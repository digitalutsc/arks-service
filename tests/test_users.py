"""
Who may manage accounts, and the rows nobody may touch.

A superuser is always an Admin whatever the groups say, so a role control on a
superuser's row would do nothing; and nobody edits their own role, so nobody
locks themselves out by accident. Adding and deleting accounts is for
superusers only; a user with the Admin role changes other people's roles and
nothing else. Deleting is a hard delete: every foreign key to a user is
SET_NULL, so ARKs and uploads keep their history and show no owner.
"""

import pytest
from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from django.urls import reverse

from admin_ui.roles import ADMIN, EDITOR, VIEWER, ensure_groups, role_of, set_role
from core.models import Ark, Collection
from jobs.models import BulkBindJob

pytestmark = pytest.mark.django_db


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


@pytest.fixture
def root(client, make_user):
    user = make_user("root", superuser=True)
    client.force_login(user)
    return user


@pytest.fixture
def admin(client, make_user):
    user = make_user("adm", ADMIN)
    client.force_login(user)
    return user


USERS = reverse("admin_ui:user_list")
NEW = reverse("admin_ui:user_create")


def delete_url(user):
    return reverse("admin_ui:user_delete", args=[user.pk])


def rows(response):
    return {row["user"].username: row for row in response.context["people"]}


# --- what the page offers --------------------------------------------------


def test_a_superuser_row_has_no_role_control(client, root, make_user):
    make_user("other", superuser=True)
    table = rows(client.get(USERS))
    assert table["other"]["can_change"] is False
    assert table["root"]["can_change"] is False


def test_your_own_row_has_no_role_control(client, admin, make_user):
    make_user("ed", EDITOR)
    table = rows(client.get(USERS))
    assert table["adm"]["can_change"] is False
    assert table["ed"]["can_change"] is True


def test_the_page_says_a_superuser_is_a_superuser(client, root):
    body = client.get(USERS).content.decode()
    assert "Superuser" in body


def test_an_admin_sees_no_add_or_delete_controls(client, admin, make_user):
    make_user("ed", EDITOR)
    response = client.get(USERS)
    assert response.context["can_manage_accounts"] is False
    assert rows(response)["ed"]["can_delete"] is False
    assert NEW not in response.content.decode()


def test_a_superuser_sees_add_and_delete_controls(client, root, make_user):
    ed = make_user("ed", EDITOR)
    response = client.get(USERS)
    assert response.context["can_manage_accounts"] is True
    assert rows(response)["ed"]["can_delete"] is True
    body = response.content.decode()
    assert NEW in body and delete_url(ed) in body


def test_a_superuser_cannot_delete_another_superuser_or_themselves(client, root, make_user):
    make_user("other", superuser=True)
    table = rows(client.get(USERS))
    assert table["other"]["can_delete"] is False
    assert table["root"]["can_delete"] is False


# --- changing roles -----------------------------------------------------------


def test_an_admin_can_change_another_users_role(client, admin, make_user):
    ed = make_user("ed", EDITOR)
    client.post(USERS, {"user": ed.pk, "role": VIEWER})
    assert role_of(ed) == VIEWER


def test_nobody_can_change_their_own_role(client, admin):
    response = client.post(USERS, {"user": admin.pk, "role": VIEWER}, follow=True)
    assert role_of(admin) == ADMIN
    assert "cannot change your own role" in response.content.decode()


def test_a_superusers_role_cannot_be_changed(client, admin, make_user):
    other = make_user("other", superuser=True)
    response = client.post(USERS, {"user": other.pk, "role": VIEWER}, follow=True)
    assert role_of(other) == ADMIN
    assert other.groups.count() == 0
    assert "superuser" in response.content.decode()


def test_the_last_admin_still_cannot_be_demoted_by_a_superuser(client, root, make_user):
    # root is a superuser, so "adm" is not the last administrator: demotion is allowed.
    adm = make_user("adm", ADMIN)
    client.post(USERS, {"user": adm.pk, "role": EDITOR})
    assert role_of(adm) == EDITOR


# --- adding accounts ------------------------------------------------------------


def good_form(**overrides):
    form = {
        "username": "newbie",
        "email": "n@example.org",
        "first_name": "New",
        "last_name": "Person",
        "password": "a-long-and-sensible-passphrase",
        "password_confirm": "a-long-and-sensible-passphrase",
        "role": VIEWER,
    }
    form.update(overrides)
    return form


def test_a_superuser_can_add_a_user_with_a_role(client, root):
    response = client.post(NEW, good_form(), follow=True)
    user = User.objects.get(username="newbie")
    assert role_of(user) == VIEWER
    assert user.check_password("a-long-and-sensible-passphrase")
    assert user.email == "n@example.org" and user.first_name == "New"
    assert not user.is_superuser and not user.is_staff
    assert "Added newbie" in response.content.decode()


