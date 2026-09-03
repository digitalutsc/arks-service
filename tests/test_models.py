"""Behaviour of the core data model."""

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from core.models import Ark, Binding, Collection, Organisation, Resolution

pytestmark = pytest.mark.django_db


@pytest.fixture
def collection():
    return Collection.objects.create(
        name="UTSC Digital Collections",
        prefix="utsc",
        naan="61220",
        naa="University of Toronto Scarborough",
        template=".zd",
    )


# --- Collection -----------------------------------------------------------


def test_firstpart_joins_naan_and_prefix(collection):
    assert collection.firstpart == "61220/utsc"


def test_firstpart_omits_prefix_when_there_is_none():
    c = Collection(name="Bare", prefix="", naan="61220", template=".zd")
    assert c.firstpart == "61220/"


def test_collection_exposes_its_parsed_template(collection):
    assert collection.spec.mask == "zd"
    assert collection.spec.unlimited is True
    assert collection.is_random is False


def test_collection_rejects_an_unparseable_template():
    c = Collection(name="Bad", prefix="x", naan="61220", template="nodot")
    with pytest.raises(ValidationError) as exc:
        c.full_clean()
    assert "template" in exc.value.message_dict


def test_collection_rejects_a_prefix_that_contradicts_the_template():
    # ".rdedk" ends in a check character drawn from "e", which excludes vowels.
    c = Collection(name="Bad", prefix="a", naan="61220", template=".rdedk")
    with pytest.raises(ValidationError) as exc:
        c.full_clean()
    assert "template" in exc.value.message_dict or "prefix" in exc.value.message_dict


def test_prefix_is_unique(collection):
    with pytest.raises(IntegrityError), transaction.atomic():
        Collection.objects.create(name="Another", prefix="utsc", naan="61220", template=".zd")


# --- Ark ------------------------------------------------------------------


def test_ark_renders_as_naan_slash_identifier(collection):
    ark = Ark.objects.create(collection=collection, naan="61220", identifier="utsc1")
    assert ark.name == "61220/utsc1"
    assert str(ark) == "61220/utsc1"


def test_same_identifier_cannot_be_minted_twice_under_one_naan(collection):
    Ark.objects.create(collection=collection, naan="61220", identifier="utsc1")
    with pytest.raises(IntegrityError), transaction.atomic():
        Ark.objects.create(collection=collection, naan="61220", identifier="utsc1")


def test_naan_defaults_to_the_collection_naan(collection):
    ark = Ark.objects.create(collection=collection, identifier="utsc9")
    assert ark.naan == "61220"


# --- Binding --------------------------------------------------------------


def test_element_names_are_stored_upper_case(collection):
    ark = Ark.objects.create(collection=collection, identifier="utsc1")
    b = Binding.objects.create(ark=ark, name="url", value="https://example.org/1")
    b.refresh_from_db()
    assert b.name == "URL"


def test_one_element_per_name_per_qualifier(collection):
    ark = Ark.objects.create(collection=collection, identifier="utsc1")
    Binding.objects.create(ark=ark, name="URL", value="https://a.example")
    with pytest.raises(IntegrityError), transaction.atomic():
        Binding.objects.create(ark=ark, name="URL", value="https://b.example")


def test_the_same_element_may_exist_under_different_qualifiers(collection):
    ark = Ark.objects.create(collection=collection, identifier="utsc1")
    Binding.objects.create(ark=ark, qualifier="", name="URL", value="https://whole.example")
    Binding.objects.create(ark=ark, qualifier="/page1", name="URL", value="https://page1.example")
    assert ark.bindings.count() == 2


def test_bindings_accept_arbitrary_element_names(collection):
    # The legacy system let any CSV column bind; nothing is special-cased.
    ark = Ark.objects.create(collection=collection, identifier="utsc1")
    Binding.objects.create(ark=ark, name="PHOTOGRAPHER", value="Anonymous")
    Binding.objects.create(ark=ark, name="RIGHTS_STATEMENT", value="CC-BY")
    assert set(ark.bindings.values_list("name", flat=True)) == {
        "PHOTOGRAPHER",
        "RIGHTS_STATEMENT",
    }


