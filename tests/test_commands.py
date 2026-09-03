"""
The command line.

There is no HTTP API in this system, so these commands are how scripts and
operators do anything the admin UI does. They run on the host with direct
database access.
"""

import csv
import io

import pytest
from django.core.management import CommandError, call_command

from core.models import Ark, Binding, Collection, Resolution

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


def test_createcollection_makes_a_usable_minter():
    run("createcollection", "Maps", "--prefix", "map", "--naan", "61220", "--template", ".zd")
    collection = Collection.objects.get(prefix="map")
    assert collection.spec.mask == "zd"


def test_createcollection_rejects_a_bad_template():
    with pytest.raises(CommandError, match="(?i)template"):
        run("createcollection", "Bad", "--prefix", "b", "--naan", "61220", "--template", "nope")


def test_createcollection_rejects_a_duplicate_prefix(collection):
    with pytest.raises(CommandError, match="(?i)prefix"):
        run("createcollection", "Other", "--prefix", "utsc", "--naan", "61220", "--template", ".zd")


# --- mint -----------------------------------------------------------------


def test_mint_creates_arks_and_prints_them(collection):
    output = run("mint", "utsc", "3")
    assert Ark.objects.count() == 3
    assert "61220/utsc0" in output
    assert "61220/utsc2" in output


def test_mint_can_write_a_fill_in_template(collection, tmp_path):
    target = tmp_path / "template.csv"
    run("mint", "utsc", "2", "--template", str(target))
    rows = list(csv.reader(target.open()))
    assert rows[0][0] == "Ark_ID"
    assert [r[0] for r in rows[1:]] == ["61220/utsc0", "61220/utsc1"]


def test_mint_reports_an_unknown_collection():
    with pytest.raises(CommandError, match="(?i)collection"):
        run("mint", "nosuch", "1")


# --- bind / unbind --------------------------------------------------------


def test_bind_creates_an_element(collection):
    run("mint", "utsc", "1")
    run("bind", "61220/utsc0", "URL", "https://example.org/0")
    assert Binding.objects.get(ark__identifier="utsc0", name="URL").value == "https://example.org/0"


def test_bind_accepts_a_qualifier(collection):
    run("mint", "utsc", "1")
    run("bind", "61220/utsc0/page1", "URL", "https://example.org/p1")
    assert Binding.objects.filter(qualifier="/page1").exists()


def test_bind_replaces_an_existing_value(collection):
    run("mint", "utsc", "1")
    run("bind", "61220/utsc0", "URL", "https://a.example")
    run("bind", "61220/utsc0", "URL", "https://b.example")
    assert Binding.objects.get(ark__identifier="utsc0", name="URL").value == "https://b.example"


def test_bind_reports_an_unknown_ark(collection):
    with pytest.raises(CommandError, match="(?i)ark"):
        run("bind", "61220/nope", "URL", "https://example.org")


def test_unbind_removes_an_element(collection):
    run("mint", "utsc", "1")
    run("bind", "61220/utsc0", "URL", "https://example.org/0")
    run("unbind", "61220/utsc0", "URL")
    assert not Binding.objects.filter(name="URL").exists()


def test_unbind_can_clear_every_element(collection):
    run("mint", "utsc", "1")
    run("bind", "61220/utsc0", "URL", "https://example.org/0")
    run("bind", "61220/utsc0", "PID", "islandora:1")
    run("unbind", "61220/utsc0", "--all")
    assert not Binding.objects.filter(ark__identifier="utsc0").exists()


# --- export ---------------------------------------------------------------


def test_export_writes_a_csv(collection, tmp_path):
    run("mint", "utsc", "2")
    run("bind", "61220/utsc0", "URL", "https://example.org/0")
    target = tmp_path / "out.csv"
    run("export_arks", "--collection", "utsc", "--out", str(target))
    rows = list(csv.reader(target.open()))
    assert rows[0] == ["Ark_ID", "URL"]
    assert ["61220/utsc0", "https://example.org/0"] in rows


def test_export_can_filter_by_free_text(collection, tmp_path):
    run("mint", "utsc", "2")
    run("bind", "61220/utsc0", "URL", "https://example.org/apple")
    run("bind", "61220/utsc1", "URL", "https://example.org/banana")
    target = tmp_path / "out.csv"
    run("export_arks", "--text", "banana", "--out", str(target))
    body = [r[0] for r in list(csv.reader(target.open()))[1:]]
    assert body == ["61220/utsc1"]


