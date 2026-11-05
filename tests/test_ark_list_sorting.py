"""
Sorting the browse table.

The table is paged on the server, so the order has to travel in the URL: a
header click, the pager and a change of filter must all carry it, or the order
silently resets under the reader. The value comes from a query string, so junk
must fall back to the default order rather than reach ``order_by()``.
"""

import re
from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from admin_ui import views
from admin_ui.roles import VIEWER, ensure_groups, set_role
from core.models import Ark, Binding, Collection, Resolution

pytestmark = pytest.mark.django_db


@pytest.fixture
def viewer(django_user_model, client):
    ensure_groups()
    user = django_user_model.objects.create_user("reader", password="pw")
    set_role(user, VIEWER)
    client.force_login(user)
    return client


@pytest.fixture
def arks():
    collection = Collection.objects.create(name="UTSC", prefix="utsc", naan="61220", template=".zd")
    now = timezone.now()
    made = []
    # (days old, redirects, elements). Every column ranks the four differently,
    # so a sort that quietly fell back to another key cannot pass by accident.
    rows = [(5, 9, 1), (9, 0, 2), (7, 4, 0), (3, 2, 3)]
    for number, (days_old, redirects, elements) in enumerate(rows):
        ark = Ark.objects.create(
            collection=collection,
            identifier=f"utsc{number}",
            sequence=number,
            minted_at=now - timedelta(days=days_old),
        )
        for index in range(elements):
            Binding.objects.create(ark=ark, name=f"FIELD{index}", value="x")
        if redirects:
            Resolution.objects.create(ark=ark, count=redirects)
        made.append(ark)
    return made


def shown(response):
    return [ark.identifier for ark in response.context["arks"]]


def browse(client, **params):
    # Browsing is per collection; every test here has exactly one.
    params.setdefault("collection", Collection.objects.order_by("pk").first().pk)
    return client.get(reverse("admin_ui:ark_list"), params)


def test_the_table_is_in_ark_order_until_asked_otherwise(viewer, arks):
    assert shown(browse(viewer)) == ["utsc0", "utsc1", "utsc2", "utsc3"]


@pytest.mark.parametrize(
    ("sort", "expected"),
    [
        ("-ark", [3, 2, 1, 0]),
        ("minted", [1, 2, 0, 3]),
        ("-minted", [3, 0, 2, 1]),
        ("-redirects", [0, 2, 3, 1]),
        ("redirects", [1, 3, 2, 0]),
        ("-elements", [3, 1, 0, 2]),
        ("elements", [2, 0, 1, 3]),
    ],
)
def test_each_column_sorts_both_ways(viewer, arks, sort, expected):
    assert shown(browse(viewer, sort=sort)) == [f"utsc{number}" for number in expected]


@pytest.mark.parametrize("sort", ["bogus", "-", "--ark", "minted_by__password", "²", "-id"])
def test_an_unknown_sort_is_the_default_order_not_an_error(viewer, arks, sort):
    response = browse(viewer, sort=sort)
    assert response.status_code == 200
    assert shown(response) == ["utsc0", "utsc1", "utsc2", "utsc3"]


def test_sorted_rows_still_show_their_own_redirect_totals(viewer, arks):
    response = browse(viewer, sort="-redirects")
    assert [ark.redirect_count for ark in response.context["arks"]] == [9, 4, 2, 0]


# --- the headers -----------------------------------------------------------


def headers(response):
    # Every header link also carries the collection the list is scoped to;
    # these tests are about the sort, so that parameter is set aside here.
    found = {}
    for h in response.context["headers"]:
        rest = [p for p in h["query"].split("&") if not p.startswith("collection=")]
        found[h["label"]] = {**h, "query": "&".join(rest)}
    return found


def test_an_unsorted_table_offers_each_columns_natural_first_direction(viewer, arks):
    found = headers(browse(viewer))
    # Already in ARK order, so clicking ARK reverses it.
    assert found["ARK"]["query"] == "sort=-ark"
    assert found["ARK"]["aria"] == "ascending"
    # Numbers and dates lead with the biggest and the newest.
    assert found["Minted"]["query"] == "sort=-minted"
    assert found["Redirects"]["query"] == "sort=-redirects"
    assert found["Elements"]["query"] == "sort=-elements"
    assert found["Minted"]["aria"] == ""


def test_clicking_the_active_header_reverses_it(viewer, arks):
    found = headers(browse(viewer, sort="-minted"))
    assert found["Minted"]["query"] == "sort=minted"
    assert found["Minted"]["aria"] == "descending"
    assert found["ARK"]["query"] == "sort=ark"
    assert found["ARK"]["aria"] == ""


def test_the_public_url_header_sorts_as_the_ark_does(viewer, arks):
    found = headers(browse(viewer, sort="-ark"))
    assert found["Public URL"]["query"] == found["ARK"]["query"] == "sort=ark"
    assert found["Public URL"]["aria"] == found["ARK"]["aria"] == "descending"


def test_a_header_link_keeps_the_filters_and_goes_back_to_page_one(viewer, arks):
    found = headers(browse(viewer, q="utsc", bound="yes", page="3", sort="minted"))
    query = found["Redirects"]["query"]
    assert "q=utsc" in query
    assert "bound=yes" in query
    assert "sort=-redirects" in query
    assert "page" not in query
    assert "sort=minted" not in query


def test_the_active_header_is_marked_up_for_assistive_technology(viewer, arks):
    body = browse(viewer, sort="-redirects").content.decode()
    assert 'class="num" aria-sort="descending"' in body
    assert body.count("aria-sort=") == 1


# --- carrying the order around ---------------------------------------------


def test_the_pager_keeps_the_sort(viewer, arks, monkeypatch):
    monkeypatch.setattr(views, "PAGE_SIZE", 1)
    first = browse(viewer, sort="-redirects")
    assert shown(first) == ["utsc0"]
    next_link = re.search(r'href="\?([^"]*)">Next</a>', first.content.decode()).group(1)
    assert "sort=-redirects" in next_link and "page=2" in next_link
    assert shown(browse(viewer, sort="-redirects", page="2")) == ["utsc2"]


def test_the_filter_form_carries_the_sort(viewer, arks):
    body = browse(viewer, sort="-minted").content.decode()
    assert '<input type="hidden" id="sort-field" name="sort" value="-minted">' in body
    assert body.count('id="sort-field"') == 1


def test_the_default_order_leaves_the_form_field_empty(viewer, arks):
    body = browse(viewer, sort="ark").content.decode()
    assert '<input type="hidden" id="sort-field" name="sort" value="">' in body


def test_an_htmx_swap_updates_the_forms_copy_of_the_sort(viewer, arks):
    # The form is outside #results, so the partial reaches it out of band.
    response = viewer.get(
        reverse("admin_ui:ark_list"),
        {"collection": arks[0].collection_id, "sort": "-minted"},
        HTTP_HX_REQUEST="true",
    )
    body = response.content.decode()
    assert 'id="sort-field" name="sort" value="-minted" hx-swap-oob="true"' in body
    assert "<form" not in body


def test_export_is_not_upset_by_a_sort_parameter(viewer, arks):
    response = viewer.get(
        reverse("admin_ui:export"), {"collection": arks[0].collection_id, "sort": "-redirects"}
    )
    assert response.status_code == 200
