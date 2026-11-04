"""
Roles and who may do what.

Admin does everything including collections, purge and user management; Editor
mints and binds; Viewer can only look and export. The legacy service had a
single all-powerful account, so this is new ground and worth pinning down.
"""

import pytest
from django.urls import reverse

from admin_ui.roles import ADMIN, EDITOR, VIEWER, ensure_groups, role_of, set_role
from core.models import Ark, Collection

pytestmark = pytest.mark.django_db


@pytest.fixture
def collection():
    return Collection.objects.create(name="UTSC", prefix="utsc", naan="61220", template=".zd")


@pytest.fixture
def ark(collection):
    return Ark.objects.create(collection=collection, identifier="utsc0", sequence=0)


@pytest.fixture
def make_user(django_user_model):
    def _make(username, role=None, superuser=False):
        ensure_groups()
        user = django_user_model.objects.create_user(
            username, password="pw", is_superuser=superuser, is_staff=superuser
        )
        if role:
            set_role(user, role)
        return user

    return _make


# --- role assignment ------------------------------------------------------


def test_a_user_with_no_group_has_no_role(make_user):
    assert role_of(make_user("nobody")) is None


def test_a_role_can_be_assigned_and_read_back(make_user):
    assert role_of(make_user("ed", EDITOR)) == EDITOR


def test_setting_a_role_replaces_the_previous_one(make_user):
    user = make_user("someone", VIEWER)
    set_role(user, ADMIN)
    assert role_of(user) == ADMIN


def test_a_superuser_is_treated_as_an_admin(make_user):
    assert role_of(make_user("root", superuser=True)) == ADMIN


# --- page access ----------------------------------------------------------

VIEW_PAGES = ["admin_ui:collection_list"]
EDIT_PAGES = ["admin_ui:user_list"]


def test_anonymous_users_are_sent_to_the_login_page(client):
    response = client.get(reverse("admin_ui:collection_list"))
    assert response.status_code == 302
    assert reverse("admin_ui:login") in response["Location"]


def test_a_viewer_can_see_the_collection_list(client, make_user, collection):
    client.force_login(make_user("v", VIEWER))
    assert client.get(reverse("admin_ui:collection_list")).status_code == 200


def test_a_user_with_no_role_is_refused(client, make_user, collection):
    client.force_login(make_user("nobody"))
    assert client.get(reverse("admin_ui:collection_list")).status_code == 403


def test_a_viewer_cannot_open_the_mint_page(client, make_user, collection):
    client.force_login(make_user("v", VIEWER))
    url = reverse("admin_ui:mint", args=[collection.pk])
    assert client.get(url).status_code == 403


def test_an_editor_can_open_the_mint_page(client, make_user, collection):
    client.force_login(make_user("e", EDITOR))
    url = reverse("admin_ui:mint", args=[collection.pk])
    assert client.get(url).status_code == 200


def test_a_viewer_cannot_mint_by_posting(client, make_user, collection):
    client.force_login(make_user("v", VIEWER))
    client.post(reverse("admin_ui:mint", args=[collection.pk]), {"count": "5"})
    assert Ark.objects.count() == 0


def test_an_editor_cannot_create_a_collection(client, make_user):
    client.force_login(make_user("e", EDITOR))
    assert client.get(reverse("admin_ui:collection_create")).status_code == 403


def test_an_admin_can_create_a_collection(client, make_user):
    client.force_login(make_user("a", ADMIN))
    assert client.get(reverse("admin_ui:collection_create")).status_code == 200


def test_an_editor_cannot_manage_users(client, make_user):
    client.force_login(make_user("e", EDITOR))
    assert client.get(reverse("admin_ui:user_list")).status_code == 403


def test_an_admin_can_manage_users(client, make_user):
    client.force_login(make_user("a", ADMIN))
    assert client.get(reverse("admin_ui:user_list")).status_code == 200


def test_an_editor_cannot_purge(client, make_user, ark):
    client.force_login(make_user("e", EDITOR))
    url = reverse("admin_ui:ark_purge", args=[ark.pk])
    assert client.post(url).status_code == 403


def test_an_admin_can_purge(client, make_user, ark):
    from core.models import Binding

    Binding.objects.create(ark=ark, name="URL", value="https://example.org")
    client.force_login(make_user("a", ADMIN))
    client.post(reverse("admin_ui:ark_purge", args=[ark.pk]))
    assert not ark.bindings.exists()


def test_a_viewer_can_export(client, make_user, collection):
    client.force_login(make_user("v", VIEWER))
    response = client.get(reverse("admin_ui:export"), {"collection": collection.pk})
    assert response.status_code == 200
    assert "text/csv" in response["Content-Type"]


def test_an_editor_can_bind(client, make_user, ark):
    client.force_login(make_user("e", EDITOR))
    url = reverse("admin_ui:ark_detail", args=[ark.pk])
    client.post(url, {"action": "bind", "name": "URL", "value": "https://example.org/0"})
    assert ark.bindings.filter(name="URL").exists()


def test_a_viewer_cannot_bind(client, make_user, ark):
    client.force_login(make_user("v", VIEWER))
    url = reverse("admin_ui:ark_detail", args=[ark.pk])
    client.post(url, {"action": "bind", "name": "URL", "value": "https://example.org/0"})
    assert not ark.bindings.exists()


def test_a_role_is_looked_up_once_per_user_object(make_user, django_assert_num_queries):
    # Every staff page asked four times: the view guard and three template values.
    user = make_user("ed", EDITOR)
    with django_assert_num_queries(1):
        for _ in range(4):
            assert role_of(user) == EDITOR


def test_changing_a_role_is_seen_at_once(make_user):
    user = make_user("ed", EDITOR)
    assert role_of(user) == EDITOR
    set_role(user, VIEWER)
    assert role_of(user) == VIEWER
