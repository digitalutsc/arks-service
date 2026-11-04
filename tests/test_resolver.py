"""
The resolver contract.

Every behaviour here exists in the legacy service and must keep working for the
~100k production ARKs: exact-qualifier redirects with a WHERE? fallback, no
ancestor fallback, the ?/??/?info metadata inflections, /manifest JSON
proxying, the redirect counter, and the NAA response for a bare NAAN.
"""

import json

import pytest

from core.models import Ark, Binding, Collection, Organisation, Resolution

pytestmark = pytest.mark.django_db


@pytest.fixture
def collection():
    return Collection.objects.create(
        name="UTSC", prefix="utsc", naan="61220", naa="UTSC Library", template=".zd"
    )


@pytest.fixture
def ark(collection):
    return Ark.objects.create(collection=collection, identifier="utsc1")


def get(client, path, raw=None):
    """Issue a request, preserving the raw URI so a trailing '?' survives."""
    return client.get(path, RAW_URI=raw if raw is not None else path)


# --- redirection ----------------------------------------------------------


def test_redirects_to_the_bound_url(client, ark):
    Binding.objects.create(ark=ark, name="URL", value="https://example.org/item/1")
    response = get(client, "/ark:/61220/utsc1")
    assert response.status_code == 302
    assert response["Location"] == "https://example.org/item/1"


def test_redirects_the_slashless_form_the_admin_ui_links_to(client, ark):
    Binding.objects.create(ark=ark, name="URL", value="https://example.org/item/1")
    response = get(client, f"/{ark.path}")
    assert ark.path == "ark:61220/utsc1"
    assert response.status_code == 302
    assert response["Location"] == "https://example.org/item/1"


def test_falls_back_to_where_when_there_is_no_url(client, ark):
    Binding.objects.create(ark=ark, name="WHERE?", value="https://fallback.example/1")
    response = get(client, "/ark:/61220/utsc1")
    assert response.status_code == 302
    assert response["Location"] == "https://fallback.example/1"


def test_url_wins_over_where(client, ark):
    Binding.objects.create(ark=ark, name="URL", value="https://primary.example")
    Binding.objects.create(ark=ark, name="WHERE?", value="https://fallback.example")
    assert get(client, "/ark:/61220/utsc1")["Location"] == "https://primary.example"


def test_unbound_ark_is_not_found(client, ark):
    assert get(client, "/ark:/61220/utsc1").status_code == 404


def test_unknown_ark_is_not_found(client, collection):
    assert get(client, "/ark:/61220/nosuchark").status_code == 404


def test_unknown_naan_is_not_found(client, collection):
    assert get(client, "/ark:/99999/utsc1").status_code == 404


# --- qualifiers -----------------------------------------------------------


def test_resolves_a_hierarchical_part_to_its_own_url(client, ark):
    Binding.objects.create(ark=ark, name="URL", value="https://example.org/whole")
    Binding.objects.create(ark=ark, qualifier="/page1", name="URL", value="https://example.org/p1")
    assert get(client, "/ark:/61220/utsc1/page1")["Location"] == "https://example.org/p1"


def test_resolves_a_variant(client, ark):
    Binding.objects.create(
        ark=ark, qualifier="/page1.image.png", name="URL", value="https://example.org/p1.png"
    )
    response = get(client, "/ark:/61220/utsc1/page1.image.png")
    assert response["Location"] == "https://example.org/p1.png"


def test_a_qualifier_without_its_own_binding_does_not_fall_back_to_the_parent(client, ark):
    # Legacy behaviour: exact match only, no walking up the hierarchy.
    Binding.objects.create(ark=ark, name="URL", value="https://example.org/whole")
    assert get(client, "/ark:/61220/utsc1/page9").status_code == 404


# --- redirect counter -----------------------------------------------------


def test_each_redirect_is_counted(client, ark):
    from core.counters import flush_counters

    Binding.objects.create(ark=ark, name="URL", value="https://example.org/1")
    get(client, "/ark:/61220/utsc1")
    get(client, "/ark:/61220/utsc1")
    flush_counters()  # counting is buffered so a redirect stays a pure read
    assert Resolution.objects.get(ark=ark, qualifier="").count == 2


