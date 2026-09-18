"""
The single-ARK page keeps the ARK's own elements apart from its variants'.

An ARK may carry hundreds of qualified forms — the pages of a book, the
derivatives of an image — each with its own set of elements. One flat table of
all of them, told apart only by a repeated qualifier column, buries the ARK's
own record under its parts. The ARK's elements come first; the variants then
have a table of their own, one row each, in the order a person would count them.
"""

import re

import pytest
from django.urls import reverse

from admin_ui.roles import EDITOR, VIEWER, ensure_groups, set_role
from core.models import Ark, Binding, Collection

pytestmark = pytest.mark.django_db


@pytest.fixture
def make_client(django_user_model, client):
    def _make(role):
        ensure_groups()
        user = django_user_model.objects.create_user(f"user-{role}", password="pw")
        set_role(user, role)
        client.force_login(user)
        return client

    return _make


@pytest.fixture
def ark():
    collection = Collection.objects.create(name="UTSC", prefix="utsc", naan="61220", template=".zd")
    return Ark.objects.create(collection=collection, identifier="utsc1", sequence=1)


def bind(ark, qualifier, **elements):
    for name, value in elements.items():
        Binding.objects.create(ark=ark, qualifier=qualifier, name=name, value=value)


def detail(client, ark, **params):
    return client.get(reverse("admin_ui:ark_detail", args=[ark.pk]), params)


def test_the_arks_own_elements_are_listed_apart_from_its_variants(make_client, ark):
    bind(ark, "", URL="https://example.org/book", TITLE="A book")
    bind(ark, "/p1", URL="https://example.org/book/1")

    response = detail(make_client(VIEWER), ark)

    assert [b.name for b in response.context["own_bindings"]] == ["TITLE", "URL"]
    assert [v["qualifier"] for v in response.context["variants"]] == ["/p1"]
    assert [b.name for b in response.context["variants"][0]["bindings"]] == ["URL"]


def test_each_variant_is_a_row_of_the_variants_table(make_client, ark):
    bind(ark, "/p1", URL="https://example.org/1", TITLE="Page one")
    bind(ark, "/p2", URL="https://example.org/2")
    bind(ark, "/p2.thumb.jpg", URL="https://example.org/2.jpg")

    response = detail(make_client(VIEWER), ark)
    body = response.content.decode()

    assert [(v["qualifier"], len(v["bindings"])) for v in response.context["variants"]] == [
        ("/p1", 2),
        ("/p2", 1),
        ("/p2.thumb.jpg", 1),
    ]
    # One table, one row per variant — not a collapsible section for each.
    assert body.count('<tr id="variant-') == 3
    assert '<details class="variant"' not in body
    for heading in ("Variant", "Public URL", "Elements", "Redirects"):
        assert f">{heading}</a></th>" in body


def test_variants_are_in_counting_order_not_alphabetical(make_client, ark):
    for number in (10, 2, 1, 100, 11):
        bind(ark, f"/p{number}", URL=f"https://example.org/{number}")
    response = detail(make_client(VIEWER), ark)
    assert [v["qualifier"] for v in response.context["variants"]] == [
        "/p1",
        "/p2",
        "/p10",
        "/p11",
        "/p100",
    ]


def test_a_variant_shows_its_own_public_url(make_client, ark):
    bind(ark, "/p1", URL="https://example.org/book/1")
    body = detail(make_client(VIEWER), ark).content.decode()
    assert 'href="http://testserver/ark:/61220/utsc1/p1"' in body
    assert 'data-copy="http://testserver/ark:/61220/utsc1/p1"' in body


def test_a_variant_shows_its_redirect_count(make_client, ark):
    from core.models import Resolution

    bind(ark, "/p1", URL="https://example.org/1")
    Resolution.objects.create(ark=ark, qualifier="/p1", count=7)
    response = detail(make_client(VIEWER), ark)
    assert response.context["variants"][0]["redirects"] == 7
    assert '<td class="num">7</td>' in response.content.decode()


