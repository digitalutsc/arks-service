"""
Bulk binding from a CSV.

The workflow staff already use: mint a batch, download a template with the new
ARKs pre-filled, add fields in a spreadsheet, upload. The whole file is
validated before anything is written, so a bad row cannot leave the collection
half-updated — the legacy version posted one row at a time and simply stopped
wherever it failed.
"""

import io

import pytest

from core.models import Ark, Binding, Collection
from jobs.bulkbind import BulkBindError, apply_csv, template_csv

pytestmark = pytest.mark.django_db


@pytest.fixture
def collection():
    return Collection.objects.create(name="UTSC", prefix="utsc", naan="61220", template=".zd")


@pytest.fixture
def arks(collection):
    return [
        Ark.objects.create(collection=collection, identifier=f"utsc{n}", sequence=n)
        for n in range(3)
    ]


def csv_file(text):
    return io.StringIO(text.lstrip("\n"))


# --- the happy path -------------------------------------------------------


def test_binds_every_column_in_the_file(collection, arks):
    result = apply_csv(
        collection,
        csv_file(
            """
Ark_ID,URL,LOCAL_ID,PHOTOGRAPHER
61220/utsc0,https://example.org/0,obj-0,Ansel Adams
61220/utsc1,https://example.org/1,obj-1,Berenice Abbott
"""
        ),
    )
    assert result.created == 6
    assert result.failed == 0
    ark = Ark.objects.get(identifier="utsc0")
    assert ark.bindings.get(name="URL").value == "https://example.org/0"
    assert ark.bindings.get(name="PHOTOGRAPHER").value == "Ansel Adams"


def test_element_names_are_upper_cased(collection, arks):
    apply_csv(collection, csv_file("Ark_ID,url\n61220/utsc0,https://example.org/0\n"))
    assert Binding.objects.filter(name="URL").exists()


def test_rebinding_updates_the_existing_value(collection, arks):
    apply_csv(collection, csv_file("Ark_ID,URL\n61220/utsc0,https://old.example\n"))
    result = apply_csv(collection, csv_file("Ark_ID,URL\n61220/utsc0,https://new.example\n"))
    assert result.updated == 1
    assert result.created == 0
    assert Binding.objects.get(ark__identifier="utsc0", name="URL").value == "https://new.example"


def test_an_empty_cell_leaves_the_existing_value_alone(collection, arks):
    apply_csv(collection, csv_file("Ark_ID,URL\n61220/utsc0,https://keep.example\n"))
    apply_csv(collection, csv_file("Ark_ID,URL,PID\n61220/utsc0,,islandora:1\n"))
    ark = Ark.objects.get(identifier="utsc0")
    assert ark.bindings.get(name="URL").value == "https://keep.example"
    assert ark.bindings.get(name="PID").value == "islandora:1"


def test_an_ark_id_may_carry_a_qualifier(collection, arks):
    apply_csv(
        collection,
        csv_file("Ark_ID,URL\n61220/utsc0/page1,https://example.org/p1\n"),
    )
    binding = Binding.objects.get(ark__identifier="utsc0", qualifier="/page1")
    assert binding.value == "https://example.org/p1"


def test_a_qualifier_may_include_a_variant(collection, arks):
    apply_csv(
        collection,
        csv_file("Ark_ID,URL\n61220/utsc0/page1.image.png,https://example.org/p1.png\n"),
    )
    assert Binding.objects.filter(qualifier="/page1.image.png").exists()


def test_the_ark_id_column_is_not_bound_as_an_element(collection, arks):
    apply_csv(collection, csv_file("Ark_ID,URL\n61220/utsc0,https://example.org/0\n"))
    assert not Binding.objects.filter(name="ARK_ID").exists()


# --- validation happens before anything is written ------------------------


def test_a_missing_ark_id_column_is_rejected(collection):
    with pytest.raises(BulkBindError, match="(?i)ark_id"):
        apply_csv(collection, csv_file("URL,PID\nhttps://example.org,1\n"))


def test_an_empty_file_is_rejected(collection):
    with pytest.raises(BulkBindError):
        apply_csv(collection, csv_file(""))


def test_an_unknown_ark_fails_its_row(collection, arks):
    result = apply_csv(
        collection,
        csv_file("Ark_ID,URL\n61220/utsc0,https://ok.example\n61220/nope,https://bad.example\n"),
    )
    assert result.failed == 1
    assert "nope" in result.errors[0].message or "nope" in result.errors[0].ark_id


def test_nothing_is_written_when_a_row_fails(collection, arks):
    # The guarantee comes from validating the whole file before writing
    # anything, not from rolling back afterwards.
    apply_csv(
        collection,
        csv_file("Ark_ID,URL\n61220/utsc0,https://ok.example\n61220/nope,https://bad.example\n"),
    )
    # The good row must not have been applied either.
    assert not Binding.objects.filter(ark__identifier="utsc0").exists()


def test_an_ark_from_another_collection_fails_its_row(collection, arks):
    other = Collection.objects.create(name="Maps", prefix="map", naan="61220", template=".zd")
    Ark.objects.create(collection=other, identifier="map0", sequence=0)
    result = apply_csv(collection, csv_file("Ark_ID,URL\n61220/map0,https://x.example\n"))
    assert result.failed == 1


def test_a_blank_ark_id_fails_unless_minting_is_requested(collection, arks):
    result = apply_csv(collection, csv_file("Ark_ID,URL\n,https://example.org/new\n"))
    assert result.failed == 1
    assert "mint" in result.errors[0].message.lower()


def test_a_duplicate_ark_and_element_in_one_file_is_rejected(collection, arks):
    result = apply_csv(
        collection,
        csv_file("Ark_ID,URL\n61220/utsc0,https://a.example\n61220/utsc0,https://b.example\n"),
    )
    assert result.failed >= 1


