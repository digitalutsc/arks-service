"""Helpers shared by the resolver views."""

from __future__ import annotations

import ipaddress
import socket
import urllib.request
from collections.abc import Iterable
from urllib.parse import quote, urlparse

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

    # request.path is already percent-decoded, but parse_ark_path decodes what
    # it is given exactly once. Re-encode so both routes decode the same number
    # of times — otherwise an identifier containing a literal '%20' resolves
    # under gunicorn and 404s under runserver.
    path = quote(request.path, safe="/:@!$&'()*+,;=~")
    query = request.META.get("QUERY_STRING", "")
    return f"{path}?{query}" if query else path


def is_support_element(name: str) -> bool:
    return SUPPORT_MARKER in name


def format_label(name: str) -> str:
    """
    'LOCAL_ID' -> 'Local_id', matching the legacy metadata display.

    Every '?' is removed, not just the '??' support marker, so 'WHERE?' shows as
    'Where' exactly as legacy rendered it.
    """
    return name.replace("?", "").strip().lower().capitalize()


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


class UnsafeTarget(Exception):
    """The bound URL must not be fetched server-side."""


class TargetTooLarge(Exception):
    """The target returned more than the manifest size limit."""


class _NoRedirects(urllib.request.HTTPRedirectHandler):
    """Refuse redirects rather than re-checking every hop."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def check_fetch_target(url: str) -> None:
    """
    Raise :class:`UnsafeTarget` unless ``url`` is safe to fetch server-side.

    The target of a /manifest request comes from a binding, which any Editor or
    bulk-bind CSV can set, and the endpoint is public. Without this the resolver
    is a fetch proxy into the host and its private network.
    """
    parsed = urlparse(url or "")
    if parsed.scheme not in ("http", "https"):
        raise UnsafeTarget(
            "Only http and https targets may be fetched; this URL uses the "
            f"{parsed.scheme or 'missing'!r} scheme."
        )
    if not parsed.hostname:
        raise UnsafeTarget("The target URL has no host.")

    try:
        resolved = socket.getaddrinfo(
            parsed.hostname, parsed.port or None, proto=socket.IPPROTO_TCP
        )
    except OSError as exc:
        raise UnsafeTarget(f"Could not resolve {parsed.hostname!r}.") from exc

    for entry in resolved:
        address = ipaddress.ip_address(entry[4][0])
        if (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_reserved
            or address.is_multicast
            or address.is_unspecified
        ):
            raise UnsafeTarget(
                f"{parsed.hostname} resolves to the internal address {address}, "
                "which this service will not fetch."
            )


def fetch_json(url: str, timeout: int | None = None, max_bytes: int | None = None) -> bytes:
    """
    Fetch ``url`` server-side and return its raw body.

    Used only by the /manifest inflection, which proxies a target's JSON (a IIIF
    manifest in practice) instead of redirecting to it. Redirects are refused,
    since following one would bypass :func:`check_fetch_target`.
    """
    timeout = timeout if timeout is not None else settings.MANIFEST_FETCH_TIMEOUT
    max_bytes = max_bytes if max_bytes is not None else settings.MANIFEST_MAX_BYTES

    check_fetch_target(url)

    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    opener = urllib.request.build_opener(_NoRedirects)
    with opener.open(request, timeout=timeout) as response:
        # Read one byte past the limit so truncation is detectable; a silently
        # truncated body would otherwise surface as an unexplained parse error.
        body = response.read(max_bytes + 1)
    if len(body) > max_bytes:
        raise TargetTooLarge(f"The target returned more than {max_bytes} bytes.")
    return body
