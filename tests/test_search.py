"""
Searching ARKs and exporting the result.

Search must reach any element name, not just the conventional ones, and free
text must reach values — the legacy admin could only filter the columns it knew
about. Export produces exactly the shape bulk bind consumes, so a search result
can be edited and uploaded straight back.
"""

import re
from datetime import timedelta

import pytest
from django.utils import timezone

from core.models import Ark, Binding, Collection, Resolution
from core.search import export_rows, parse_sort, search_arks, sort_arks

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


# --- sorting --------------------------------------------------------------


def in_order(queryset):
    return [a.identifier for a in queryset]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("ark", ("ark", False)),
        ("-ark", ("ark", True)),
        ("minted", ("minted", False)),
        ("-redirects", ("redirects", True)),
        ("elements", ("elements", False)),
        # Anything unrecognised is today's order, never an error: the value
        # comes straight from the query string.
        ("", ("ark", False)),
        ("-", ("ark", False)),
        ("--ark", ("ark", False)),
        ("minted_by__password", ("ark", False)),
        ("²", ("ark", False)),
        (None, ("ark", False)),
    ],
)
def test_parse_sort_accepts_only_known_keys(raw, expected):
    assert parse_sort(raw) == expected


def test_the_default_sort_is_by_ark(data):
    assert in_order(sort_arks(search_arks(), "ark", False)) == ["map0", "utsc0", "utsc1", "utsc2"]
    assert in_order(sort_arks(search_arks(), "ark", True)) == ["utsc2", "utsc1", "utsc0", "map0"]


def test_sort_by_minted_date(data):
    now = timezone.now()
    for days_ago, key in enumerate(["a2", "a0", "a3", "a1"]):
        Ark.objects.filter(pk=data[key].pk).update(minted_at=now - timedelta(days=days_ago))
    assert in_order(sort_arks(search_arks(), "minted", True)) == ["utsc2", "utsc0", "map0", "utsc1"]
    assert in_order(sort_arks(search_arks(), "minted", False)) == [
        "utsc1",
        "map0",
        "utsc0",
        "utsc2",
    ]


def test_sort_by_redirects_puts_never_resolved_arks_at_zero(data):
    # Ties (the two that were never resolved) fall back to ARK order.
    assert in_order(sort_arks(search_arks(), "redirects", True)) == [
        "utsc0",
        "utsc1",
        "map0",
        "utsc2",
    ]
    assert in_order(sort_arks(search_arks(), "redirects", False)) == [
        "map0",
        "utsc2",
        "utsc1",
        "utsc0",
    ]


def test_sort_by_redirects_adds_up_every_qualifier(data):
    # The column shows the total across qualifiers, so the sort must too.
    Resolution.objects.create(ark=data["a1"], qualifier="/page1", count=1000)
    assert in_order(sort_arks(search_arks(), "redirects", True))[:2] == ["utsc1", "utsc0"]


def test_sort_by_number_of_elements(data):
    assert in_order(sort_arks(search_arks(), "elements", True)) == [
        "utsc0",
        "utsc1",
        "map0",
        "utsc2",
    ]
    assert in_order(sort_arks(search_arks(), "elements", False)) == [
        "utsc2",
        "map0",
        "utsc0",
        "utsc1",
    ]


def test_sorting_composes_with_filters_and_keeps_rows_distinct(data, collection):
    found = sort_arks(search_arks(collection=collection, bound=True), "redirects", False)
    assert in_order(found) == ["utsc1", "utsc0"]


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


# --- cost must not grow with the result set -------------------------------


def _widest_in_list(sql: str) -> int:
    """
    Largest `IN (...)` list in a statement.

    Counts the values themselves rather than placeholders: SQLite's captured
    SQL is already interpolated, so counting %s would report zero and the test
    would pass on an unbounded query.
    """
    return max(
        (len(match.split(",")) for match in re.findall(r"\bIN \(([^()]*)\)", sql, re.I)),
        default=0,
    )


@pytest.fixture
def many_arks(collection):
    """More ARKs than one export chunk, so chunking is actually exercised."""
    arks = Ark.objects.bulk_create(
        [
            Ark(collection=collection, naan="61220", identifier=f"utsc{n}", sequence=n)
            for n in range(250)
        ]
    )
    pks = list(Ark.objects.filter(collection=collection).values_list("id", flat=True))
    Binding.objects.bulk_create(
        [
            Binding(ark_id=pk, qualifier="", name="URL", value=f"https://e.example/{pk}")
            for pk in pks
        ]
    )
    return arks


def test_export_never_builds_an_unbounded_in_list(many_arks, collection, monkeypatch):
    # export_rows did `list(queryset.values_list("id"))` then passed the whole
    # list to `ark_id__in=...`. At 1M ARKs that was 311 MB and 33s to the first
    # row; past ~4M ids the IN-list exceeds MySQL's max_allowed_packet and the
    # export fails outright.
    import core.search

    monkeypatch.setattr(core.search, "EXPORT_CHUNK", 50)

    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    with CaptureQueriesContext(connection) as captured:
        rows = list(export_rows(search_arks(collection=collection)))

    assert len(rows) > 250  # header + every ARK
    for query in captured.captured_queries:
        widest = _widest_in_list(query["sql"])
        assert widest <= 60, f"unbounded IN-list ({widest} values): {query['sql'][:120]}"


