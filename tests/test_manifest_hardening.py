"""
/manifest made dependable for cutover and usable by IIIF viewers.

- Timeouts close to legacy's 30 s: 1,151 of the imported manifests are built on
  demand and send nothing until they are ready, so a 5 s per-read limit failed
  real ones.
- CORS: a IIIF viewer on another site reads the manifest with fetch(); without
  Access-Control-Allow-Origin the browser blocks it. The source sites send it.
- resolve_diff: legacy answered a failed manifest fetch with 500, this system
  with 502/503/504; both failed, so that is not a difference.
- check_manifests: a read-only report of every proxied-suffix target.

See INTENTS_manifest_hardening.md.
"""

import csv
import io
import json
import urllib.error

import pytest
from django.conf import settings as django_settings
from django.core.management import call_command
from django.db import connection
from django.test.utils import CaptureQueriesContext

from core.models import Ark, Binding, Collection
from core.verify import compare
from resolver.services import TargetTooLarge, TargetTooSlow, UnsafeTarget

pytestmark = pytest.mark.django_db


@pytest.fixture
def collection():
    return Collection.objects.create(
        name="UTSC", prefix="utsc", naan="61220", naa="UTSC Library", template=".zd"
    )


@pytest.fixture
def ark(collection):
    ark = Ark.objects.create(collection=collection, identifier="utsc1", sequence=1)
    Binding.objects.create(ark=ark, name="URL", value="https://example.org/1")
    Binding.objects.create(ark=ark, qualifier="/manifest", name="URL", value="https://x.org/m.json")
    return ark


def get(client, path):
    return client.get(path, RAW_URI=path)


# --- timeouts -------------------------------------------------------------


def test_the_timeouts_default_close_to_legacy():
    assert django_settings.MANIFEST_FETCH_TIMEOUT == 30
    assert django_settings.MANIFEST_TOTAL_TIMEOUT == 30
    assert django_settings.MANIFEST_MAX_CONCURRENT == 4


# --- CORS -----------------------------------------------------------------


def test_a_manifest_can_be_read_by_a_viewer_on_another_site(client, ark, monkeypatch):
    monkeypatch.setattr("resolver.views.fetch_json", lambda url: b'{"type": "Manifest"}')
    response = get(client, "/ark:/61220/utsc1/manifest")
    assert response.status_code == 200
    assert response["Access-Control-Allow-Origin"] == "*"


@pytest.mark.parametrize(
    ("error", "status"),
    [
        (UnsafeTarget("no"), 502),
        (TargetTooLarge("big"), 502),
        (TargetTooSlow("slow"), 504),
        (OSError("down"), 502),
    ],
)
def test_a_failed_manifest_is_readable_too(client, ark, monkeypatch, error, status):
    # A viewer should see the JSON error, not an opaque CORS failure.
    def fail(url):
        raise error

    monkeypatch.setattr("resolver.views.fetch_json", fail)
    response = get(client, "/ark:/61220/utsc1/manifest")
    assert response.status_code == status
    assert response["Access-Control-Allow-Origin"] == "*"


def test_a_non_json_manifest_is_readable_too(client, ark, monkeypatch):
    monkeypatch.setattr("resolver.views.fetch_json", lambda url: b"<html>")
    response = get(client, "/ark:/61220/utsc1/manifest")
    assert response.status_code == 502
    assert response["Access-Control-Allow-Origin"] == "*"


def test_a_busy_manifest_is_readable_too(client, ark, monkeypatch, settings):
    import resolver.views as views

    settings.MANIFEST_MAX_CONCURRENT = 1
    slots = views._manifest_slots_for(1)
    slots.acquire()
    try:
        response = get(client, "/ark:/61220/utsc1/manifest")
    finally:
        slots.release()
    assert response.status_code == 503
    assert response["Access-Control-Allow-Origin"] == "*"


@pytest.mark.parametrize("path", ["/ark:/61220/utsc1", "/ark:/61220/utsc1?", "/admin/login/"])
def test_cors_is_only_on_manifest_responses(client, ark, path):
    assert "Access-Control-Allow-Origin" not in get(client, path)


# --- resolve_diff: both failed is agreement -------------------------------


def test_legacy_500_and_our_502_on_a_manifest_agree():
    assert (
        compare("/ark:/61220/utsc1/manifest", (500, ""), (502, "{}"), proxied_suffixes={"manifest"})
        is None
    )
    assert (
        compare(
            "/ark:/61220/utsc1/p2/manifest", (500, ""), (504, ""), proxied_suffixes={"manifest"}
        )
        is None
    )
    assert (
        compare("/ark:/61220/utsc1/manifest", (500, ""), (503, ""), proxied_suffixes={"manifest"})
        is None
    )


def test_both_failed_only_counts_on_a_proxied_suffix():
    # An ordinary qualifier, a suffix the collection does not proxy, and a
    # metadata request are all still differences.
    assert compare("/ark:/61220/utsc1/page2", (500, ""), (502, ""), proxied_suffixes={"manifest"})
    assert compare("/ark:/61220/utsc1/manifest", (500, ""), (502, ""), proxied_suffixes=set())
    assert compare(
        "/ark:/61220/utsc1/manifest?", (500, ""), (502, ""), proxied_suffixes={"manifest"}
    )


