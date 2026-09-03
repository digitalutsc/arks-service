"""
Minting new ARKs.

Ordering and uniqueness are the database's job here, not Perl's rand(): a
unique constraint on (naan, identifier) is the hard guarantee the legacy
service never had.
"""

import pytest

from core.models import Ark, Collection
from minting.minter import TemplateExhausted, mint
from minting.noid import check_char, parse_template, xdig2n

pytestmark = pytest.mark.django_db


def make_collection(template=".zd", prefix="utsc", naan="61220", name=None):
    return Collection.objects.create(
        name=name or f"C{template}{prefix}", prefix=prefix, naan=naan, template=template
    )


# --- sequential -----------------------------------------------------------


def test_first_mint_starts_the_sequence_at_zero():
    collection = make_collection(".zd")
    (ark,) = mint(collection)
    assert ark.name == "61220/utsc0"
    assert ark.sequence == 0


def test_sequential_minting_is_contiguous():
    collection = make_collection(".zd")
    arks = mint(collection, count=5)
    assert [a.name for a in arks] == [f"61220/utsc{n}" for n in range(5)]


def test_minting_continues_where_the_last_run_stopped():
    collection = make_collection(".zd")
    mint(collection, count=3)
    more = mint(collection, count=2)
    assert [a.name for a in more] == ["61220/utsc3", "61220/utsc4"]


def test_minting_continues_after_identifiers_that_arrived_by_import():
    collection = make_collection(".zd")
    # An imported ARK carries the sequence decoded from its identifier.
    Ark.objects.create(collection=collection, identifier="utsc99", sequence=99)
    (ark,) = mint(collection)
    assert ark.name == "61220/utsc100"


def test_minting_skips_an_identifier_that_is_already_taken():
    collection = make_collection(".zd")
    # A row with no sequence recorded still blocks its identifier.
    Ark.objects.create(collection=collection, identifier="utsc0")
    (ark,) = mint(collection)
    assert ark.name == "61220/utsc1"
    assert Ark.objects.filter(collection=collection).count() == 2


def test_a_fixed_width_sequence_runs_out():
    collection = make_collection(".sdd")  # two digits: 100 identifiers
    mint(collection, count=100)
    with pytest.raises(TemplateExhausted):
        mint(collection)


def test_nothing_is_minted_when_the_batch_cannot_be_completed():
    collection = make_collection(".sdd")
    mint(collection, count=98)
    with pytest.raises(TemplateExhausted):
        mint(collection, count=5)
    assert Ark.objects.filter(collection=collection).count() == 98


# --- random ---------------------------------------------------------------


def test_random_minting_produces_distinct_identifiers_inside_the_space():
    collection = make_collection(".rddd")  # 1000 identifiers
    arks = mint(collection, count=50)
    names = {a.name for a in arks}
    assert len(names) == 50
    for ark in arks:
        assert ark.identifier.startswith("utsc")
        assert 0 <= xdig2n(ark.identifier[len("utsc") :], "rddd") < 1000


def test_random_minting_is_not_sequential():
    collection = make_collection(".rdddd")  # 10k, so ordering is obvious
    sequences = [a.sequence for a in mint(collection, count=30)]
    assert sequences != sorted(sequences)


def test_random_minting_can_fill_a_small_space_completely():
    collection = make_collection(".rdd")  # 100 identifiers
    arks = mint(collection, count=100)
    assert len({a.identifier for a in arks}) == 100
    with pytest.raises(TemplateExhausted):
        mint(collection)


def test_random_minting_avoids_identifiers_already_present():
    collection = make_collection(".rdd")
    Ark.objects.create(collection=collection, identifier="utsc42", sequence=42)
    arks = mint(collection, count=99)
    assert "61220/utsc42" not in {a.name for a in arks}


# --- check characters -----------------------------------------------------


def test_minted_identifiers_carry_a_valid_check_character():
    collection = make_collection(".rdedk", prefix="63q")
    for ark in mint(collection, count=20):
        assert check_char(ark.name, "e") == ark.name


def test_check_character_is_not_left_as_a_placeholder():
    collection = make_collection(".rdedk", prefix="63q")
    (ark,) = mint(collection)
    assert "+" not in ark.name


# --- bookkeeping ----------------------------------------------------------


def test_minting_records_who_did_it(django_user_model):
    user = django_user_model.objects.create_user("kyle", password="x")
    collection = make_collection(".zd")
    (ark,) = mint(collection, user=user)
    assert ark.minted_by == user


def test_minted_arks_belong_to_their_collection():
    collection = make_collection(".zd")
    (ark,) = mint(collection)
    assert ark.collection == collection
    assert ark.naan == "61220"


def test_count_must_be_positive():
    collection = make_collection(".zd")
    with pytest.raises(ValueError):
        mint(collection, count=0)


def test_identifiers_include_the_collection_prefix():
    collection = make_collection(".zd", prefix="dsu")
    (ark,) = mint(collection)
    assert ark.identifier.startswith("dsu")


def test_a_collection_with_no_prefix_still_mints():
    collection = make_collection(".zd", prefix="")
    (ark,) = mint(collection)
    assert ark.name == "61220/0"


# --- consistency with the template ----------------------------------------


def test_minted_identifiers_match_what_the_template_promises():
    collection = make_collection(".sdddddd")
    spec = parse_template(collection.full_template)
    (ark,) = mint(collection)
    variable = ark.identifier[len(collection.prefix) :]
    assert len(variable) == len(spec.mask) - 1


# --- concurrency ----------------------------------------------------------
# The point of moving ordering into the database: two minters running at once
# must never produce the same ARK. Needs real connections, so real transactions.


@pytest.mark.django_db(transaction=True)
def test_concurrent_minters_never_produce_the_same_ark():
    import threading

    from django.db import connection, connections

    if connection.vendor == "sqlite":
        pytest.skip("SQLite serialises writes globally; nothing to prove here")

    collection = make_collection(".zd", name="concurrent")
    workers, results, errors = 8, [], []
    start = threading.Barrier(workers)

    def worker():
        try:
            start.wait()
            results.extend(a.name for a in mint(collection, count=5))
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
    assert len(results) == workers * 5
    assert len(set(results)) == workers * 5, "two minters produced the same ARK"
    assert Ark.objects.filter(collection=collection).count() == workers * 5


def test_minted_arks_come_back_with_primary_keys():
    # bulk_create cannot return primary keys on MySQL — the production engine —
    # so callers that bind to, or remember, what they just minted would get
    # None. Everything downstream (bulk bind's mint-missing, the fill-in
    # template download) depends on these.
    collection = make_collection(".zd", name="pk-check")
    arks = mint(collection, count=3)
    assert all(ark.pk is not None for ark in arks)
    assert sorted(a.pk for a in arks) == sorted(
        Ark.objects.filter(collection=collection).values_list("id", flat=True)
    )


def test_a_single_mint_request_is_capped(settings):
    # Unbounded count would build millions of identifiers inside one
    # transaction holding the collection lock, blocking every other minter.
    settings.MINT_MAX_PER_REQUEST = 10
    collection = make_collection(".zd", name="capped")
    with pytest.raises(ValueError, match="(?i)at most|10"):
        mint(collection, count=11)
    assert Ark.objects.filter(collection=collection).count() == 0
