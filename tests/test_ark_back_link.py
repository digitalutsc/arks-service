"""
The way back from an ARK's page to the list it was opened from.

The only way back used to be the collection's name in the line under the
identifier, which leads to the collection's page rather than to a list of ARKs.
A button above the identifier now returns to the list as it was left: same
search, filters, sort and page. With no list to return to, it offers the ARKs
of this ARK's own collection.
"""

import re

import pytest
from django.urls import reverse

from admin_ui.roles import EDITOR, VIEWER, ensure_groups, set_role
from core.models import Ark, Collection

pytestmark = pytest.mark.django_db


@pytest.fixture
def make_client(django_user_model, client):
    def _make(role=VIEWER):
        ensure_groups()
        user = django_user_model.objects.create_user(f"user-{role}", password="pw")
        set_role(user, role)
        client.force_login(user)
        return client

    return _make


@pytest.fixture
def collection():
    return Collection.objects.create(name="UTSC", prefix="utsc", naan="61220", template=".zd")


@pytest.fixture
def ark(collection):
    return Ark.objects.create(collection=collection, identifier="utsc1", sequence=1)


def back(client, ark):
    response = client.get(reverse("admin_ui:ark_detail", args=[ark.pk]))
    return response.context["back"], response.content.decode()


LIST = reverse("admin_ui:ark_list")


def test_with_no_list_to_return_to_it_offers_the_collections_arks(make_client, ark, collection):
    link, body = back(make_client(), ark)
    assert link == {"url": f"{LIST}?collection={collection.pk}", "label": "Back to ARKs in UTSC"}
    assert f'href="{LIST}?collection={collection.pk}"' in body


def test_it_returns_to_the_list_exactly_as_it_was_left(make_client, ark, collection):
    client = make_client()
    client.get(LIST, {"collection": collection.pk, "q": "utsc", "sort": "-minted", "page": "3"})
    link, body = back(client, ark)
    assert link["label"] == "Back to ARKs"
    assert link["url"] == f"{LIST}?collection={collection.pk}&q=utsc&sort=-minted&page=3"
    assert (
        f'href="{LIST}?collection={collection.pk}&amp;q=utsc&amp;sort=-minted&amp;page=3"' in body
    )


def test_an_unfiltered_list_is_a_list_to_return_to(make_client, ark, collection):
    client = make_client()
    client.get(LIST, {"collection": collection.pk})
    assert back(client, ark)[0] == {
        "url": f"{LIST}?collection={collection.pk}",
        "label": "Back to ARKs",
    }


def test_the_list_as_left_by_an_htmx_swap_counts(make_client, ark, collection):
    # Paging and filtering swap the table in place; the address bar follows,
    # so the way back must too.
    client = make_client()
    client.get(LIST, {"collection": collection.pk, "q": "utsc"})
    client.get(
        LIST, {"collection": collection.pk, "q": "utsc", "page": "2"}, HTTP_HX_REQUEST="true"
    )
    assert back(client, ark)[0]["url"] == f"{LIST}?collection={collection.pk}&q=utsc&page=2"


def test_a_list_of_another_collection_is_not_offered(make_client, ark, collection):
    other = Collection.objects.create(name="Maps", prefix="map", naan="61220", template=".zd")
    client = make_client()
    client.get(LIST, {"collection": other.pk})
    # This ARK was not reached from that list; its own collection's is the honest way back.
    assert back(client, ark)[0]["url"] == f"{LIST}?collection={collection.pk}"


def test_the_way_back_survives_an_edit(make_client, ark, collection):
    client = make_client(EDITOR)
    client.get(LIST, {"collection": collection.pk, "q": "utsc", "sort": "-redirects"})
    response = client.post(
        reverse("admin_ui:ark_detail", args=[ark.pk]),
        {"action": "bind", "name": "URL", "value": "https://example.org/", "qualifier": ""},
        follow=True,
    )
    assert (
        response.context["back"]["url"]
        == f"{LIST}?collection={collection.pk}&q=utsc&sort=-redirects"
    )


def test_the_way_back_is_the_first_thing_on_the_page(make_client, ark):
    _, body = back(make_client(), ark)
    content = body[body.index('class="content-inner"') :]
    first_link = re.search(r'<a class="([^"]+)"', content)
    assert "back-link" in first_link.group(1)
    assert content.index("back-link") < content.index('class="page-header"')


def test_a_crafted_list_address_is_escaped_in_the_link(make_client, ark):
    client = make_client()
    client.get(LIST, {"q": '"><script>alert(1)</script>'})
    _, body = back(client, ark)
    assert "<script>alert(1)</script>" not in body


def test_the_collection_link_under_the_identifier_is_still_there(make_client, ark, collection):
    _, body = back(make_client(), ark)
    assert reverse("admin_ui:collection_detail", args=[collection.pk]) in body