# --- bulk_bind ------------------------------------------------------------


def test_bulk_bind_applies_a_file(collection, tmp_path):
    run("mint", "utsc", "2")
    source = tmp_path / "in.csv"
    source.write_text(
        "Ark_ID,URL,PID\n61220/utsc0,https://example.org/0,islandora:0\n"
        "61220/utsc1,https://example.org/1,islandora:1\n"
    )
    output = run("bulk_bind", "utsc", str(source))
    assert Binding.objects.count() == 4
    assert "4" in output


def test_bulk_bind_reports_failures_and_writes_nothing(collection, tmp_path):
    run("mint", "utsc", "1")
    source = tmp_path / "in.csv"
    source.write_text(
        "Ark_ID,URL\n61220/utsc0,https://ok.example\n61220/nope,https://bad.example\n"
    )
    with pytest.raises(CommandError):
        run("bulk_bind", "utsc", str(source))
    assert Binding.objects.count() == 0


def test_bulk_bind_can_mint_blank_rows(collection, tmp_path):
    source = tmp_path / "in.csv"
    source.write_text("Ark_ID,URL\n,https://example.org/new\n")
    run("bulk_bind", "utsc", str(source), "--mint-missing")
    assert Ark.objects.count() == 1
    assert Binding.objects.count() == 1


def test_bulk_bind_writes_a_results_file(collection, tmp_path):
    run("mint", "utsc", "1")
    source = tmp_path / "in.csv"
    source.write_text("Ark_ID,URL\n61220/utsc0,https://example.org/0\n")
    results = tmp_path / "results.csv"
    run("bulk_bind", "utsc", str(source), "--results", str(results))
    rows = list(csv.reader(results.open()))
    assert rows[0] == ["row", "ark_id", "status", "message"]
    assert rows[1][1] == "61220/utsc0"


# --- stats ----------------------------------------------------------------


def test_stats_summarises_each_collection(collection):
    run("mint", "utsc", "3")
    run("bind", "61220/utsc0", "URL", "https://example.org/0")
    Resolution.objects.create(ark=Ark.objects.get(identifier="utsc0"), qualifier="", count=9)
    output = run("ark_stats")
    assert "utsc" in output
    assert "3" in output


def test_export_can_filter_by_minted_date(collection, tmp_path):
    from datetime import timedelta

    from django.utils import timezone

    run("mint", "utsc", "2")
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


def test_unbind_all_on_a_bare_ark_retires_it_completely(collection):
    # "Retire this ARK" must leave nothing resolving, including its parts —
    # and must match what the UI's "Purge all elements" does.
    run("mint", "utsc", "1")
    run("bind", "61220/utsc0", "URL", "https://example.org/0")
    run("bind", "61220/utsc0/page1", "URL", "https://example.org/0/p1")
    run("bind", "61220/utsc0/page1.image.png", "URL", "https://example.org/0/p1.png")

    run("unbind", "61220/utsc0", "--all")

    assert not Binding.objects.filter(ark__identifier="utsc0").exists()
    assert Ark.objects.filter(identifier="utsc0").exists(), "the identifier is never reissued"


def test_unbind_all_under_a_qualifier_only_clears_that_qualifier(collection):
    run("mint", "utsc", "1")
    run("bind", "61220/utsc0", "URL", "https://example.org/0")
    run("bind", "61220/utsc0/page1", "URL", "https://example.org/0/p1")

    run("unbind", "61220/utsc0/page1", "--all")

    assert Binding.objects.filter(ark__identifier="utsc0", qualifier="").exists()
    assert not Binding.objects.filter(ark__identifier="utsc0", qualifier="/page1").exists()


def test_the_cli_and_the_ui_purge_the_same_way(collection):
    from core.services import unbind_elements

    run("mint", "utsc", "2")
    for ident in ("utsc0", "utsc1"):
        run("bind", f"61220/{ident}", "URL", "https://example.org/x")
        run("bind", f"61220/{ident}/page1", "URL", "https://example.org/x/p1")

    run("unbind", "61220/utsc0", "--all")  # the CLI
    unbind_elements(Ark.objects.get(identifier="utsc1"))  # what the UI calls

    assert not Binding.objects.filter(ark__identifier="utsc0").exists()
    assert not Binding.objects.filter(ark__identifier="utsc1").exists()
