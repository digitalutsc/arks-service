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

from core.arkpath import ArkPath, Inflection, last_segment, parent_qualifier, parse_ark_path
from core.counters import record_resolution
from core.models import Ark, Collection, Organisation
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

    The collection says which elements hold it and in what order
    (``Collection.redirect_elements``, by default ``URL`` then ``WHERE?`` as in
    legacy); the first bound with a non-empty value wins. ``ark.collection`` is
    loaded with the ARK (see ``_locate``), so this is still one indexed read.

    Read from the database every time, through the unique (ark, qualifier,
    name) index. It used to be cached, which saved one indexed read but made the
    resolver depend on the cache server, needed every write path to invalidate
    it, and could serve an old URL for a few minutes after a rebind.
    """
    elements = ark.collection.redirect_element_list
    bindings = dict(
        ark.bindings.filter(qualifier=qualifier, name__in=elements).values_list("name", "value")
    )
    return next((bindings[name] for name in elements if bindings.get(name)), None)


def _is_proxied(ark: Ark, qualifier: str) -> bool:
    """True when ``qualifier`` ends in one of the collection's proxied suffixes."""
    suffix = last_segment(qualifier)
    return bool(suffix) and suffix in ark.collection.proxied_suffix_list


def _resolution_target(ark: Ark, qualifier: str) -> str | None:
    """
    The URL a non-metadata request for ``qualifier`` is answered from, or None.

    For a proxied suffix (``…/manifest`` by default) that is the URL bound at
    the suffix qualifier itself, as legacy did (a pre-generated IIIF manifest
    bound at ``/manifest``), or else the URL of what the suffix is attached to.
    For anything else it is the URL at exactly ``qualifier``: no walk up the
    hierarchy.
    """
    target = _target_url(ark, qualifier)
    if target is None and _is_proxied(ark, qualifier):
        target = _target_url(ark, parent_qualifier(qualifier))
    return target


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


def _has_metadata(ark: Ark, qualifier: str) -> list | None:
    """The bindings an inflection would show at ``qualifier``, or None when there are none."""
    return list(_metadata_bindings(ark, qualifier)) or None


def _locate(parsed: ArkPath, probe) -> tuple[ArkPath, Ark | None, object]:
    """
    Find what ``parsed`` names: ``(form that matched, ark, probe's answer)``.

    The request is looked up exactly as written first, which is the legacy
    contract and costs the usual reads. Only when that misses (no such ARK, or
    ``probe(ark, qualifier)`` returns None) are its other readings tried, in
    ``ArkPath.alternatives()`` order: a variant of the object (``utsc1.pdf`` as
    ``utsc1`` + ``.pdf``), then the spec-normalised form, with hyphens and a
    trailing '.' removed (draft-kunze-ark-44 §3.2; arks.org strips hyphens
    before forwarding). On a total miss the request as written is returned, so
    its 404 or empty answer is the one it always had.
    """
    arks: dict[str, Ark | None] = {}

    def ark_for(form: ArkPath) -> Ark | None:
        # The collection comes in the same query: its settings decide what
        # the probes look for, and a redirect must stay at two reads.
        if form.identifier not in arks:
            arks[form.identifier] = (
                Ark.objects.select_related("collection")
                .filter(naan=form.naan, identifier=form.identifier)
                .first()
            )
        return arks[form.identifier]

    ark = ark_for(parsed)
    found = probe(ark, parsed.qualifier) if ark is not None else None
    if found is not None:
        return parsed, ark, found

    for form in parsed.alternatives():
        alt_ark = ark_for(form)
        alt_found = probe(alt_ark, form.qualifier) if alt_ark is not None else None
        if alt_found is not None:
            return form, alt_ark, alt_found
    return parsed, ark, found


def resolve(request, *args, **kwargs):
    """Resolve any /ark:... request."""
    parsed = parse_ark_path(raw_request_uri(request))
    if parsed is None:
        raise Http404("Not an ARK")

    if parsed.naan_only:
        return _naa_response(parsed.naan)

    # An explicit inflection wins over a proxied suffix: legacy only treated a
    # request as a manifest when the URI *ended* in "/manifest", so a trailing
    # '?' sent it down the metadata path instead, describing the qualifier
    # '/manifest' itself (legacy built the qualifier from every path part).
    if parsed.inflection is not Inflection.NONE:
        parsed, ark, bindings = _locate(parsed, _has_metadata)
        if ark is None:
            raise Http404(f"Unknown ARK {parsed.name}")
        body = render_erc(
            bindings or (),
            include_support=parsed.inflection is Inflection.FULL,
        )
        return HttpResponse(body, content_type="text/plain; charset=utf-8")

    parsed, ark, target = _locate(parsed, _resolution_target)
    if ark is None:
        raise Http404(f"Unknown ARK {parsed.name}")
    if not target:
        raise Http404(f"Nothing bound to {parsed.name}{parsed.qualifier}")

    if _is_proxied(ark, parsed.qualifier):
        return _manifest(ark, target)

    # Buffered, so a redirect stays a pure read: see core.counters. Counted
    # against the qualifier that actually resolved, so a hyphenated spelling
    # adds to the stored ARK's count rather than starting a row of its own.
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


def _manifest(ark: Ark, target: str) -> HttpResponse:
    """
    Proxy the target's JSON rather than redirecting to it (IIIF pass-through).

    Each fetch holds a gunicorn thread on someone else's server, and the
    endpoint is public, so at most MANIFEST_MAX_CONCURRENT fetches run per
    process; past that the caller is told to retry rather than queueing behind
    them and starving ordinary redirects.

    Every answer, error or not, may be read by a page on another site: a IIIF
    viewer loads the manifest with fetch(), and without this header the browser
    hides even the error from it. The response is public and anonymous (no
    cookies, nothing credentialed), so any origin is fine, and the source sites
    send the same header. Only manifest responses carry it.
    """
    slots = _manifest_slots_for(max(1, settings.MANIFEST_MAX_CONCURRENT))
    if not slots.acquire(blocking=False):
        response = JsonResponse({"error": "Too many manifest requests; retry shortly."}, status=503)
        response["Retry-After"] = "5"
    else:
        try:
            response = _proxy_manifest(ark, target)
        finally:
            slots.release()
    response["Access-Control-Allow-Origin"] = "*"
    return response


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
