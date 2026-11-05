"""
Staff pages that would otherwise read a whole large collection per request.

At 4M ARKs (~18M bindings) counting a collection, a contains-search, the
redirect/element sorts and a full export each cost seconds to minutes. These
tests pin the limits that keep that work out of web requests: index-backed
starts-with search, stored statistics, a sort threshold, an export threshold,
and an export that pages by key instead of buffering every id.
"""

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from admin_ui.roles import VIEWER, ensure_groups, set_role
from core import search, services
from core.models import Ark, Binding, Collection
from core.search import TEXT_CONTAINS, TEXT_STARTS, TooManyMatches, export_rows, search_arks

pytestmark = pytest.mark.django_db


@pytest.fixture
def viewer(django_user_model, client):
    ensure_groups()
    user = django_user_model.objects.create_user("reader", password="pw")
    set_role(user, VIEWER)
    client.force_login(user)
    return client


@pytest.fixture
def collection():
    return Collection.objects.create(name="UTSC", prefix="utsc", naan="61220", template=".zd")


def make_arks(collection, count, start=0):
    Ark.objects.bulk_create(
        [
            Ark(collection=collection, naan="61220", identifier=f"utsc{n}", sequence=n)
            for n in range(start, start + count)
        ]
    )
    return list(Ark.objects.filter(collection=collection).order_by("sequence"))


# --- starts-with search ---------------------------------------------------


def test_starts_with_matches_identifiers_and_values_by_their_start(collection):
    first, second, third = make_arks(collection, 3)
    Binding.objects.create(ark=second, name="PID", value="Islandora:42")
    Binding.objects.create(ark=third, name="NOTE", value="see islandora:42")

    by_identifier = search_arks(collection=collection, text="utsc0", text_mode=TEXT_STARTS)
    assert list(by_identifier) == [first]

    by_value = search_arks(collection=collection, text="islandora:4", text_mode=TEXT_STARTS)
    assert list(by_value) == [second], "case-insensitive, and only at the start"

    anywhere = search_arks(collection=collection, text="islandora:4", text_mode=TEXT_CONTAINS)
    assert set(anywhere) == {second, third}


def test_too_many_starts_with_matches_are_refused_not_truncated(collection, monkeypatch):
    make_arks(collection, 5)
    monkeypatch.setattr(search, "STARTS_WITH_CAP", 3)
    with pytest.raises(TooManyMatches):
        search_arks(collection=collection, text="utsc", text_mode=TEXT_STARTS)


def test_the_browse_page_defaults_to_starts_with(viewer, collection):
    first, second = make_arks(collection, 2)
    Binding.objects.create(ark=second, name="NOTE", value="mentions utsc0 in passing")

    starts = viewer.get(reverse("admin_ui:ark_list"), {"collection": collection.pk, "q": "utsc0"})
    assert [a.pk for a in starts.context["arks"]] == [first.pk]

    contains = viewer.get(
        reverse("admin_ui:ark_list"),
        {"collection": collection.pk, "q": "utsc0", "match": "contains"},
    )
    assert {a.pk for a in contains.context["arks"]} == {first.pk, second.pk}


def test_too_many_matches_on_the_browse_page_says_how_to_narrow(viewer, collection, monkeypatch):
    make_arks(collection, 5)
    monkeypatch.setattr(search, "STARTS_WITH_CAP", 3)
    response = viewer.get(reverse("admin_ui:ark_list"), {"collection": collection.pk, "q": "utsc"})
    assert response.status_code == 200
    assert response.context["arks"] == []
    assert b"Add more characters" in response.content


# --- counting -------------------------------------------------------------


def test_a_result_that_fits_one_page_is_not_counted_separately(viewer, collection):
    make_arks(collection, 3)
    # The table alone, as htmx fetches it: the full page also renders the
    # collection header, whose own size figure is a separate matter.
    with CaptureQueriesContext(connection) as captured:
        response = viewer.get(
            reverse("admin_ui:ark_list"), {"collection": collection.pk}, HTTP_HX_REQUEST="true"
        )
    assert response.context["total"] == 3
    counts = [q["sql"] for q in captured.captured_queries if "COUNT(" in q["sql"].upper()]
    assert not counts, f"the page already held every row: {counts[:1]}"


