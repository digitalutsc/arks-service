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