def test_counts_are_kept_per_qualifier(client, ark):
    from core.counters import flush_counters

    Binding.objects.create(ark=ark, name="URL", value="https://example.org/whole")
    Binding.objects.create(ark=ark, qualifier="/page1", name="URL", value="https://example.org/p1")
    get(client, "/ark:/61220/utsc1")
    get(client, "/ark:/61220/utsc1/page1")
    get(client, "/ark:/61220/utsc1/page1")
    flush_counters()
    assert Resolution.objects.get(ark=ark, qualifier="").count == 1
    assert Resolution.objects.get(ark=ark, qualifier="/page1").count == 2


def test_counts_lag_until_they_are_flushed(client, ark):
    # The documented trade: a redirect performs no write, so the counter is
    # behind by up to one flush interval and a cache outage loses that window.
    Binding.objects.create(ark=ark, name="URL", value="https://example.org/1")
    get(client, "/ark:/61220/utsc1")
    assert not Resolution.objects.filter(ark=ark).exists()


def test_a_metadata_request_is_not_counted_as_a_redirect(client, ark):
    Binding.objects.create(ark=ark, name="URL", value="https://example.org/1")
    get(client, "/ark:/61220/utsc1?", raw="/ark:/61220/utsc1?")
    assert Resolution.objects.filter(ark=ark).count() == 0


# --- inflections ----------------------------------------------------------


def test_single_question_mark_returns_brief_metadata(client, ark):
    Binding.objects.create(ark=ark, name="URL", value="https://example.org/1")
    Binding.objects.create(ark=ark, name="WHO", value="Anonymous")
    response = get(client, "/ark:/61220/utsc1?", raw="/ark:/61220/utsc1?")
    body = response.content.decode()
    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/plain")
    assert body.startswith("erc:")
    assert "Anonymous" in body
    assert "erc-support:" not in body


def test_double_question_mark_adds_the_support_block(client, ark):
    Binding.objects.create(ark=ark, name="WHO", value="Anonymous")
    Binding.objects.create(ark=ark, name="WHO??", value="Support note")
    body = get(client, "/ark:/61220/utsc1??", raw="/ark:/61220/utsc1??").content.decode()
    assert "erc:" in body
    assert "erc-support:" in body
    assert "Support note" in body
    assert body.index("erc:") < body.index("erc-support:")


def test_question_info_behaves_like_double_question_mark(client, ark):
    Binding.objects.create(ark=ark, name="WHO??", value="Support note")
    body = get(client, "/ark:/61220/utsc1?info", raw="/ark:/61220/utsc1?info").content.decode()
    assert "erc-support:" in body


def test_brief_metadata_excludes_support_elements(client, ark):
    Binding.objects.create(ark=ark, name="WHO", value="Shown")
    Binding.objects.create(ark=ark, name="WHO??", value="Hidden")
    body = get(client, "/ark:/61220/utsc1?", raw="/ark:/61220/utsc1?").content.decode()
    assert "Shown" in body
    assert "Hidden" not in body


def test_metadata_excludes_the_internal_redirect_counter(client, ark):
    Binding.objects.create(ark=ark, name="URL", value="https://example.org/1")
    Binding.objects.create(ark=ark, name="REDIRECT", value="7")
    body = get(client, "/ark:/61220/utsc1?", raw="/ark:/61220/utsc1?").content.decode()
    assert "REDIRECT" not in body.upper().replace("REDIRECTS", "")


def test_metadata_values_are_not_mangled(client, ark):
    # Legacy replaced underscores with spaces in values, corrupting URLs.
    Binding.objects.create(ark=ark, name="URL", value="https://example.org/my_file_name")
    body = get(client, "/ark:/61220/utsc1?", raw="/ark:/61220/utsc1?").content.decode()
    assert "https://example.org/my_file_name" in body


