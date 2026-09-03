"""Helpers shared by the resolver views."""

from __future__ import annotations

import urllib.request
from collections.abc import Iterable

from django.conf import settings
from django.http import HttpRequest

#: Elements that are bookkeeping, never shown as metadata.
INTERNAL_ELEMENTS = {"REDIRECT", ":/C", ":/H"}

#: An element whose name contains this marker is ERC *support* metadata,
#: matching how the legacy service tagged it.
SUPPORT_MARKER = "??"


def raw_request_uri(request: HttpRequest) -> str:
    """
    The request URI as it arrived, including a trailing bare '?'.

    Django drops a '?' with nothing after it, and that character is the
    difference between a redirect and a metadata request. Gunicorn exposes the
    original request line as ``RAW_URI``; other servers may set ``REQUEST_URI``.
    The final fallback cannot recover a bare '?', so production must run behind
    a server that provides one of them (see deploy/README).
    """
    raw = request.META.get("RAW_URI") or request.META.get("REQUEST_URI")
    if raw:
        return raw
    query = request.META.get("QUERY_STRING", "")
    return f"{request.path}?{query}" if query else request.path


def is_support_element(name: str) -> bool:
    return SUPPORT_MARKER in name


def format_label(name: str) -> str:
    """'LOCAL_ID' -> 'Local_id', matching the legacy metadata display."""
    return name.replace(SUPPORT_MARKER, "").strip().lower().capitalize()


def render_erc(bindings: Iterable, include_support: bool) -> str:
    """
    Render the ERC metadata block(s) for a set of bindings.

    Values are emitted verbatim. (The legacy implementation replaced
    underscores with spaces, which corrupted any URL containing one.)
    """
    shown = [b for b in bindings if b.name.upper() not in INTERNAL_ELEMENTS]
    brief = [b for b in shown if not is_support_element(b.name)]

    lines = ["erc:"]
    lines += [f"{format_label(b.name)}: {b.value}" for b in brief]

    if include_support:
        support = [b for b in shown if is_support_element(b.name)]
        lines.append("")
        lines.append("erc-support:")
        lines += [f"{format_label(b.name)}: {b.value}" for b in support]

    return "\n".join(lines) + "\n"


def fetch_json(url: str, timeout: int | None = None, max_bytes: int | None = None) -> bytes:
    """
    Fetch ``url`` server-side and return its raw body.

    Used only by the /manifest inflection, which proxies a target's JSON (a IIIF
    manifest in practice) instead of redirecting to it.
    """
    timeout = timeout if timeout is not None else settings.MANIFEST_FETCH_TIMEOUT
    max_bytes = max_bytes if max_bytes is not None else settings.MANIFEST_MAX_BYTES
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        return response.read(max_bytes)