def test_a_row_shows_four_elements_and_counts_the_rest(make_client, ark):
    # The browse table's rule: four elements, then "+N more".
    bind(ark, "/p1", A="1", B="2", C="3", D="4", E="5", F="6")
    body = detail(make_client(VIEWER), ark).content.decode()
    row = body[body.index('<tr id="variant-1"') :]
    row = row[: row.index("</tr>")]

    shown, rest = row.split('<details class="more"')
    for name in "ABCD":
        assert f'<span class="el-name">{name}</span>' in shown
    for name in "EF":
        assert f'<span class="el-name">{name}</span>' not in shown
        assert f'<span class="el-name">{name}</span>' in rest
    assert "+2 more" in rest
    # Closed until asked for.
    assert not rest.startswith(" open")


def test_a_row_of_four_or_fewer_has_nothing_more(make_client, ark):
    bind(ark, "/p1", A="1", B="2", C="3", D="4")
    body = detail(make_client(VIEWER), ark).content.decode()
    assert 'class="more"' not in body
    assert " more</" not in body


def test_long_values_are_cut_short_and_kept_whole_on_hover(make_client, ark):
    long_value = "https://example.org/" + "a-very-long-path/" * 8
    bind(ark, "/p1", URL=long_value)
    body = detail(make_client(VIEWER), ark).content.decode()
    assert f'title="{long_value}"' in body
    assert f">{long_value}<" not in body
    assert f">{long_value[:59]}…<" in body


def test_hidden_elements_can_still_be_removed(make_client, ark):
    bind(ark, "/p1", A="1", B="2", C="3", D="4", E="5")
    body = detail(make_client(EDITOR), ark).content.decode()
    rest = body[body.index('<details class="more"') :]
    assert 'name="name" value="E"' in rest[: rest.index("</details>")]


def test_the_elements_sort_still_counts_the_hidden_ones(make_client, ark):
    bind(ark, "/p1", A="1", B="2", C="3", D="4", E="5", F="6")
    bind(ark, "/p2", A="1", B="2", C="3", D="4", E="5")
    assert found(detail(make_client(VIEWER), ark, sort="-elements")) == ["/p1", "/p2"]


def test_an_ark_with_variants_but_nothing_of_its_own_says_so(make_client, ark):
    bind(ark, "/p1", URL="https://example.org/1")
    body = detail(make_client(VIEWER), ark).content.decode()
    assert "Nothing is bound to the ARK itself" in body
    assert "Nothing is bound yet" not in body


def sections(body):
    return re.findall(r"<h2[^>]*>([^<]+)", body)


def test_the_page_opens_with_binding_and_the_danger_zone(make_client, ark):
    from admin_ui.roles import ADMIN

    bind(ark, "", URL="https://example.org/")
    bind(ark, "/p1", URL="https://example.org/1")
    body = detail(make_client(ADMIN), ark).content.decode()
    assert [s.strip() for s in sections(body)] == [
        "Bind an element",
        "Danger zone",
        "Bound elements",
        "Variants",
    ]


def test_an_editor_gets_the_bind_form_first_and_no_danger_zone(make_client, ark):
    bind(ark, "", URL="https://example.org/")
    body = detail(make_client(EDITOR), ark).content.decode()
    assert [s.strip() for s in sections(body)] == ["Bind an element", "Bound elements"]


def test_a_viewer_starts_with_the_bound_elements(make_client, ark):
    bind(ark, "", URL="https://example.org/")
    body = detail(make_client(VIEWER), ark).content.decode()
    assert [s.strip() for s in sections(body)] == ["Bound elements"]


def test_an_ark_with_nothing_bound_has_no_variants_section(make_client, ark):
    body = detail(make_client(VIEWER), ark).content.decode()
    assert "Nothing is bound yet" in body
    assert "<h2>Variants" not in body