def test_a_manifest_that_only_we_fail_is_still_a_difference():
    assert compare(
        "/ark:/61220/utsc1/manifest", (200, "{}"), (502, ""), proxied_suffixes={"manifest"}
    )
    assert compare(
        "/ark:/61220/utsc1/manifest", (500, ""), (200, "{}"), proxied_suffixes={"manifest"}
    )


def test_resolve_diff_treats_both_failed_manifests_as_agreeing(collection, ark, monkeypatch):
    seen = []

    def fake_fetch(url, timeout):
        seen.append(url)
        if url.endswith("/manifest"):
            return (500, "") if url.startswith("http://legacy") else (502, "")
        return 302, "https://example.org/1"

    monkeypatch.setattr("core.management.commands.resolve_diff._fetch", fake_fetch)
    out = io.StringIO()
    call_command(
        "resolve_diff",
        "--legacy-base",
        "http://legacy",
        "--new-base",
        "http://new",
        "--no-inflections",
        stdout=out,
    )
    assert "http://new/ark:/61220/utsc1/manifest" in seen
    assert "Safe to cut over" in out.getvalue()


# --- check_manifests ------------------------------------------------------


def run_check(*args):
    out = io.StringIO()
    call_command("check_manifests", *args, stdout=out)
    return out.getvalue()


@pytest.fixture
def targets(collection):
    """One ARK per outcome, each binding a /manifest URL that names it."""
    outcomes = ["ok", "empty", "notjson", "slow", "large", "refused", "redirect", "gone"]
    for n, name in enumerate(outcomes):
        ark = Ark.objects.create(
            collection=collection, identifier=f"utsc{100 + n}", sequence=100 + n
        )
        Binding.objects.create(
            ark=ark, qualifier="/manifest", name="URL", value=f"https://x.org/{name}.json"
        )
    # A part's manifest, and one read through WHERE? (the second redirect element).
    part = Ark.objects.get(identifier="utsc100")
    Binding.objects.create(
        ark=part, qualifier="/p2/manifest", name="WHERE?", value="https://x.org/ok.json"
    )
    return outcomes


def fake_fetch(url, *args, **kwargs):
    name = url.rsplit("/", 1)[1].removesuffix(".json")
    if name == "ok":
        return json.dumps({"type": "Manifest", "items": [1]}).encode()
    if name == "empty":
        return b"{}"
    if name == "notjson":
        return b"<html>"
    if name == "slow":
        raise TargetTooSlow("took too long")
    if name == "large":
        raise TargetTooLarge("too big")
    if name == "refused":
        raise UnsafeTarget("private address")
    if name == "redirect":
        raise urllib.error.HTTPError(url, 301, "Moved", {}, None)
    raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)


def test_check_manifests_reports_every_outcome(targets, monkeypatch, tmp_path):
    monkeypatch.setattr("core.management.commands.check_manifests.fetch_json", fake_fetch)
    report = tmp_path / "manifests.csv"

    out = run_check("--collection", "utsc", "--out", str(report), "--workers", "2")

    rows = {(row["ark"], row["qualifier"]): row for row in csv.DictReader(report.open())}
    outcome = {key: row["outcome"] for key, row in rows.items()}
    assert outcome[("61220/utsc100", "/manifest")] == "ok"
    assert outcome[("61220/utsc100", "/p2/manifest")] == "ok"
    assert outcome[("61220/utsc101", "/manifest")] == "empty"
    assert outcome[("61220/utsc102", "/manifest")] == "not-json"
    assert outcome[("61220/utsc103", "/manifest")] == "too-slow"
    assert outcome[("61220/utsc104", "/manifest")] == "too-large"
    assert outcome[("61220/utsc105", "/manifest")] == "refused"
    assert outcome[("61220/utsc106", "/manifest")] == "redirect"
    assert outcome[("61220/utsc107", "/manifest")] == "http-error"
    assert rows[("61220/utsc107", "/manifest")]["status"] == "404"
    assert "9 manifest" in out and "ok 2" in out and "empty 1" in out


def test_check_manifests_uses_the_collections_settings(collection, ark, monkeypatch):
    collection.redirect_elements = "IIIF"
    collection.proxied_suffixes = "iiif"
    collection.save()
    Binding.objects.create(ark=ark, qualifier="/iiif", name="IIIF", value="https://x.org/ok.json")
    seen = []
    monkeypatch.setattr(
        "core.management.commands.check_manifests.fetch_json",
        lambda url, *a, **k: seen.append(url) or b'{"a": 1}',
    )
    run_check("--collection", "utsc")
    # /manifest is no longer proxied, and its URL element is not IIIF.
    assert seen == ["https://x.org/ok.json"]


def test_check_manifests_can_sample(targets, monkeypatch):
    seen = []
    monkeypatch.setattr(
        "core.management.commands.check_manifests.fetch_json",
        lambda url, *a, **k: seen.append(url) or b'{"a": 1}',
    )
    run_check("--collection", "utsc", "--sample", "3")
    assert len(seen) == 3


def test_check_manifests_writes_nothing_to_the_database(targets, monkeypatch):
    monkeypatch.setattr("core.management.commands.check_manifests.fetch_json", fake_fetch)
    with CaptureQueriesContext(connection) as captured:
        run_check("--collection", "utsc")
    writes = [
        q["sql"]
        for q in captured.captured_queries
        if q["sql"].lstrip().split(" ", 1)[0].upper() in {"INSERT", "UPDATE", "DELETE"}
    ]
    assert writes == []
