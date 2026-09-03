"""
Public ARK resolution.

This is the only part of the system the outside world touches, and its contract
is fixed by the ~100k ARKs already in circulation. See tests/test_resolver.py.
"""

from __future__ import annotations

import json
import logging

from django.db.models import Q
from django.http import (
    Http404,
    HttpResponse,
    HttpResponseRedirect,
    JsonResponse,
)
from django.shortcuts import render

from core.arkpath import Inflection, parse_ark_path
from core.models import ELEMENT_URL, ELEMENT_WHERE, Ark, Collection, Organisation, Resolution
from resolver.services import (
    TargetTooLarge,
    UnsafeTarget,
    fetch_json,
    raw_request_uri,
    render_erc,
)

logger = logging.getLogger(__name__)


def _target_url(ark: Ark, qualifier: str) -> str | None:
    """The redirect target for an exact (ark, qualifier), or None."""
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

    Resolution.record(ark, parsed.qualifier)
    return HttpResponseRedirect(target)


def _manifest(ark: Ark, qualifier: str) -> HttpResponse:
    """Proxy the target's JSON rather than redirecting to it (IIIF pass-through)."""
    target = _target_url(ark, qualifier)
    if not target:
        raise Http404(f"Nothing bound to {ark.name}{qualifier}")

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
    except Exception:
        logger.warning("manifest fetch failed for %s -> %s", ark.name, target, exc_info=True)
        return JsonResponse({"error": "Could not fetch the manifest."}, status=502)

    try:
        payload = json.loads(body)
    except (ValueError, TypeError):
        logger.warning("manifest at %s was not JSON", target)
        return JsonResponse({"error": "The target did not return JSON."}, status=502)

    return JsonResponse(payload, safe=False)


def landing(request):
    """Minimal public page: who runs this service and what an ARK is."""
    return render(
        request,
        "resolver/landing.html",
        {
            "organisation": Organisation.load(),
            "collections": Collection.objects.exclude(naan="").order_by("name"),
        },
    )