# --- searching the variants ------------------------------------------------


@pytest.fixture
def book(ark):
    bind(ark, "", URL="https://example.org/book", TITLE="The whole book")
    bind(ark, "/p1", URL="https://example.org/book/1", TITLE="Frontispiece")
    bind(ark, "/p2", URL="https://example.org/book/2", TITLE="Preface")
    bind(ark, "/p10", URL="https://example.org/book/10", TITLE="Chapter one", PID="islandora:77")
    return ark


def found(response):
    return [v["qualifier"] for v in response.context["variants"]]


def test_search_finds_a_variant_by_its_qualifier(make_client, book):
    response = detail(make_client(VIEWER), book, q="/p10")
    assert found(response) == ["/p10"]
    assert response.context["variant_query"] == "/p10"
    assert response.context["variant_total"] == 3


def test_search_reaches_element_values_and_names(make_client, book):
    client = make_client(VIEWER)
    assert found(detail(client, book, q="preface")) == ["/p2"]
    assert found(detail(client, book, q="ISLANDORA:77")) == ["/p10"]
    assert found(detail(client, book, q="pid")) == ["/p10"]


def test_a_partial_qualifier_matches_every_variant_containing_it(make_client, book):
    assert found(detail(make_client(VIEWER), book, q="/p1")) == ["/p1", "/p10"]


def test_search_leaves_the_arks_own_elements_alone(make_client, book):
    # "whole book" is the ARK's own title, not a variant's.
    response = detail(make_client(VIEWER), book, q="whole book")
    assert found(response) == []
    assert [b.name for b in response.context["own_bindings"]] == ["TITLE", "URL"]
    body = response.content.decode()
    assert "No variants match" in body
    assert "<h2" in body and "Variants" in body


def test_a_found_variant_shows_all_of_its_elements(make_client, book):
    variant = detail(make_client(VIEWER), book, q="islandora").context["variants"][0]
    assert [b.name for b in variant["bindings"]] == ["PID", "TITLE", "URL"]


def test_a_search_that_matched_a_hidden_element_shows_it(make_client, ark):
    bind(ark, "/p1", A="1", B="2", C="3", D="4", NOTE="needle in a haystack")
    bind(ark, "/p2", A="needle", B="2", C="3", D="4", E="5")
    response = detail(make_client(VIEWER), ark, q="NEEDLE")
    assert found(response) == ["/p1", "/p2"]
    # The match in /p1 is past the first four, so its "+1 more" opens; /p2's
    # match is already in view, so its rest stays folded.
    assert [v["more_open"] for v in response.context["variants"]] == [True, False]
    assert '<details class="more" open>' in response.content.decode()


def test_a_variant_keeps_its_anchor_whatever_the_search_shows(make_client, book):
    body = detail(make_client(VIEWER), book, q="chapter").content.decode()
    assert 'id="variant-3"' in body
    assert 'id="variant-1"' not in body


def test_the_search_box_remembers_the_term_and_says_how_many_matched(make_client, book):
    body = detail(make_client(VIEWER), book, q="/p1").content.decode()
    assert 'name="q" value="/p1"' in body
    assert "2 of 3" in body
    assert "Clear search" in body


def test_there_is_no_search_box_without_variants(make_client, ark):
    bind(ark, "", URL="https://example.org/")
    assert 'name="q"' not in detail(make_client(VIEWER), ark).content.decode()


def test_a_variant_search_term_cannot_inject_markup(make_client, book):
    body = detail(make_client(VIEWER), book, q='"><script>alert(1)</script>').content.decode()
    assert "<script>alert(1)</script>" not in body


def test_an_absurdly_long_variant_search_is_cut_short(make_client, book):
    response = detail(make_client(VIEWER), book, q="x" * 5000)
    assert response.status_code == 200
    assert len(response.context["variant_query"]) == 200


# --- sorting the variants --------------------------------------------------