def test_binding_value_is_not_length_limited(collection):
    ark = Ark.objects.create(collection=collection, identifier="utsc1")
    long_value = "x" * 20000
    Binding.objects.create(ark=ark, name="NOTE", value=long_value)
    assert ark.bindings.get(name="NOTE").value == long_value


# --- Resolution -----------------------------------------------------------


def test_recording_a_resolution_creates_then_increments_a_counter(collection):
    ark = Ark.objects.create(collection=collection, identifier="utsc1")
    Resolution.record(ark, "")
    Resolution.record(ark, "")
    Resolution.record(ark, "/page1")
    assert Resolution.objects.get(ark=ark, qualifier="").count == 2
    assert Resolution.objects.get(ark=ark, qualifier="/page1").count == 1


def test_resolution_records_when_it_last_happened(collection):
    ark = Ark.objects.create(collection=collection, identifier="utsc1")
    Resolution.record(ark, "")
    first = Resolution.objects.get(ark=ark, qualifier="").last_at
    Resolution.record(ark, "")
    assert Resolution.objects.get(ark=ark, qualifier="").last_at >= first


# --- Organisation ---------------------------------------------------------


def test_organisation_is_a_singleton():
    a = Organisation.load()
    b = Organisation.load()
    assert a.pk == b.pk
    assert Organisation.objects.count() == 1


def test_organisation_survives_edits():
    org = Organisation.load()
    org.name = "UTSC Digital Scholarship Unit"
    org.save()
    assert Organisation.load().name == "UTSC Digital Scholarship Unit"


# --- concurrency ----------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_two_first_time_resolutions_of_the_same_ark_do_not_collide():
    # Both callers find no counter row and both try to create one; the loser
    # must fall back to incrementing, not raise IntegrityError out of the
    # resolver. A crawler hitting a freshly imported ARK does exactly this.
    import threading

    from django.db import connection, connections

    if connection.vendor == "sqlite":
        pytest.skip("SQLite serialises writes globally; nothing to prove here")

    collection = Collection.objects.create(name="race", prefix="race", naan="61220", template=".zd")
    ark = Ark.objects.create(collection=collection, identifier="race0", sequence=0)

    workers = 8
    start = threading.Barrier(workers)
    errors = []

    def worker():
        try:
            start.wait()
            Resolution.record(ark, "")
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)
        finally:
            connections.close_all()

    threads = [threading.Thread(target=worker) for _ in range(workers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, errors
    assert Resolution.objects.get(ark=ark, qualifier="").count == workers


# --- more than one NAAN ---------------------------------------------------


def test_two_naans_may_use_the_same_prefix():
    # prefix was unique across the whole service, so a second NAAN could never
    # reuse "utsc" — a real blocker, and one that costs a table rebuild to fix
    # once the table is large.
    Collection.objects.create(name="UTSC books", prefix="utsc", naan="61220", template=".zd")
    Collection.objects.create(name="Other books", prefix="utsc", naan="12345", template=".zd")
    assert Collection.objects.filter(prefix="utsc").count() == 2


def test_one_naan_may_not_reuse_a_prefix():
    Collection.objects.create(name="UTSC books", prefix="utsc", naan="61220", template=".zd")
    with pytest.raises(IntegrityError), transaction.atomic():
        Collection.objects.create(name="UTSC maps", prefix="utsc", naan="61220", template=".zd")


def test_arks_from_two_naans_sharing_a_prefix_resolve_apart(client):
    from core.models import Binding

    first = Collection.objects.create(name="A", prefix="utsc", naan="61220", template=".zd")
    second = Collection.objects.create(name="B", prefix="utsc", naan="12345", template=".zd")
    a = Ark.objects.create(collection=first, identifier="utsc1", sequence=1)
    b = Ark.objects.create(collection=second, identifier="utsc1", sequence=1)
    Binding.objects.create(ark=a, name="URL", value="https://first.example")
    Binding.objects.create(ark=b, name="URL", value="https://second.example")

    assert client.get("/ark:/61220/utsc1", RAW_URI="/ark:/61220/utsc1")["Location"] == (
        "https://first.example"
    )
    assert client.get("/ark:/12345/utsc1", RAW_URI="/ark:/12345/utsc1")["Location"] == (
        "https://second.example"
    )
