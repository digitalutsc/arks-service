"""
Searching ARKs and exporting the result.

Search must reach any element name, not just the conventional ones, and free
text must reach values — the legacy admin could only filter the columns it knew
about. Export produces exactly the shape bulk bind consumes, so a search result
can be edited and uploaded straight back.
"""

import pytest
from django.utils import timezone

from core.models import Ark, Binding, Collection, Resolution
from core.search import export_rows, search_arks

pytestmark = pytest.mark.django_db


@pytest.fixture
def collection():
    return Collection.objects.create(name="UTSC", prefix="utsc", naan="61220", template=".zd")


@pytest.fixture
def other_collection():
    return Collection.objects.create(name="Maps", prefix="map", naan="61220", template=".zd")


@pytest.fixture
def data(collection, other_collection):
    a0 = Ark.objects.create(collection=collection, identifier="utsc0", sequence=0)
    Binding.objects.create(ark=a0, name="URL", value="https://example.org/apple")
    Binding.objects.create(ark=a0, name="LOCAL_ID", value="obj-100")
    Binding.objects.create(ark=a0, name="PHOTOGRAPHER", value="Ansel Adams")

    a1 = Ark.objects.create(collection=collection, identifier="utsc1", sequence=1)
    Binding.objects.create(ark=a1, name="URL", value="https://example.org/banana")
    Binding.objects.create(ark=a1, name="LOCAL_ID", value="obj-200")
    Binding.objects.create(ark=a1, qualifier="/page1", name="URL", value="https://example.org/b/p1")

    a2 = Ark.objects.create(collection=collection, identifier="utsc2", sequence=2)  # unbound

    a3 = Ark.objects.create(collection=other_collection, identifier="map0", sequence=0)
    Binding.objects.create(ark=a3, name="URL", value="https://example.org/cherry")

    Resolution.objects.create(ark=a0, qualifier="", count=500, last_at=timezone.now())
    Resolution.objects.create(ark=a1, qualifier="", count=3, last_at=timezone.now())
    return {"a0": a0, "a1": a1, "a2": a2, "a3": a3}


def names(queryset):
    return sorted(a.identifier for a in queryset)


# --- filtering ------------------------------------------------------------


def test_no_filters_returns_everything(data):
    assert len(names(search_arks())) == 4


def test_filter_by_collection(data, collection):
    assert names(search_arks(collection=collection)) == ["utsc0", "utsc1", "utsc2"]


def test_free_text_matches_an_identifier(data):
    assert names(search_arks(text="utsc1")) == ["utsc1"]


def test_free_text_matches_a_binding_value(data):
    assert names(search_arks(text="banana")) == ["utsc1"]


def test_free_text_is_case_insensitive(data):
    assert names(search_arks(text="ANSEL")) == ["utsc0"]


def test_free_text_matches_a_substring(data):
    assert names(search_arks(text="obj-2")) == ["utsc1"]


def test_free_text_reaches_an_arbitrary_element(data):
    # PHOTOGRAPHER is not a conventional element; it must still be searchable.
    assert names(search_arks(text="Adams")) == ["utsc0"]


def test_filter_by_element_name(data):
    assert names(search_arks(element="PHOTOGRAPHER")) == ["utsc0"]


def test_filter_by_element_name_and_value(data):
    assert names(search_arks(element="LOCAL_ID", value="obj-200")) == ["utsc1"]


def test_element_filter_is_case_insensitive_on_the_name(data):
    assert names(search_arks(element="local_id", value="obj-100")) == ["utsc0"]


def test_filter_unbound_arks(data):
    assert names(search_arks(bound=False)) == ["utsc2"]


def test_filter_bound_arks(data, collection):
    assert names(search_arks(collection=collection, bound=True)) == ["utsc0", "utsc1"]


def test_filter_by_minimum_redirects(data):
    assert names(search_arks(min_redirects=100)) == ["utsc0"]


def test_filters_combine(data, collection):
    assert names(search_arks(collection=collection, text="obj-", bound=True)) == [
        "utsc0",
        "utsc1",
    ]


def test_results_are_distinct_even_when_several_bindings_match(data):
    # "example.org" matches every binding on utsc1, including the qualified one.
    assert (
        names(search_arks(text="example.org", collection=data["a1"].collection)).count("utsc1") == 1
    )


def test_search_returns_no_rows_when_nothing_matches(data):
    assert names(search_arks(text="nothing-here")) == []


# --- export ---------------------------------------------------------------


def test_export_header_starts_with_the_ark_id_column(data, collection):
    rows = list(export_rows(search_arks(collection=collection)))
    assert rows[0][0] == "Ark_ID"


def test_export_header_covers_every_element_present(data, collection):
    header = list(export_rows(search_arks(collection=collection)))[0]
    assert set(header[1:]) == {"LOCAL_ID", "PHOTOGRAPHER", "URL"}


def test_export_has_one_row_per_ark_and_qualifier(data, collection):
    rows = list(export_rows(search_arks(collection=collection)))
    ark_ids = [row[0] for row in rows[1:]]
    assert ark_ids == ["61220/utsc0", "61220/utsc1", "61220/utsc1/page1", "61220/utsc2"]


def test_export_puts_values_under_the_right_columns(data, collection):
    rows = list(export_rows(search_arks(collection=collection)))
    header, body = rows[0], rows[1:]
    row = next(r for r in body if r[0] == "61220/utsc0")
    assert row[header.index("URL")] == "https://example.org/apple"
    assert row[header.index("PHOTOGRAPHER")] == "Ansel Adams"


def test_export_leaves_missing_values_empty(data, collection):
    rows = list(export_rows(search_arks(collection=collection)))
    header, body = rows[0], rows[1:]
    row = next(r for r in body if r[0] == "61220/utsc1")
    assert row[header.index("PHOTOGRAPHER")] == ""


def test_export_includes_unbound_arks_so_they_can_be_filled_in(data, collection):
    rows = list(export_rows(search_arks(collection=collection)))
    assert "61220/utsc2" in [row[0] for row in rows[1:]]


def test_export_of_nothing_still_has_a_header(collection):
    rows = list(export_rows(search_arks(collection=collection)))
    assert rows == [["Ark_ID"]]


def test_export_ark_ids_round_trip_into_a_qualifier(data, collection):
    from core.arkpath import parse_ark_path

    rows = list(export_rows(search_arks(collection=collection)))
    parsed = parse_ark_path("ark:/" + next(r[0] for r in rows[1:] if r[0].endswith("/page1")))
    assert parsed.name == "61220/utsc1"
    assert parsed.qualifier == "/page1"
