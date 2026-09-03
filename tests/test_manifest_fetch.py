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