# --- sorting --------------------------------------------------------------


def test_the_redirect_sort_is_refused_above_the_threshold(viewer, collection, settings):
    make_arks(collection, 5)
    settings.SORT_SUBQUERY_MAX_ROWS = 3
    response = viewer.get(
        reverse("admin_ui:ark_list"), {"collection": collection.pk, "sort": "-redirects"}
    )
    assert response.context["sort_refused"] is True
    assert b"Narrow the search to sort it" in response.content


def test_the_redirect_sort_still_works_on_small_results(viewer, collection, settings):
    make_arks(collection, 3)
    settings.SORT_SUBQUERY_MAX_ROWS = 3
    response = viewer.get(
        reverse("admin_ui:ark_list"), {"collection": collection.pk, "sort": "-redirects"}
    )
    assert response.context["sort_refused"] is False


# --- exporting ------------------------------------------------------------


def test_a_large_export_points_to_the_command_line(viewer, collection, settings):
    make_arks(collection, 5)
    settings.EXPORT_SYNC_MAX_ROWS = 3
    response = viewer.get(reverse("admin_ui:export"), {"collection": collection.pk})
    assert response.status_code == 302
    page = viewer.get(response["Location"])
    assert b"export_arks --collection utsc" in page.content


def test_a_small_export_still_streams(viewer, collection, settings):
    make_arks(collection, 3)
    settings.EXPORT_SYNC_MAX_ROWS = 3
    response = viewer.get(reverse("admin_ui:export"), {"collection": collection.pk})
    assert response.status_code == 200
    assert response["Content-Type"] == "text/csv"


def test_the_export_pages_by_key_and_keeps_order(collection, monkeypatch):
    # Batches of 4 over 10 ARKs: every ARK exactly once, in identifier order,
    # across batch boundaries.
    make_arks(collection, 10)
    monkeypatch.setattr(search, "EXPORT_CHUNK", 4)
    rows = list(export_rows(search_arks(collection=collection), collection))[1:]
    exported = [row[0] for row in rows]
    expected = sorted(f"61220/utsc{n}" for n in range(10))
    assert exported == expected


# --- collection statistics ------------------------------------------------


def test_small_collections_are_counted_live(collection):
    make_arks(collection, 2)
    stats, as_of = services.current_stats(collection)
    assert stats["total"] == 2
    assert as_of is None


def test_large_collections_show_the_stored_counts(collection, monkeypatch):
    monkeypatch.setattr(services, "LIVE_STATS_MAX_ARKS", 2)
    make_arks(collection, 3)
    services.refresh_collection_stats(collection)
    make_arks(collection, 1, start=3)  # not yet counted

    stats, as_of = services.current_stats(collection)
    assert stats["total"] == 3, "the stored figure, not a fresh count"
    assert as_of is not None


def test_the_scheduled_refresh_recounts_every_collection(collection, monkeypatch):
    from jobs.tasks import refresh_collection_stats

    monkeypatch.setattr(services, "LIVE_STATS_MAX_ARKS", 2)
    make_arks(collection, 3)
    services.refresh_collection_stats(collection)
    make_arks(collection, 2, start=3)

    assert refresh_collection_stats() == 1
    collection.refresh_from_db()
    assert collection.ark_count == 5


def test_the_collection_page_says_when_counts_were_taken(viewer, collection, monkeypatch):
    monkeypatch.setattr(services, "LIVE_STATS_MAX_ARKS", 2)
    make_arks(collection, 3)
    services.refresh_collection_stats(collection)
    response = viewer.get(reverse("admin_ui:collection_detail", args=[collection.pk]))
    assert b"Counts as of" in response.content


def test_the_refresh_command(collection, capsys):
    from django.core.management import call_command

    make_arks(collection, 2)
    call_command("refresh_collection_stats", "utsc")
    assert "2 ARKs" in capsys.readouterr().out
    collection.refresh_from_db()
    assert collection.stats_refreshed_at is not None