@pytest.fixture
def pages(ark):
    from core.models import Resolution

    # (qualifier, elements, redirects): every column ranks them differently.
    for qualifier, elements, redirects in [("/p1", 2, 0), ("/p2", 1, 9), ("/p10", 3, 4)]:
        for index in range(elements):
            Binding.objects.create(ark=ark, qualifier=qualifier, name=f"FIELD{index}", value="x")
        if redirects:
            Resolution.objects.create(ark=ark, qualifier=qualifier, count=redirects)
    return ark


@pytest.mark.parametrize(
    ("sort", "expected"),
    [
        (None, ["/p1", "/p2", "/p10"]),
        ("variant", ["/p1", "/p2", "/p10"]),
        ("-variant", ["/p10", "/p2", "/p1"]),
        ("-elements", ["/p10", "/p1", "/p2"]),
        ("elements", ["/p2", "/p1", "/p10"]),
        ("-redirects", ["/p2", "/p10", "/p1"]),
        ("redirects", ["/p1", "/p10", "/p2"]),
    ],
)
def test_the_variants_table_sorts_by_each_column_both_ways(make_client, pages, sort, expected):
    params = {"sort": sort} if sort else {}
    assert found(detail(make_client(VIEWER), pages, **params)) == expected


@pytest.mark.parametrize("sort", ["bogus", "-", "--variant", "bindings__value", "²"])
def test_an_unknown_variant_sort_is_counting_order_not_an_error(make_client, pages, sort):
    response = detail(make_client(VIEWER), pages, sort=sort)
    assert response.status_code == 200
    assert found(response) == ["/p1", "/p2", "/p10"]


def test_ties_stay_in_counting_order_whichever_way_the_sort_runs(make_client, ark):
    for number in (3, 1, 2):
        bind(ark, f"/p{number}", URL=f"https://example.org/{number}")
    client = make_client(VIEWER)
    assert found(detail(client, ark, sort="elements")) == ["/p1", "/p2", "/p3"]
    assert found(detail(client, ark, sort="-elements")) == ["/p1", "/p2", "/p3"]


def variant_headers(response):
    return {h["label"]: h for h in response.context["variant_headers"]}


def test_variant_headers_offer_each_columns_natural_first_direction(make_client, pages):
    headers = variant_headers(detail(make_client(VIEWER), pages))
    # Already in counting order, so clicking Variant reverses it.
    assert headers["Variant"]["query"] == "sort=-variant"
    assert headers["Variant"]["aria"] == "ascending"
    assert headers["Elements"]["query"] == "sort=-elements"
    assert headers["Redirects"]["query"] == "sort=-redirects"
    assert headers["Redirects"]["aria"] == ""


def test_clicking_the_active_variant_header_reverses_it(make_client, pages):
    headers = variant_headers(detail(make_client(VIEWER), pages, sort="-redirects"))
    assert headers["Redirects"]["query"] == "sort=redirects"
    assert headers["Redirects"]["aria"] == "descending"
    assert headers["Variant"]["query"] == "sort=variant"


def test_the_public_url_header_sorts_as_the_variant_does(make_client, pages):
    headers = variant_headers(detail(make_client(VIEWER), pages, sort="-variant"))
    assert headers["Public URL"]["query"] == headers["Variant"]["query"] == "sort=variant"
    assert headers["Public URL"]["aria"] == headers["Variant"]["aria"] == "descending"


def test_sorting_keeps_the_search_and_searching_keeps_the_sort(make_client, pages):
    response = detail(make_client(VIEWER), pages, q="/p1", sort="-elements")
    assert found(response) == ["/p10", "/p1"]
    assert variant_headers(response)["Redirects"]["query"] == "q=%2Fp1&sort=-redirects"
    body = response.content.decode()
    assert '<input type="hidden" name="sort" value="-elements">' in body
    # Both come back at the table, not at the top of the page.
    assert 'href="?q=%2Fp1&amp;sort=-redirects#variants"' in body


