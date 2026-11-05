"""
Public ARK resolution.

This is the only part of the system the outside world touches, and its contract
is fixed by the ~100k ARKs already in circulation. See tests/test_resolver.py.
"""

from __future__ import annotations

import json
import logging
import threading

from django.conf import settings
from django.db.models import Q
from django.http import (
    Http404,
    HttpResponse,
    HttpResponseRedirect,
    JsonResponse,
)
from django.shortcuts import render

from core.arkpath import Inflection, parse_ark_path
from core.counters import record_resolution
from core.models import ELEMENT_URL, ELEMENT_WHERE, Ark, Collection, Organisation
from resolver.services import (
    TargetTooLarge,
    TargetTooSlow,
    UnsafeTarget,
    fetch_json,
    raw_request_uri,
    render_erc,
)

logger = logging.getLogger(__name__)


def _target_url(ark: Ark, qualifier: str) -> str | None:
    """
    The redirect target for an exact (ark, qualifier), or None.

    Read from the database every time, through the unique (ark, qualifier,
    name) index. It used to be cached, which saved one indexed read but made the
    resolver depend on the cache server, needed every write path to invalidate
    it, and could serve an old URL for a few minutes after a rebind.
    """
    bindings = {
        b.name: b.value
        for b in ark.bindings.filter(qualifier=qualifier, name__in=[ELEMENT_URL, ELEMENT_WHERE])
    }
    return bindings.get(ELEMENT_URL) or bindings.get(ELEMENT_WHERE) or None


def _metadata_bindings(ark: Ark, qualifier: str):
    """
    The elements an inflection should show for ``qualifier``.

    Legacy matched "<ark>\t[^/]" for a bare ARK — any key whose next component
    is not a hierarchy — so a variant-only qualifier such as ".image.png" was
    listed alongside the ARK's own elements, while "/page1" was not. A request
    that names a qualifier matches that qualifier exactly.
    """
    if qualifier:
        return ark.bindings.filter(qualifier=qualifier)
    return ark.bindings.filter(Q(qualifier="") | Q(qualifier__startswith="."))


def _naa_response(naan: str) -> HttpResponse:
    """A bare NAAN returns the Name Assigning Authority, as the legacy service did."""
    naa = Collection.objects.filter(naan=naan).exclude(naa="").values_list("naa", flat=True).first()
    if not naa:
        raise Http404(f"No name assigning authority for NAAN {naan}")
    return HttpResponse(naa + "\n", content_type="text/plain; charset=utf-8")


def resolve(request, *args, **kwargs):
    """Resolve any /ark:... request."""
    parsed = parse_ark_path(raw_request_uri(request))
    if parsed is None:
        raise Http404("Not an ARK")

    if parsed.naan_only:
        return _naa_response(parsed.naan)

    ark = Ark.objects.filter(naan=parsed.naan, identifier=parsed.identifier).first()
    if ark is None:
        raise Http404(f"Unknown ARK {parsed.name}")

    # An explicit inflection wins over /manifest: legacy only treated a request
    # as a manifest when the URI *ended* in "/manifest", so a trailing '?' sent
    # it down the metadata path instead.
    if parsed.inflection is not Inflection.NONE:
        body = render_erc(
            _metadata_bindings(ark, parsed.qualifier),
            include_support=parsed.inflection is Inflection.FULL,
        )
        return HttpResponse(body, content_type="text/plain; charset=utf-8")

    if parsed.manifest:
        return _manifest(ark, parsed.qualifier)

    target = _target_url(ark, parsed.qualifier)
    if not target:
        raise Http404(f"Nothing bound to {parsed.name}{parsed.qualifier}")

    # Buffered, so a redirect stays a pure read: see core.counters.
    record_resolution(ark.pk, parsed.qualifier)
    return HttpResponseRedirect(target)


_manifest_slots_lock = threading.Lock()
_manifest_slots: tuple[int, threading.BoundedSemaphore] | None = None


def _manifest_slots_for(size: int) -> threading.BoundedSemaphore:
    """This process's semaphore for /manifest fetches, rebuilt if the setting changes."""
    global _manifest_slots
    with _manifest_slots_lock:
        if _manifest_slots is None or _manifest_slots[0] != size:
            _manifest_slots = (size, threading.BoundedSemaphore(size))
        return _manifest_slots[1]


def _manifest(ark: Ark, qualifier: str) -> HttpResponse:
    """
    Proxy the target's JSON rather than redirecting to it (IIIF pass-through).

    Each fetch holds a gunicorn thread on someone else's server, and the
    endpoint is public, so at most MANIFEST_MAX_CONCURRENT fetches run per
    process; past that the caller is told to retry rather than queueing behind
    them and starving ordinary redirects.
    """
    target = _target_url(ark, qualifier)
    if not target:
        raise Http404(f"Nothing bound to {ark.name}{qualifier}")

    slots = _manifest_slots_for(max(1, settings.MANIFEST_MAX_CONCURRENT))
    if not slots.acquire(blocking=False):
        response = JsonResponse({"error": "Too many manifest requests; retry shortly."}, status=503)
        response["Retry-After"] = "5"
        return response
    try:
        return _proxy_manifest(ark, target)
    finally:
        slots.release()


def _proxy_manifest(ark: Ark, target: str) -> HttpResponse:
    try:
        body = fetch_json(target)
    except UnsafeTarget as exc:
        # Worth its own line: this is a misconfigured or malicious binding, not
        # an unreachable target, and the two need different remedies.
        logger.warning("manifest target refused for %s -> %s: %s", ark.name, target, exc)
        return JsonResponse({"error": "The bound URL may not be fetched."}, status=502)
    except TargetTooLarge as exc:
        logger.warning("manifest too large for %s -> %s: %s", ark.name, target, exc)
        return JsonResponse({"error": "The manifest is too large to proxy."}, status=502)
    except TargetTooSlow as exc:
        logger.warning("manifest too slow for %s -> %s: %s", ark.name, target, exc)
        return JsonResponse({"error": "The manifest took too long to fetch."}, status=504)
    except Exception:
        logger.warning("manifest fetch failed for %s -> %s", ark.name, target, exc_info=True)
        return JsonResponse({"error": "Could not fetch the manifest."}, status=502)

    try:
        json.loads(body)
    except (ValueError, TypeError):
        logger.warning("manifest at %s was not JSON", target)
        return JsonResponse({"error": "The target did not return JSON."}, status=502)

    # Validated, then passed through as received: re-serialising a large
    # manifest cost a second copy of it in memory for no change in meaning.
    return HttpResponse(body, content_type="application/json")


def landing(request):
    """Minimal public page: who runs this service and what an ARK is."""
    from resolver.fallback import landing_response

    configured = landing_response()
    if configured is not None:
        return configured
    return render(
        request,
        "resolver/landing.html",
        {
            "organisation": Organisation.load(),
            "collections": Collection.objects.exclude(naan="").order_by("name"),
        },
    )
