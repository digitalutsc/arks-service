"""
Public ARK resolution.

This is the only part of the system the outside world touches, and its contract
is fixed by the ~100k ARKs already in circulation. See tests/test_resolver.py.
"""

from __future__ import annotations

import json
import logging
import threading
from typing import NamedTuple
from urllib.parse import quote

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


class Target(NamedTuple):
    """Where a redirect goes, and which qualifier its hit is counted against."""

    url: str
    counted: str


def _target_url(ark: Ark, qualifier: str) -> Target | None:
    """
    The redirect target bound at (ark, qualifier), or None.

    The collection says which elements hold it and in what order
    (``Collection.redirect_elements``, by default ``URL`` then ``WHERE?`` as in
    legacy); the first bound with a non-empty value wins. ``ark.collection`` is
    loaded with the ARK (see ``_locate``), so this is still one indexed read.

    The hit is counted against the qualifier *as stored on the binding*, not as
    requested. They differ on MySQL, whose collation matches ``/Page1`` to a
    binding at ``/page1``: counting the request's spelling would buffer a pair
    the unique (ark, qualifier) index rejects at flush time
    (INTENTS_counter_collation.md).

    Read from the database every time, through the unique (ark, qualifier,
    name) index. It used to be cached, which saved one indexed read but made the
    resolver depend on the cache server, needed every write path to invalidate
    it, and could serve an old URL for a few minutes after a rebind.
    """
    elements = ark.collection.redirect_element_list
    bindings: dict[str, tuple[str, str]] = {}
    for bound_at, name, value in ark.bindings.filter(
        qualifier=qualifier, name__in=elements
    ).values_list("qualifier", "name", "value"):
        bindings[name] = (value, bound_at)
    for name in elements:
        value, bound_at = bindings.get(name, ("", qualifier))
        if value:
            return Target(value, bound_at)
    return None


def _is_proxied(ark: Ark, qualifier: str) -> bool:
    """True when ``qualifier`` ends in one of the collection's proxied suffixes."""
    suffix = last_segment(qualifier)
    return bool(suffix) and suffix in ark.collection.proxied_suffix_list


def _resolution_target(ark: Ark, qualifier: str) -> Target | None:
    """
    The URL a non-metadata request for ``qualifier`` is answered from, or None.

    For a proxied suffix (``…/manifest`` by default) that is the URL bound at
    the suffix qualifier itself, as legacy did (a pre-generated IIIF manifest
    bound at ``/manifest``), or else the URL of what the suffix is attached to.
    For anything else it is the URL at exactly ``qualifier``: no walk up the
    hierarchy here (suffix passthrough, when a collection turns it on, is a
    separate last resort: ``_passthrough``).
    """
    target = _target_url(ark, qualifier)
    if target is None and _is_proxied(ark, qualifier):
        target = _target_url(ark, parent_qualifier(qualifier))
    return target


#: Path segments a passthrough never appends: they would step out of the
#: target's directory once a browser or server normalises the URL.
_DOT_SEGMENTS = {".", ".."}

#: Characters left as they are when a passthrough segment is re-encoded: RFC
#: 3986 'pchar' minus '%' (so any literal '%' is encoded) and minus '/'.
_SEGMENT_SAFE = "!$&'()*+,;=:@-._~"


def _passthrough(ark: Ark, qualifier: str) -> Target | None:
    """
    Suffix passthrough (R6): ``<nearest bound ancestor's URL>/<rest of the path>``.

    Only when the ARK's collection turns it on, only for a hierarchy part
    ('/page7', not an object variant '.png'), never for a proxied suffix, and
    never for a path with '.' or '..' segments. The nearest ancestor is found in
    one query over every level above ``qualifier`` (the exact qualifier itself
    has already missed); the hit is counted against that ancestor, so a made-up
    path never creates a counter row of its own.
    """
    collection = ark.collection
    if not collection.suffix_passthrough or not qualifier.startswith("/"):
        return None
    if _is_proxied(ark, qualifier):
        return None
    segments = qualifier.split("/")[1:]
    if any(segment in _DOT_SEGMENTS for segment in segments):
        return None

    ancestors = ["/" + "/".join(segments[:depth]) for depth in range(len(segments) - 1, 0, -1)]
    ancestors.append("")
    elements = collection.redirect_element_list
    found: dict[str, dict[str, str]] = {}
    for bound_at, name, value in ark.bindings.filter(
        qualifier__in=ancestors, name__in=elements
    ).values_list("qualifier", "name", "value"):
        found.setdefault(bound_at, {})[name] = value

    for ancestor in ancestors:  # nearest first
        values = found.get(ancestor, {})
        url = next((values[name] for name in elements if values.get(name)), None)
        if url:
            rest = segments[len(ancestor.split("/")) - 1 if ancestor else 0 :]
            path = "/".join(quote(segment, safe=_SEGMENT_SAFE) for segment in rest)
            return Target(f"{url.rstrip('/')}/{path}", ancestor)
    return None


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


def _locate(parsed: ArkPath, probe, fallback=None) -> tuple[ArkPath, Ark | None, object]:
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

    ``fallback`` (suffix passthrough) is a last resort: it runs only once every
    reading has missed ``probe`` exactly, over the same readings in the same
    order, so an exact binding at any reading always beats it.
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

    alternatives = list(parsed.alternatives())
    for form in alternatives:
        alt_ark = ark_for(form)
        alt_found = probe(alt_ark, form.qualifier) if alt_ark is not None else None
        if alt_found is not None:
            return form, alt_ark, alt_found

    if fallback is not None:
        for form in [parsed, *alternatives]:
            form_ark = ark_for(form)
            last_resort = fallback(form_ark, form.qualifier) if form_ark is not None else None
            if last_resort is not None:
                return form, form_ark, last_resort
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

    parsed, ark, target = _locate(parsed, _resolution_target, fallback=_passthrough)
    if ark is None:
        raise Http404(f"Unknown ARK {parsed.name}")
    if not target:
        raise Http404(f"Nothing bound to {parsed.name}{parsed.qualifier}")

    if _is_proxied(ark, parsed.qualifier):
        return _manifest(ark, target.url)

    # Buffered, so a redirect stays a pure read: see core.counters. Counted
    # against the qualifier that actually resolved (a hyphenated spelling adds
    # to the stored ARK's count), or for a passthrough against the ancestor
    # that supplied the URL, so made-up paths never start rows of their own.
    record_resolution(ark.pk, target.counted)
    return HttpResponseRedirect(target.url)


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
