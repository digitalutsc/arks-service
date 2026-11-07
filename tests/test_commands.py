"""
The operator commands that stay in arks-service: export_arks and resolve_diff here
(import_legacy, check_manifests, flush_counters, refresh_collection_stats and
prune_bulk_jobs have their own test files).

The staff commands (createcollection, mint, bind, unbind, bulk_bind, ark_stats)
are the optional arks-cli plugin now, with their tests (INTENTS_cli_plugin.md).
These tests set up data through the shared services the plugin also uses.
"""

import csv
import io

import pytest
from django.core.management import CommandError, call_command

from core.models import Ark, Collection
from core.services import bind_element
from minting.minter import mint

pytestmark = pytest.mark.django_db


def run(command, *args, **kwargs):
    out = io.StringIO()
    call_command(command, *args, stdout=out, stderr=out, **kwargs)
    return out.getvalue()


@pytest.fixture
def collection():
    return Collection.objects.create(
        name="UTSC", prefix="utsc", naan="61220", naa="UTSC Library", template=".zd"
    )


# --- createcollection -----------------------------------------------------


# --- mint -----------------------------------------------------------------


# --- bind / unbind --------------------------------------------------------


# --- export ---------------------------------------------------------------


def test_export_writes_a_csv(collection, tmp_path):
    mint(collection, 2)
    bind_element(Ark.objects.get(identifier="utsc0"), "URL", "https://example.org/0")
    target = tmp_path / "out.csv"
    run("export_arks", "--collection", "utsc", "--out", str(target))
    rows = list(csv.reader(target.open()))
    assert rows[0] == ["Ark_ID", "URL"]
    assert ["61220/utsc0", "https://example.org/0"] in rows


def test_export_can_filter_by_free_text(collection, tmp_path):
    mint(collection, 2)
    bind_element(Ark.objects.get(identifier="utsc0"), "URL", "https://example.org/apple")
    bind_element(Ark.objects.get(identifier="utsc1"), "URL", "https://example.org/banana")
    target = tmp_path / "out.csv"
    run("export_arks", "--text", "banana", "--out", str(target))
    body = [r[0] for r in list(csv.reader(target.open()))[1:]]
    assert body == ["61220/utsc1"]


# --- bulk_bind ------------------------------------------------------------


# --- stats ----------------------------------------------------------------


def test_export_can_filter_by_minted_date(collection, tmp_path):
    from datetime import timedelta

    from django.utils import timezone

    mint(collection, 2)
    old = Ark.objects.get(identifier="utsc0")
    old.minted_at = timezone.now() - timedelta(days=30)
    old.save()

    target = tmp_path / "out.csv"
    run(
        "export_arks",
        "--minted-after",
        (timezone.now() - timedelta(days=1)).date().isoformat(),
        "--out",
        str(target),
    )
    body = [r[0] for r in list(csv.reader(target.open()))[1:]]
    assert body == ["61220/utsc1"]


# --- the cutover gate -----------------------------------------------------


def test_resolve_diff_passes_when_both_systems_agree(collection, monkeypatch):
    from core.management.commands import resolve_diff as command

    Ark.objects.create(collection=collection, identifier="utsc0", sequence=0)
    monkeypatch.setattr(command, "_fetch", lambda url, timeout: (302, "https://example.org/0"))
    output = run("resolve_diff", "--legacy-base", "https://old", "--new-base", "https://new")
    assert "resolve identically" in output


def test_resolve_diff_fails_on_a_real_difference(collection, monkeypatch):
    from core.management.commands import resolve_diff as command

    Ark.objects.create(collection=collection, identifier="utsc0", sequence=0)

    def fetch(url, timeout):
        return (
            302,
            "https://example.org/old"
            if url.startswith("https://old")
            else "https://example.org/new",
        )

    monkeypatch.setattr(command, "_fetch", fetch)
    with pytest.raises(CommandError, match="Do not flip"):
        run("resolve_diff", "--legacy-base", "https://old", "--new-base", "https://new")


def test_resolve_diff_does_not_fail_on_paths_the_import_reported(collection, monkeypatch, tmp_path):
    from core.management.commands import resolve_diff as command

    Ark.objects.create(collection=collection, identifier="utsc0", sequence=0)
    report = tmp_path / "report.csv"
    report.write_text(
        "reason,table,ark_path,element,value\n"
        "duplicate-element,UTSC,/ark:/61220/utsc0,COLLECTION,Other\n"
    )

    def fetch(url, timeout):
        if url.endswith("/ark:/61220/"):
            return (200, "UTSC Library")
        return (
            302,
            "https://example.org/old"
            if url.startswith("https://old")
            else "https://example.org/new",
        )

    monkeypatch.setattr(command, "_fetch", fetch)
    output = run(
        "resolve_diff",
        "--legacy-base",
        "https://old",
        "--new-base",
        "https://new",
        "--known",
        str(report),
    )
    assert "already reported" in output