def test_a_new_user_may_have_no_role(client, root):
    client.post(NEW, good_form(role="none"))
    assert role_of(User.objects.get(username="newbie")) is None


def test_an_admin_cannot_add_a_user(client, admin):
    assert client.post(NEW, good_form()).status_code == 403
    assert not User.objects.filter(username="newbie").exists()


def test_an_editor_cannot_add_a_user(client, make_user):
    client.force_login(make_user("ed", EDITOR))
    assert client.post(NEW, good_form()).status_code == 403


def test_adding_needs_a_post(client, root):
    assert client.get(NEW).status_code == 405


def test_a_taken_username_is_refused(client, root, make_user):
    make_user("newbie")
    response = client.post(NEW, good_form())
    assert response.status_code == 200
    assert "taken" in response.context["form_errors"]["username"]
    assert User.objects.filter(username="newbie").count() == 1


def test_a_taken_username_is_refused_whatever_the_case(client, root, make_user):
    make_user("Newbie")
    response = client.post(NEW, good_form(username="newbie"))
    assert "username" in response.context["form_errors"]


def test_mismatched_passwords_are_refused(client, root):
    response = client.post(NEW, good_form(password_confirm="something else"))
    assert "do not match" in response.context["form_errors"]["password"]
    assert not User.objects.filter(username="newbie").exists()


def test_a_weak_password_is_refused_by_the_validators(client, root):
    response = client.post(NEW, good_form(password="password", password_confirm="password"))
    assert "password" in response.context["form_errors"]
    assert not User.objects.filter(username="newbie").exists()


def test_a_blank_username_is_refused(client, root):
    response = client.post(NEW, good_form(username=""))
    assert "username" in response.context["form_errors"]


def test_an_unknown_role_is_refused(client, root):
    response = client.post(NEW, good_form(role="god"))
    assert "role" in response.context["form_errors"]


def test_the_form_keeps_what_was_typed_after_an_error(client, root):
    response = client.post(NEW, good_form(password_confirm="x"))
    assert response.context["form_values"]["username"] == "newbie"
    assert response.context["form_values"]["email"] == "n@example.org"
    assert "a-long-and-sensible-passphrase" not in response.content.decode()


# --- deleting accounts ----------------------------------------------------------


def test_a_superuser_can_delete_a_user(client, root, make_user):
    ed = make_user("ed", EDITOR)
    response = client.post(delete_url(ed), follow=True)
    assert not User.objects.filter(pk=ed.pk).exists()
    assert "Deleted ed" in response.content.decode()


def test_an_admin_cannot_delete_a_user(client, admin, make_user):
    ed = make_user("ed", EDITOR)
    assert client.post(delete_url(ed)).status_code == 403
    assert User.objects.filter(pk=ed.pk).exists()


def test_deleting_needs_a_post(client, root, make_user):
    ed = make_user("ed", EDITOR)
    assert client.get(delete_url(ed)).status_code == 405


def test_a_superuser_cannot_delete_themselves(client, root):
    response = client.post(delete_url(root), follow=True)
    assert User.objects.filter(pk=root.pk).exists()
    assert "own account" in response.content.decode()


def test_a_superuser_cannot_delete_another_superuser(client, root, make_user):
    other = make_user("other", superuser=True)
    response = client.post(delete_url(other), follow=True)
    assert User.objects.filter(pk=other.pk).exists()
    assert "superuser" in response.content.decode()


def test_deleting_an_unknown_user_is_not_found(client, root):
    assert client.post(reverse("admin_ui:user_delete", args=[99999])).status_code == 404


def test_history_survives_a_delete(client, root, make_user):
    ed = make_user("ed", EDITOR)
    collection = Collection.objects.create(name="UTSC", prefix="utsc", naan="61220", template=".zd")
    ark = Ark.objects.create(collection=collection, identifier="utsc0", sequence=0, minted_by=ed)
    job = BulkBindJob(collection=collection, created_by=ed)
    job.upload.save("x.csv", ContentFile(b"Ark_ID\n"), save=False)
    job.save()

    client.post(delete_url(ed))

    ark.refresh_from_db()
    job.refresh_from_db()
    assert ark.minted_by is None and job.created_by is None


# --- the sidebar and the page shell -------------------------------------------


def test_the_role_card_lists_the_superuser(client, root):
    body = client.get(USERS).content.decode()
    assert "add and remove accounts" in body.lower()


def test_delete_asks_for_confirmation_without_inline_handlers(client, root, make_user):
    make_user("ed", EDITOR)
    body = client.get(USERS).content.decode()
    assert "data-confirm=" in body
    assert "onsubmit" not in body and "onclick" not in body