def test_metadata_is_scoped_to_the_requested_qualifier(client, ark):
    Binding.objects.create(ark=ark, name="WHO", value="Whole object")
    Binding.objects.create(ark=ark, qualifier="/page1", name="WHO", value="Just page one")
    body = get(client, "/ark:/61220/utsc1/page1?", raw="/ark:/61220/utsc1/page1?").content.decode()
    assert "Just page one" in body
    assert "Whole object" not in body


# --- NAA ------------------------------------------------------------------


def test_bare_naan_returns_the_name_assigning_authority(client, collection):
    response = get(client, "/ark:/61220/")
    assert response.status_code == 200
    assert "UTSC Library" in response.content.decode()


def test_bare_unknown_naan_is_not_found(client, collection):
    assert get(client, "/ark:/99999/").status_code == 404


# --- manifest -------------------------------------------------------------


def test_manifest_proxies_the_targets_json(client, ark, monkeypatch):
    Binding.objects.create(ark=ark, name="URL", value="https://example.org/item/1")
    manifest = {"@context": "http://iiif.io/api/presentation/3/context.json", "type": "Manifest"}

    def fake_fetch(url, **kwargs):
        assert url == "https://example.org/item/1"
        return json.dumps(manifest).encode()

    monkeypatch.setattr("resolver.views.fetch_json", fake_fetch)
    response = get(client, "/ark:/61220/utsc1/manifest")
    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    assert json.loads(response.content) == manifest


def test_manifest_reports_an_upstream_failure_as_bad_gateway(client, ark, monkeypatch):
    Binding.objects.create(ark=ark, name="URL", value="https://example.org/item/1")

    def boom(url, **kwargs):
        raise OSError("connection refused")

    monkeypatch.setattr("resolver.views.fetch_json", boom)
    assert get(client, "/ark:/61220/utsc1/manifest").status_code == 502


def test_manifest_rejects_a_non_json_response(client, ark, monkeypatch):
    Binding.objects.create(ark=ark, name="URL", value="https://example.org/item/1")
    monkeypatch.setattr("resolver.views.fetch_json", lambda url, **kw: b"<html>nope</html>")
    assert get(client, "/ark:/61220/utsc1/manifest").status_code == 502


def test_manifest_for_an_unbound_ark_is_not_found(client, ark):
    assert get(client, "/ark:/61220/utsc1/manifest").status_code == 404


# --- landing page ---------------------------------------------------------


def test_root_shows_a_minimal_landing_page(client):
    org = Organisation.load()
    org.name = "UTSC Digital Scholarship Unit"
    org.save()
    response = client.get("/")
    assert response.status_code == 200
    assert "UTSC Digital Scholarship Unit" in response.content.decode()


# --- percent-encoding -----------------------------------------------------


def test_an_encoded_qualifier_resolves(client, ark):
    # The import stores legacy keys literally, so a qualifier really can contain
    # a space; it is requested as %20.
    Binding.objects.create(ark=ark, qualifier="/page 1", name="URL", value="https://e.example/p1")
    response = get(client, "/ark:/61220/utsc1/page%201")
    assert response.status_code == 302
    assert response["Location"] == "https://e.example/p1"


def test_an_encoded_identifier_resolves(client, collection):
    odd = Ark.objects.create(collection=collection, identifier="café")
    Binding.objects.create(ark=odd, name="URL", value="https://e.example/cafe")
    assert get(client, "/ark:/61220/caf%C3%A9")["Location"] == "https://e.example/cafe"


def test_decoding_is_the_same_with_and_without_a_raw_uri(client, ark):
    # Gunicorn sets RAW_URI (undecoded); other servers do not, and Django's
    # request.path is already decoded. Both must reach the same binding, and
    # neither may decode twice.
    Binding.objects.create(ark=ark, qualifier="/a%20b", name="URL", value="https://e.example/lit")
    with_raw = client.get("/ark:/61220/utsc1/a%2520b", RAW_URI="/ark:/61220/utsc1/a%2520b")
    without_raw = client.get("/ark:/61220/utsc1/a%2520b")
    assert with_raw.status_code == 302
    assert without_raw.status_code == 302
    assert with_raw["Location"] == without_raw["Location"] == "https://e.example/lit"


