"""
Operations shared by the admin UI and the management commands.

Both surfaces must do the same thing, because staff use whichever is to hand and
a difference between them is a difference in the data. The bulk upsert helper
lives here too: bulk bind and the legacy import had two copies of it that had
already drifted apart over whether to touch updated_at.
"""

import pytest
from django.core.exceptions import ValidationError

from core.models import Ark, Binding, Collection
from core.services import bind_element, bulk_upsert_bindings, collection_stats, unbind_elements

pytestmark = pytest.mark.django_db


@pytest.fixture
def collection():
    return Collection.objects.create(name="UTSC", prefix="utsc", naan="61220", template=".zd")


@pytest.fixture
def ark(collection):
    return Ark.objects.create(collection=collection, identifier="utsc0", sequence=0)


# --- bind / unbind --------------------------------------------------------


def test_bind_creates_an_element(ark):
    binding, created = bind_element(ark, "url", "https://example.org/0")
    assert created is True
    assert binding.name == "URL"
    assert binding.value == "https://example.org/0"


def test_bind_replaces_an_existing_value(ark):
    bind_element(ark, "URL", "https://a.example")
    binding, created = bind_element(ark, "URL", "https://b.example")
    assert created is False
    assert binding.value == "https://b.example"


def test_bind_respects_a_qualifier(ark):
    bind_element(ark, "URL", "https://whole.example")
    bind_element(ark, "URL", "https://p1.example", qualifier="/page1")
    assert ark.bindings.count() == 2


def test_bind_rejects_an_empty_element_name(ark):
    with pytest.raises(ValidationError):
        bind_element(ark, "   ", "https://example.org")


def test_unbind_removes_one_element(ark):
    bind_element(ark, "URL", "https://example.org")
    bind_element(ark, "PID", "islandora:1")
    assert unbind_elements(ark, name="URL") == 1
    assert [b.name for b in ark.bindings.all()] == ["PID"]


def test_unbind_can_remove_everything_under_a_qualifier(ark):
    bind_element(ark, "URL", "https://whole.example")
    bind_element(ark, "URL", "https://p1.example", qualifier="/page1")
    assert unbind_elements(ark, qualifier="/page1") == 1
    assert ark.bindings.get().qualifier == ""


def test_unbind_is_case_insensitive_on_the_name(ark):
    bind_element(ark, "URL", "https://example.org")
    assert unbind_elements(ark, name="url") == 1


# --- shared bulk upsert ---------------------------------------------------


def test_bulk_upsert_creates_and_updates(ark):
    created, updated = bulk_upsert_bindings({(ark.pk, "", "URL"): "https://a.example"})
    assert (created, updated) == (1, 0)
    created, updated = bulk_upsert_bindings({(ark.pk, "", "URL"): "https://b.example"})
    assert (created, updated) == (0, 1)
    assert Binding.objects.get().value == "https://b.example"


def test_bulk_upsert_leaves_unchanged_values_alone(ark):
    bulk_upsert_bindings({(ark.pk, "", "URL"): "https://a.example"})
    created, updated = bulk_upsert_bindings({(ark.pk, "", "URL"): "https://a.example"})
    assert (created, updated) == (0, 0)


def test_bulk_upsert_touches_updated_at(ark):
    # bulk_update skips auto_now, so this has to be set explicitly. The import
    # did and bulk bind did not, so the same rebind produced different rows
    # depending on which route staff used.
    bulk_upsert_bindings({(ark.pk, "", "URL"): "https://a.example"})
    before = Binding.objects.get().updated_at
    bulk_upsert_bindings({(ark.pk, "", "URL"): "https://b.example"})
    assert Binding.objects.get().updated_at > before


def test_bulk_upsert_stores_names_upper_case(ark):
    bulk_upsert_bindings({(ark.pk, "", "url"): "https://a.example"})
    assert Binding.objects.get().name == "URL"


# --- stats ----------------------------------------------------------------


def test_collection_stats_counts_what_the_ui_and_cli_both_show(collection, ark):
    Ark.objects.create(collection=collection, identifier="utsc1", sequence=1)
    bind_element(ark, "URL", "https://example.org/0")
    stats = collection_stats(collection)
    assert stats["total"] == 2
    assert stats["bound"] == 1
    assert stats["unbound"] == 1
    assert stats["elements"] == 1
    assert stats["redirects"] == 0