def test_the_default_order_leaves_the_hidden_sort_field_out(make_client, pages):
    body = detail(make_client(VIEWER), pages, sort="variant").content.decode()
    assert 'name="sort"' not in body


def test_clearing_the_search_keeps_the_sort(make_client, pages):
    body = detail(make_client(VIEWER), pages, q="/p1", sort="-elements").content.decode()
    assert "?sort=-elements#variants" in body


def test_a_row_keeps_its_anchor_whatever_the_sort(make_client, pages):
    body = detail(make_client(VIEWER), pages, sort="-variant").content.decode()
    # /p10 is third in counting order, first on the page.
    assert body.index('id="variant-3"') < body.index('id="variant-1"')


def test_the_active_variant_header_is_marked_up_for_assistive_technology(make_client, pages):
    body = detail(make_client(VIEWER), pages, sort="-redirects").content.decode()
    assert 'class="num" aria-sort="descending"' in body
    assert body.count("aria-sort=") == 1


# --- editing ---------------------------------------------------------------


def test_removing_from_a_variant_comes_back_to_its_row(make_client, ark):
    for number in (1, 2, 3):
        bind(ark, f"/p{number}", URL=f"https://example.org/{number}", TITLE=f"Page {number}")
    client = make_client(EDITOR)

    response = client.post(
        reverse("admin_ui:ark_detail", args=[ark.pk]),
        {"action": "unbind", "name": "TITLE", "qualifier": "/p2"},
    )

    assert response.status_code == 302
    assert response["Location"] == reverse("admin_ui:ark_detail", args=[ark.pk]) + "#variant-2"
    page = client.get(response["Location"])
    assert [b.name for b in page.context["variants"][1]["bindings"]] == ["URL"]
    assert '<tr id="variant-2"' in page.content.decode()


def test_binding_to_a_new_variant_comes_back_to_its_row(make_client, ark):
    bind(ark, "/p1", URL="https://example.org/1")
    client = make_client(EDITOR)

    response = client.post(
        reverse("admin_ui:ark_detail", args=[ark.pk]),
        {"action": "bind", "name": "URL", "value": "https://example.org/2", "qualifier": "/p2"},
    )

    assert response["Location"].endswith("#variant-2")
    assert [v["qualifier"] for v in client.get(response["Location"]).context["variants"]] == [
        "/p1",
        "/p2",
    ]


def test_an_edit_made_under_a_search_and_sort_comes_back_to_the_same_view(make_client, pages):
    client = make_client(EDITOR)
    response = client.post(
        reverse("admin_ui:ark_detail", args=[pages.pk]) + "?q=%2Fp1&sort=-elements&page=bogus",
        {"action": "unbind", "name": "FIELD0", "qualifier": "/p10"},
    )
    base = reverse("admin_ui:ark_detail", args=[pages.pk])
    assert response["Location"] == f"{base}?q=%2Fp1&sort=-elements#variant-3"


def test_editing_the_arks_own_elements_needs_no_detour(make_client, ark):
    client = make_client(EDITOR)
    response = client.post(
        reverse("admin_ui:ark_detail", args=[ark.pk]),
        {"action": "bind", "name": "URL", "value": "https://example.org/", "qualifier": ""},
    )
    assert response["Location"] == reverse("admin_ui:ark_detail", args=[ark.pk])


def test_every_variant_has_its_own_remove_buttons(make_client, ark):
    bind(ark, "/p1", URL="https://example.org/1")
    body = detail(make_client(EDITOR), ark).content.decode()
    assert '<input type="hidden" name="qualifier" value="/p1">' in body


def test_viewers_see_no_remove_buttons(make_client, ark):
    bind(ark, "/p1", URL="https://example.org/1")
    body = detail(make_client(VIEWER), ark).content.decode()
    assert 'value="unbind"' not in body