def test_export_streams_rather_than_reading_everything_up_front(many_arks, collection, monkeypatch):
    # A streaming download must start producing rows without first walking the
    # whole result set.
    import core.search

    monkeypatch.setattr(core.search, "EXPORT_CHUNK", 50)

    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    rows = export_rows(search_arks(collection=collection))
    with CaptureQueriesContext(connection) as captured:
        header = next(rows)
        first = next(rows)

    assert header[0] == "Ark_ID"
    assert first[0].startswith("61220/")
    assert len(captured.captured_queries) <= 4, (
        "starting an export should cost a bounded number of queries, "
        f"got {len(captured.captured_queries)}"
    )


# --- the admin list page must not scan the table to render ----------------


def test_result_count_is_capped_rather_than_exact(many_arks, collection, settings):
    from core.search import COUNT_CAP, counted

    settings_cap = 100
    total, capped = counted(search_arks(collection=collection), cap=settings_cap)
    assert capped is True
    assert total == settings_cap
    assert COUNT_CAP >= 1000  # the shipped default is a sane page-footer number


def test_a_small_result_is_counted_exactly(data, collection):
    from core.search import counted

    total, capped = counted(search_arks(collection=collection))
    assert capped is False
    assert total == 3  # utsc0, utsc1, utsc2 — map0 is in the other collection


def test_counting_stops_at_the_cap(many_arks, collection):
    # COUNT(*) over an unfiltered 1B-row table is a full index scan; the page
    # footer never needs that number, only "more than N".
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    from core.search import counted

    with CaptureQueriesContext(connection) as captured:
        counted(search_arks(collection=collection), cap=10)

    sql = " ".join(q["sql"].lower() for q in captured.captured_queries)
    assert "limit" in sql, "the capped count must LIMIT rather than count everything"


def test_element_names_are_scoped_to_a_collection(data, collection, other_collection):
    from core.models import Ark, Binding
    from core.search import element_names

    other = Ark.objects.create(collection=other_collection, identifier="map9", sequence=9)
    Binding.objects.create(ark=other, name="CARTOGRAPHER", value="Mercator")

    assert "CARTOGRAPHER" not in element_names(collection.pk)
    assert "CARTOGRAPHER" in element_names(other_collection.pk)


def test_element_names_are_cached(data, collection):
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    from core.search import element_names

    element_names(collection.pk)
    with CaptureQueriesContext(connection) as captured:
        element_names(collection.pk)
    assert not captured.captured_queries, "a second call should be served from cache"


# --- value lookups must be index-backed -----------------------------------


def test_an_exact_value_lookup_uses_the_index(many_arks, collection):
    # `value` is unbounded TEXT, which MySQL cannot index, so an exact lookup
    # scanned every binding with that name: 3.9s at 1M ARKs. A normalised
    # prefix column carries the index.
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    target = Binding.objects.filter(name="URL").order_by("id").last()

    with CaptureQueriesContext(connection) as captured:
        found = list(search_arks(collection=collection, element="URL", value=target.value))

    assert [a.id for a in found] == [target.ark_id]
    sql = " ".join(q["sql"].lower() for q in captured.captured_queries)
    assert "value_prefix" in sql, "the exact-value path must go through the indexed column"


def test_value_prefix_is_maintained_on_save(collection):
    ark = Ark.objects.create(collection=collection, identifier="vp0", sequence=900)
    binding = Binding.objects.create(ark=ark, name="URL", value="HTTPS://Example.org/Thing")
    binding.refresh_from_db()
    assert binding.value_prefix == "https://example.org/thing"


def test_value_prefix_is_maintained_in_bulk(collection):
    from core.services import bulk_upsert_bindings

    ark = Ark.objects.create(collection=collection, identifier="vp1", sequence=901)
    bulk_upsert_bindings({(ark.pk, "", "URL"): "https://Example.org/Bulk"})
    assert Binding.objects.get(ark=ark).value_prefix == "https://example.org/bulk"

    bulk_upsert_bindings({(ark.pk, "", "URL"): "https://Example.org/Changed"})
    assert Binding.objects.get(ark=ark).value_prefix == "https://example.org/changed"


def test_value_prefix_survives_a_writer_that_bypasses_save(collection):
    # bulk_create skips Model.save(); the database generates this column, so a
    # writer cannot create a row that search is unable to find.
    ark = Ark.objects.create(collection=collection, identifier="vp5", sequence=905)
    Binding.objects.bulk_create(
        [Binding(ark=ark, qualifier="", name="RAW", value="Https://Example.org/Bulky")]
    )
    assert Binding.objects.get(ark=ark, name="RAW").value_prefix == "https://example.org/bulky"
    assert list(
        search_arks(collection=collection, element="RAW", value="https://example.org/bulky")
    ) == [ark]


def test_a_long_value_is_still_found_by_its_exact_text(collection):
    ark = Ark.objects.create(collection=collection, identifier="vp2", sequence=902)
    long_value = "https://example.org/" + ("x" * 400)
    Binding.objects.create(ark=ark, name="NOTE", value=long_value)
    other = Ark.objects.create(collection=collection, identifier="vp3", sequence=903)
    Binding.objects.create(ark=other, name="NOTE", value=long_value[:-1] + "y")

    found = list(search_arks(collection=collection, element="NOTE", value=long_value))
    assert [a.id for a in found] == [ark.id], "values sharing a prefix must not collide"


def test_value_search_is_case_insensitive_on_the_indexed_path(collection):
    ark = Ark.objects.create(collection=collection, identifier="vp4", sequence=904)
    Binding.objects.create(ark=ark, name="PID", value="Islandora:42")
    assert list(search_arks(collection=collection, element="PID", value="islandora:42")) == [ark]