# --- minting on upload ----------------------------------------------------


def test_blank_rows_are_minted_when_asked(collection, arks):
    result = apply_csv(
        collection,
        csv_file("Ark_ID,URL\n,https://example.org/new\n"),
        mint_missing=True,
    )
    assert result.failed == 0
    assert result.minted == 1
    new_ark = Ark.objects.get(identifier="utsc3")
    assert new_ark.bindings.get(name="URL").value == "https://example.org/new"


def test_minted_ark_ids_are_reported_back(collection, arks):
    result = apply_csv(
        collection, csv_file("Ark_ID,URL\n,https://example.org/new\n"), mint_missing=True
    )
    assert result.rows[0].ark_id == "61220/utsc3"


def test_existing_rows_are_untouched_when_minting_others(collection, arks):
    result = apply_csv(
        collection,
        csv_file("Ark_ID,URL\n61220/utsc0,https://existing.example\n,https://minted.example\n"),
        mint_missing=True,
    )
    assert result.minted == 1
    assert result.created == 2


# --- purge ----------------------------------------------------------------


def test_purge_first_clears_previous_bindings(collection, arks):
    apply_csv(collection, csv_file("Ark_ID,URL,PID\n61220/utsc0,https://a.example,islandora:1\n"))
    apply_csv(
        collection,
        csv_file("Ark_ID,URL\n61220/utsc0,https://b.example\n"),
        purge_first=True,
    )
    ark = Ark.objects.get(identifier="utsc0")
    assert sorted(ark.bindings.values_list("name", flat=True)) == ["URL"]
    assert ark.bindings.get(name="URL").value == "https://b.example"


def test_purge_only_touches_arks_named_in_the_file(collection, arks):
    apply_csv(collection, csv_file("Ark_ID,PID\n61220/utsc1,islandora:1\n"))
    apply_csv(collection, csv_file("Ark_ID,URL\n61220/utsc0,https://b.example\n"), purge_first=True)
    assert Binding.objects.filter(ark__identifier="utsc1", name="PID").exists()


# --- limits ---------------------------------------------------------------


def test_a_file_over_the_row_limit_is_rejected(collection, arks, settings):
    settings.BULK_BIND_MAX_ROWS = 2
    body = "Ark_ID,URL\n" + "".join(f"61220/utsc{n},https://e.example/{n}\n" for n in range(3))
    with pytest.raises(BulkBindError, match="(?i)row"):
        apply_csv(collection, csv_file(body))


# --- the template offered after minting -----------------------------------


def test_template_lists_the_minted_arks(collection, arks):
    rows = list(template_csv(arks))
    assert rows[0][0] == "Ark_ID"
    assert [r[0] for r in rows[1:]] == ["61220/utsc0", "61220/utsc1", "61220/utsc2"]


def test_template_has_the_conventional_columns_ready_to_fill(collection, arks):
    header = list(template_csv(arks))[0]
    assert header[1:] == ["URL", "PID", "LOCAL_ID", "COLLECTION"]


def test_template_rows_are_blank_apart_from_the_ark(collection, arks):
    rows = list(template_csv(arks))
    assert set(rows[1][1:]) == {""}


def test_purge_only_clears_the_qualifier_the_row_names(collection, arks):
    # A row naming /page1 must not destroy the base ARK's binding — that would
    # stop the ARK itself resolving.
    apply_csv(collection, csv_file("Ark_ID,URL\n61220/utsc0,https://whole.example\n"))
    apply_csv(collection, csv_file("Ark_ID,URL\n61220/utsc0/page1,https://p1.example\n"))
    apply_csv(
        collection,
        csv_file("Ark_ID,URL\n61220/utsc0/page1,https://p1-new.example\n"),
        purge_first=True,
    )
    ark = Ark.objects.get(identifier="utsc0")
    assert ark.bindings.get(qualifier="", name="URL").value == "https://whole.example"
    assert ark.bindings.get(qualifier="/page1", name="URL").value == "https://p1-new.example"


def test_purge_clears_a_row_whose_cells_are_all_blank(collection, arks):
    # The row names the ARK, so purge must apply even though it binds nothing.
    apply_csv(collection, csv_file("Ark_ID,URL,PID\n61220/utsc0,https://a.example,islandora:1\n"))
    apply_csv(collection, csv_file("Ark_ID,URL,PID\n61220/utsc0,,\n"), purge_first=True)
    assert not Ark.objects.get(identifier="utsc0").bindings.exists()


def test_purge_leaves_other_qualifiers_of_the_same_ark_alone(collection, arks):
    apply_csv(
        collection,
        csv_file(
            "Ark_ID,URL\n"
            "61220/utsc0/page1,https://p1.example\n"
            "61220/utsc0/page2,https://p2.example\n"
        ),
    )
    apply_csv(
        collection,
        csv_file("Ark_ID,URL\n61220/utsc0/page1,https://p1-new.example\n"),
        purge_first=True,
    )
    ark = Ark.objects.get(identifier="utsc0")
    assert ark.bindings.get(qualifier="/page2", name="URL").value == "https://p2.example"


def test_a_row_is_only_reported_minted_once_it_really_was(collection, arks):
    # A blank row was marked "minted" during validation, so a file that failed
    # elsewhere reported rows as minted when nothing had been created.
    result = apply_csv(
        collection,
        csv_file("Ark_ID,URL\n,https://example.org/new\n61220/nope,https://bad.example\n"),
        mint_missing=True,
    )
    assert result.failed >= 1
    assert result.minted == 0
    assert not any(row.status == "minted" for row in result.rows)
    assert Ark.objects.filter(collection=collection).count() == len(arks)
