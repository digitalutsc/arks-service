"""
Guardrails on the /manifest proxy.

/manifest is the one place the resolver fetches a URL server-side, and the
target comes from a binding — which any Editor, or any bulk-bind CSV, can set.
Without restrictions the public endpoint becomes a fetch proxy into the host and
its network.
"""

import pytest

from resolver.services import UnsafeTarget, check_fetch_target


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://example.org/x",
        "gopher://example.org/",
        "data:application/json,{}",
        "//example.org/x",
        "",
    ],
)
def test_only_http_and_https_may_be_fetched(url):
    with pytest.raises(UnsafeTarget, match="(?i)scheme|url"):
        check_fetch_target(url)


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/admin",
        "http://localhost:8000/",
        "http://[::1]/",
        "http://169.254.169.254/latest/meta-data/",
        "http://10.0.0.5/internal",
        "http://192.168.1.1/",
        "http://172.16.0.1/",
        "http://0.0.0.0/",
    ],
)
def test_internal_addresses_are_refused(url):
    with pytest.raises(UnsafeTarget, match="(?i)internal|private|resolve"):
        check_fetch_target(url)


@pytest.mark.parametrize("url", ["https://example.org/manifest", "http://93.184.216.34/x"])
def test_public_targets_are_allowed(url):
    check_fetch_target(url)


def test_a_host_that_does_not_resolve_is_refused():
    with pytest.raises(UnsafeTarget, match="(?i)resolve"):
        check_fetch_target("http://no-such-host.invalid/x")


# --- the address that was vetted must be the address that is used ----------


def test_the_vetted_address_is_the_one_connected_to(monkeypatch):
    # check_fetch_target resolved the hostname, then urlopen resolved it again.
    # A DNS server answering 1.2.3.4 on the first lookup and 127.0.0.1 on the
    # second turned /manifest into a proxy for anything on the host.
    import resolver.services as services

    answers = iter([["93.184.216.34"], ["127.0.0.1"]])
    monkeypatch.setattr(services, "resolve_host", lambda host, port: next(answers))

    with pytest.raises(UnsafeTarget, match="(?i)internal|address"):
        # First call vets 93.184.216.34; the connection must not be allowed to
        # re-resolve and land somewhere else.
        services.safe_target("http://rebind.example/manifest")
        services.safe_target("http://rebind.example/manifest")


def test_a_host_resolving_to_both_public_and_private_is_refused(monkeypatch):
    import resolver.services as services

    monkeypatch.setattr(services, "resolve_host", lambda host, port: ["93.184.216.34", "10.0.0.5"])
    with pytest.raises(UnsafeTarget, match="(?i)internal"):
        services.safe_target("http://mixed.example/x")


def test_safe_target_reports_the_address_to_connect_to(monkeypatch):
    import resolver.services as services

    monkeypatch.setattr(services, "resolve_host", lambda host, port: ["93.184.216.34"])
    target = services.safe_target("https://example.org/manifest")
    assert target.address == "93.184.216.34"
    assert target.host == "example.org"


@pytest.mark.parametrize("address", ["64:ff9b::7f00:1", "0100::1", "100.64.0.1"])
def test_non_global_addresses_are_refused(monkeypatch, address):
    # NAT64 and shared-address space are not "private" by ipaddress's reckoning
    # but must not be reachable either.
    import resolver.services as services

    monkeypatch.setattr(services, "resolve_host", lambda host, port: [address])
    with pytest.raises(UnsafeTarget, match="(?i)internal|address"):
        services.safe_target("http://nat64.example/x")


# --- overall deadline and size, against a real local server ---------------


class _Server:
    """A local HTTP server whose response is scripted per test."""

    def __init__(self, handler_body):
        import http.server
        import threading

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                handler_body(self)

            def log_message(self, *args):
                pass

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def local_target(monkeypatch):
    """Point the fetcher at a loopback server, bypassing the address check."""
    from resolver import services

    servers = []

    def start(handler_body):
        server = _Server(handler_body)
        servers.append(server)
        url = f"http://127.0.0.1:{server.port}/manifest.json"
        monkeypatch.setattr(
            services,
            "safe_target",
            lambda u: services.FetchTarget(
                url=u, host="127.0.0.1", address="127.0.0.1", port=server.port
            ),
        )
        return url

    yield start
    for server in servers:
        server.close()


def test_a_trickling_server_is_cut_off_by_the_overall_deadline(local_target):
    # Each read arrives well inside the per-read timeout, so only an overall
    # deadline stops this from holding the thread for the whole drip.
    import time

    from resolver.services import TargetTooSlow, fetch_json

    def drip(handler):
        handler.send_response(200)
        handler.send_header("Content-Type", "application/json")
        handler.end_headers()
        for _ in range(50):
            try:
                handler.wfile.write(b" ")
                handler.wfile.flush()
            except OSError:
                return
            time.sleep(0.1)

    url = local_target(drip)
    started = time.monotonic()
    with pytest.raises(TargetTooSlow):
        fetch_json(url, timeout=2, max_bytes=1_000_000, total_timeout=0.5)
    assert time.monotonic() - started < 2.5


def test_a_declared_oversize_body_is_refused_before_reading(local_target):
    from resolver.services import TargetTooLarge, fetch_json

    def big(handler):
        handler.send_response(200)
        handler.send_header("Content-Length", "5000")
        handler.end_headers()
        handler.wfile.write(b"{" + b" " * 4998 + b"}")

    url = local_target(big)
    with pytest.raises(TargetTooLarge, match="declared"):
        fetch_json(url, timeout=2, max_bytes=100, total_timeout=5)


def test_an_undeclared_oversize_body_is_refused(local_target):
    from resolver.services import TargetTooLarge, fetch_json

    def big(handler):
        handler.send_response(200)
        handler.end_headers()
        handler.wfile.write(b"[" + b"0," * 200 + b"0]")

    url = local_target(big)
    with pytest.raises(TargetTooLarge):
        fetch_json(url, timeout=2, max_bytes=100, total_timeout=5)


def test_a_normal_body_is_returned_whole(local_target):
    from resolver.services import fetch_json

    body = b'{"type": "Manifest", "items": [' + b"1," * 50_000 + b"1]}"

    def ok(handler):
        handler.send_response(200)
        handler.send_header("Content-Length", str(len(body)))
        handler.end_headers()
        handler.wfile.write(body)

    url = local_target(ok)
    assert fetch_json(url, timeout=2, max_bytes=1_000_000, total_timeout=5) == body
