"""
Public ARK resolution.

This is the only part of the system the outside world touches, and its contract
is fixed by the ~100k ARKs already in circulation. See tests/test_resolver.py.
"""

from __future__ import annotations

import json
import logging

from django.http import (
    Http404,
    HttpResponse,
    HttpResponseRedirect,
    JsonResponse,
)
from django.shortcuts import render

from core.arkpath import Inflection, parse_ark_path
from core.models import ELEMENT_URL, ELEMENT_WHERE, Ark, Collection, Organisation, Resolution
from resolver.services import fetch_json, raw_request_uri, render_erc

logger = logging.getLogger(__name__)


def _target_url(ark: Ark, qualifier: str) -> str | None:
    """The redirect target for an exact (ark, qualifier), or None."""
    bindings = {
        b.name: b.value
        for b in ark.bindings.filter(qualifier=qualifier, name__in=[ELEMENT_URL, ELEMENT_WHERE])
    }
    return bindings.get(ELEMENT_URL) or bindings.get(ELEMENT_WHERE) or None


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

    if parsed.manifest:
        return _manifest(ark, parsed.qualifier)

    if parsed.inflection is not Inflection.NONE:
        bindings = ark.bindings.filter(qualifier=parsed.qualifier)
        body = render_erc(bindings, include_support=parsed.inflection is Inflection.FULL)
        return HttpResponse(body, content_type="text/plain; charset=utf-8")

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