def test_manifest_refuses_a_local_file_target(client, ark):
    # An Editor can set any URL; the public endpoint must not read the disk.
    Binding.objects.create(ark=ark, name="URL", value="file:///etc/passwd")
    response = get(client, "/ark:/61220/utsc1/manifest")
    assert response.status_code == 502
    assert b"passwd" not in response.content


def test_manifest_refuses_a_link_local_target(client, ark):
    Binding.objects.create(ark=ark, name="URL", value="http://169.254.169.254/latest/meta-data/")
    assert get(client, "/ark:/61220/utsc1/manifest").status_code == 502


# --- matching legacy metadata output --------------------------------------


def test_brief_metadata_on_a_bare_ark_includes_variant_elements(client, ark):
    # Legacy's bare-'?' query matched "<ark>\t[^/]", i.e. any key whose next
    # component is not a hierarchy — which includes a variant-only qualifier
    # such as ".image.png" (resolver.php, the else branch of getMetdata).
    Binding.objects.create(ark=ark, name="WHO", value="Whole object")
    Binding.objects.create(ark=ark, qualifier=".image.png", name="WHO", value="The PNG variant")
    Binding.objects.create(ark=ark, qualifier="/page1", name="WHO", value="Page one")
    body = get(client, "/ark:/61220/utsc1?", raw="/ark:/61220/utsc1?").content.decode()
    assert "Whole object" in body
    assert "The PNG variant" in body
    assert "Page one" not in body, "a hierarchy qualifier is excluded, as in legacy"


def test_labels_drop_every_question_mark(client, ark):
    # Legacy stripped all '?' from the field name before display
    # (resolver.php: trim(str_replace("?", "", $field))), so WHERE? shows as
    # "Where", not "Where?".
    Binding.objects.create(ark=ark, name="WHERE?", value="https://fallback.example")
    body = get(client, "/ark:/61220/utsc1?", raw="/ark:/61220/utsc1?").content.decode()
    assert "Where: https://fallback.example" in body
    assert "Where?:" not in body


def test_an_inflection_beats_a_manifest_request(client, ark, monkeypatch):
    # "?" explicitly asks for metadata instead of the resource; legacy's
    # /manifest test required the URI to *end* in "/manifest", so a trailing '?'
    # took it down the metadata path.
    Binding.objects.create(ark=ark, name="URL", value="https://example.org/1")
    monkeypatch.setattr(
        "resolver.views.fetch_json", lambda *a, **k: pytest.fail("should not fetch")
    )
    response = get(client, "/ark:/61220/utsc1/manifest?", raw="/ark:/61220/utsc1/manifest?")
    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/plain")
    assert response.content.decode().startswith("erc:")


def test_the_naa_for_a_naan_is_chosen_deterministically(client):
    # Two collections can share a NAAN; whichever answers must not depend on
    # database row order, or the same request gives different answers.
    Collection.objects.create(
        name="Zed maps", prefix="zmap", naan="61220", naa="Zed NAA", template=".zd"
    )
    Collection.objects.create(
        name="Alpha books", prefix="abook", naan="61220", naa="Alpha NAA", template=".zd"
    )
    first = get(client, "/ark:/61220/").content.decode()
    second = get(client, "/ark:/61220/").content.decode()
    assert first == second
    assert "Alpha NAA" in first, "the lowest collection name wins, so it is predictable"


def test_full_metadata_omits_the_support_block_when_there_is_none(client, ark):
    # Legacy's getMetdata returned false when no element carried '??', and the
    # caller printed nothing, so the output was just the erc: block. Emitting a
    # bare "erc-support:" header made every ?? and ?info path differ.
    Binding.objects.create(ark=ark, name="WHO", value="Anonymous")
    body = get(client, "/ark:/61220/utsc1??", raw="/ark:/61220/utsc1??").content.decode()
    assert "erc:" in body
    assert "erc-support:" not in body


# --- the resolver hot path ------------------------------------------------


