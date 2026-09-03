"""Helpers shared by the resolver views."""

from __future__ import annotations

import http.client
import ipaddress
import socket
import urllib.request
from collections.abc import Iterable
from dataclasses import dataclass
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
        # Legacy printed nothing at all when no element carried '??', so a bare
        # header here would make every ?? and ?info path differ at cutover.
        if support:
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


@dataclass(frozen=True)
class FetchTarget:
    """A vetted target: the address to connect to, and the host to ask for."""

    url: str
    host: str
    address: str
    port: int


def resolve_host(host: str, port: int | None) -> list[str]:
    """Every address ``host`` resolves to. Separated out so tests can steer it."""
    try:
        return [entry[4][0] for entry in socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)]
    except OSError as exc:
        raise UnsafeTarget(f"Could not resolve {host!r}.") from exc


#: NAT64 ranges. An IPv6 address here carries an IPv4 address in its low 32
#: bits, and Python reports the wrapper as global however private the address
#: inside it is — so 64:ff9b::7f00:1 would otherwise pass as public loopback.
_NAT64_PREFIXES = (
    ipaddress.ip_network("64:ff9b::/96"),
    ipaddress.ip_network("64:ff9b:1::/48"),
)


def _unwrap(address):
    """Follow IPv4-mapped and NAT64 wrappers down to the address really used."""
    if not isinstance(address, ipaddress.IPv6Address):
        return address
    if address.ipv4_mapped:
        return address.ipv4_mapped
    for prefix in _NAT64_PREFIXES:
        if address in prefix:
            return ipaddress.ip_address(int(address) & 0xFFFFFFFF)
    return address


def _is_reachable(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """
    True only for addresses on the public internet.

    ``is_global`` does most of the work — it excludes private, loopback,
    link-local, reserved, multicast and shared address space in one check, where
    testing ranges one at a time keeps missing new ones — but it is applied to
    the unwrapped address so a tunnel cannot smuggle a private one through.
    """
    return _unwrap(address).is_global


def safe_target(url: str) -> FetchTarget:
    """
    Vet ``url`` and return the exact address to connect to.

    The target of a /manifest request comes from a binding, which any Editor or
    bulk-bind CSV can set, and the endpoint is public. Returning the address —
    rather than just approving the URL — is what closes DNS rebinding: checking
    the hostname and then letting the HTTP client resolve it again lets a
    server answer with a public address for the check and a loopback address
    for the fetch.
    """
    parsed = urlparse(url or "")
    if parsed.scheme not in ("http", "https"):
        raise UnsafeTarget(
            "Only http and https targets may be fetched; this URL uses the "
            f"{parsed.scheme or 'missing'!r} scheme."
        )
    if not parsed.hostname:
        raise UnsafeTarget("The target URL has no host.")

    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    addresses = resolve_host(parsed.hostname, port)
    if not addresses:
        raise UnsafeTarget(f"Could not resolve {parsed.hostname!r}.")

    for raw in addresses:
        address = ipaddress.ip_address(raw)
        if not _is_reachable(address):
            # Any non-public answer disqualifies the host: a rebinding server
            # can otherwise return one good address among several.
            raise UnsafeTarget(
                f"{parsed.hostname} resolves to the internal address {address}, "
                "which this service will not fetch."
            )

    return FetchTarget(url=url, host=parsed.hostname, address=addresses[0], port=port)


def check_fetch_target(url: str) -> None:
    """Raise :class:`UnsafeTarget` unless ``url`` is safe to fetch server-side."""
    safe_target(url)


class _PinnedHTTPConnection(http.client.HTTPConnection):
    """Connects to a vetted address while still presenting the real Host."""

    pinned_address: str = ""

    def connect(self):
        self.sock = socket.create_connection(
            (self.pinned_address, self.port), self.timeout, self.source_address
        )


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    pinned_address: str = ""

    def connect(self):
        sock = socket.create_connection(
            (self.pinned_address, self.port), self.timeout, self.source_address
        )
        # server_hostname stays the real host so certificate validation is
        # still against the name, not the pinned address.
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


def _pinned_opener(target: FetchTarget):
    """An opener that connects only to the address already vetted."""

    class _HTTPHandler(urllib.request.HTTPHandler):
        def http_open(self, req):
            return self.do_open(_connection_factory(http_class=_PinnedHTTPConnection), req)

    class _HTTPSHandler(urllib.request.HTTPSHandler):
        def https_open(self, req):
            return self.do_open(_connection_factory(http_class=_PinnedHTTPSConnection), req)

    def _connection_factory(http_class):
        def build(host, timeout=None, **kwargs):
            kwargs.pop("context", None)
            connection = http_class(host, timeout=timeout, **kwargs)
            connection.pinned_address = target.address
            return connection

        return build

    return urllib.request.build_opener(_NoRedirects, _HTTPHandler, _HTTPSHandler)


def fetch_json(url: str, timeout: int | None = None, max_bytes: int | None = None) -> bytes:
    """
    Fetch ``url`` server-side and return its raw body.

    Used only by the /manifest inflection, which proxies a target's JSON (a IIIF
    manifest in practice) instead of redirecting to it. Redirects are refused,
    since following one would bypass the address check.
    """
    timeout = timeout if timeout is not None else settings.MANIFEST_FETCH_TIMEOUT
    max_bytes = max_bytes if max_bytes is not None else settings.MANIFEST_MAX_BYTES

    target = safe_target(url)

    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    opener = _pinned_opener(target)
    with opener.open(request, timeout=timeout) as response:
        # Read one byte past the limit so truncation is detectable; a silently
        # truncated body would otherwise surface as an unexplained parse error.
        body = response.read(max_bytes + 1)
    if len(body) > max_bytes:
        raise TargetTooLarge(f"The target returned more than {max_bytes} bytes.")
    return body
