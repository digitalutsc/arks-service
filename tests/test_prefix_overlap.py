"""
A new prefix may not start, or be the start of, another prefix under its NAAN.

Every minted identifier is ``prefix + generated part``, and the minter only
looks inside its own collection for numbers already used. So if one prefix
starts another (``utsc`` and ``utsc1``), both collections can reach for the
same identifier: the second to get there hits the ``(naan, identifier)`` unique
index and can never mint past it. arks.org calls shoulders "non-overlapping
namespaces"; this keeps them that way (INTENTS_prefix_overlap.md).
"""

import pytest
from django.core.management import CommandError
from django.urls import reverse

from admin_ui.roles import ADMIN, ensure_groups, set_role
from core.models import Collection
from core.services import prefix_overlap
from minting.minter import mint
from tests.test_legacy_import import build_legacy_db, run_import

pytestmark = pytest.mark.django_db


def make(name, prefix, naan="61220"):
    return Collection.objects.create(name=name, prefix=prefix, naan=naan, template=".zd")


# --- the rule -------------------------------------------------------------


@pytest.mark.parametrize(
    "existing, new",
    [
        ("utsc", "utsc1"),  # the new prefix starts with an existing one
        ("utsc", "ut"),  # the new prefix is the start of an existing one
        ("utsc", "utsc"),  # the exact repeat is the shortest overlap
        ("utsc", "UTSC1"),  # MySQL's collation treats UTSC10 and utsc10 as one identifier
        ("", "utsc"),  # a blank legacy prefix is the start of every prefix
        ("utsc", ""),
    ],
)
def test_an_overlapping_prefix_is_found(existing, new):
    clash = make("Existing", existing)
    assert prefix_overlap("61220", new) == clash


@pytest.mark.parametrize("new", ["maps", "utsb", "u1", "tsc"])
def test_a_prefix_that_neither_starts_nor_is_started_by_another_is_free(new):
    make("Existing", "utsc")
    assert prefix_overlap("61220", new) is None


def test_a_prefix_under_another_naan_does_not_overlap():
    make("Elsewhere", "utsc", naan="99999")
    assert prefix_overlap("61220", "utsc1") is None


def test_the_named_collection_is_left_out():
    make("Existing", "utsc")
    assert prefix_overlap("61220", "utsc", exclude_name="Existing") is None


# --- the staff form -------------------------------------------------------


@pytest.fixture
def admin_client(django_user_model, client):
    ensure_groups()
    user = django_user_model.objects.create_user("boss", password="pw")
    set_role(user, ADMIN)
    client.force_login(user)
    return client


FORM = {"name": "Theses", "naan": "61220", "naa": "UTSC Library", "template": ".zd"}


def test_the_form_refuses_a_prefix_that_overlaps_another_and_names_it(admin_client):
    make("Digital collections", "utsc")
    response = admin_client.post(
        reverse("admin_ui:collection_create"), {**FORM, "prefix": "utsc1", "term": "medium"}
    )
    body = response.content.decode()
    assert response.status_code == 200
    assert "Digital collections" in body
    assert "overlaps" in body
    assert 'value="utsc1"' in body  # what was typed is kept
    assert not Collection.objects.filter(name="Theses").exists()


def test_a_prefix_differing_only_in_case_is_called_the_same_prefix(admin_client):
    make("Digital collections", "utsc")
    body = admin_client.post(
        reverse("admin_ui:collection_create"), {**FORM, "prefix": "UTSC", "term": "medium"}
    ).content.decode()
    assert "apart from letter case" in body
    assert "beginning of the other" not in body
    assert not Collection.objects.filter(name="Theses").exists()


def test_the_form_still_accepts_an_unrelated_prefix(admin_client):
    make("Digital collections", "utsc")
    response = admin_client.post(
        reverse("admin_ui:collection_create"), {**FORM, "prefix": "thes", "term": "medium"}
    )
    assert response.status_code == 302
    assert Collection.objects.filter(name="Theses", prefix="thes").exists()


# --- the legacy import ----------------------------------------------------


def test_the_import_refuses_a_legacy_collection_that_overlaps_another(tmp_path):
    make("Existing", "utsc1")  # the legacy table's prefix is utsc
    path = tmp_path / "legacy.sqlite3"
    build_legacy_db(path)
    with pytest.raises(CommandError, match="overlaps"):
        run_import(path)
    assert Collection.objects.count() == 1


def test_re_importing_the_same_collection_is_not_an_overlap(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    build_legacy_db(path)
    run_import(path)
    run_import(path)
    assert Collection.objects.count() == 1


# --- why it matters -------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_the_collection_that_would_have_blocked_minting_is_never_created(admin_client):
    production = make("dsu_ark", "utsc")
    mint(production, 10)  # utsc0 … utsc9; the next one is utsc10
    admin_client.post(
        reverse("admin_ui:collection_create"), {**FORM, "prefix": "utsc1", "term": "medium"}
    )
    assert not Collection.objects.filter(prefix="utsc1").exists()
    assert [ark.identifier for ark in mint(production, 2)] == ["utsc10", "utsc11"]