def test_resolving_does_not_write(client, ark):
    # Every redirect used to UPDATE the counter. Resolution must be a read, so
    # it can be served from a replica and cannot lock on a popular ARK.
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    Binding.objects.create(ark=ark, name="URL", value="https://example.org/1")

    with CaptureQueriesContext(connection) as captured:
        assert get(client, "/ark:/61220/utsc1").status_code == 302

    writes = [
        q["sql"]
        for q in captured.captured_queries
        if not q["sql"].lower().lstrip().startswith(("select", "savepoint", "release"))
    ]
    assert not writes, f"resolution wrote to the database: {writes[:1]}"


def test_hits_still_reach_the_counter(client, ark):
    from core.counters import flush_counters

    Binding.objects.create(ark=ark, name="URL", value="https://example.org/1")
    for _ in range(3):
        get(client, "/ark:/61220/utsc1")
    flush_counters()
    assert Resolution.objects.get(ark=ark, qualifier="").count == 3


def test_a_redirect_costs_two_indexed_reads(client, ark):
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    Binding.objects.create(ark=ark, name="URL", value="https://example.org/1")

    with CaptureQueriesContext(connection) as captured:
        response = get(client, "/ark:/61220/utsc1")

    assert response["Location"] == "https://example.org/1"
    selects = [q for q in captured.captured_queries if q["sql"].lower().startswith("select")]
    assert len(selects) <= 2, f"expected the ARK and its bindings, got {len(selects)} queries"


def test_redirects_keep_working_when_the_cache_server_is_down(client, ark, monkeypatch):
    # The resolver must not depend on Redis/Valkey: the hit is written through
    # instead, and the redirect still happens.
    import redis

    import core.counters as counters

    class Down:
        def hincrby(self, *args, **kwargs):
            raise redis.ConnectionError("down")

    monkeypatch.setattr(counters, "_client", lambda: Down())
    Binding.objects.create(ark=ark, name="URL", value="https://example.org/1")

    response = get(client, "/ark:/61220/utsc1")
    assert response.status_code == 302
    assert Resolution.objects.get(ark=ark, qualifier="").count == 1


def test_rebinding_takes_effect_immediately(client, ark):
    from core.services import bind_element

    Binding.objects.create(ark=ark, name="URL", value="https://old.example")
    assert get(client, "/ark:/61220/utsc1")["Location"] == "https://old.example"

    bind_element(ark, "URL", "https://new.example")

    assert get(client, "/ark:/61220/utsc1")["Location"] == "https://new.example", (
        "a stale cached target would send people to the wrong place"
    )


def test_unbinding_stops_resolution_immediately(client, ark):
    from core.services import unbind_elements

    Binding.objects.create(ark=ark, name="URL", value="https://example.org/1")
    get(client, "/ark:/61220/utsc1")

    unbind_elements(ark)

    assert get(client, "/ark:/61220/utsc1").status_code == 404


def test_bulk_rebinding_takes_effect_immediately(client, ark):
    from core.services import bulk_upsert_bindings

    Binding.objects.create(ark=ark, name="URL", value="https://old.example")
    get(client, "/ark:/61220/utsc1")

    bulk_upsert_bindings({(ark.pk, "", "URL"): "https://bulk-new.example"})

    assert get(client, "/ark:/61220/utsc1")["Location"] == "https://bulk-new.example"


def test_the_health_endpoint_reports_ok(client):
    response = client.get("/healthz")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["checks"] == {"database": "ok", "cache": "ok", "counters": "ok"}
    assert "counters_flushed_ago" in body


def test_the_health_endpoint_reports_a_broken_dependency(client, monkeypatch, counter_redis):
    def broken(*args, **kwargs):
        raise RuntimeError("cache is down at secret-host.internal")

    monkeypatch.setattr(counter_redis, "ping", broken)
    response = client.get("/healthz")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert body["checks"]["counters"] == "error"
    assert "secret-host" not in response.content.decode(), "error detail must stay in the log"


def test_the_health_endpoint_reports_the_last_flush(client):
    from core.counters import flush_counters

    flush_counters()
    assert client.get("/healthz").json()["counters_flushed_ago"] is not None
