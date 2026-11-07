"""
The command helpers in core.management.commands._common.

The operator commands use them, and so does the optional arks-cli plugin
(bind, unbind, mint, …): they are part of what core offers plugins
(arkservice.plugins.PLUGIN_API). The plugin's own tests cover the commands; these
pin the helpers here, in core, where they live.
"""

import pytest
from django.core.management import CommandError

from core.management.commands._common import get_ark, get_collection
from core.models import Ark, Collection

pytestmark = pytest.mark.django_db


@pytest.fixture
def collection():
    return Collection.objects.create(name="UTSC", prefix="utsc", naan="61220", template=".zd")


@pytest.fixture
def ark(collection):
    return Ark.objects.create(collection=collection, identifier="utsc1", sequence=1)


# --- get_collection -------------------------------------------------------


def test_a_collection_is_found_by_name_or_prefix(collection):
    assert get_collection("UTSC") == collection
    assert get_collection("utsc") == collection
    assert get_collection("61220/utsc") == collection


def test_a_prefix_shared_across_naans_must_name_the_naan(collection):
    other = Collection.objects.create(name="Other", prefix="utsc", naan="99999", template=".zd")
    with pytest.raises(CommandError, match="More than one"):
        get_collection("utsc")
    assert get_collection("99999/utsc") == other


def test_an_unknown_collection_lists_the_known_ones(collection):
    with pytest.raises(CommandError, match="61220/utsc"):
        get_collection("nope")


# --- get_ark --------------------------------------------------------------


def test_an_ark_is_found_with_and_without_a_qualifier(ark):
    assert get_ark("61220/utsc1") == (ark, "")
    assert get_ark("/61220/utsc1/page2") == (ark, "/page2")


def test_a_dotted_name_reads_as_a_variant_of_the_object(ark):
    # How export writes it: '61220/utsc1.pdf' is utsc1's '.pdf' variant.
    assert get_ark("61220/utsc1.pdf") == (ark, ".pdf")


def test_an_identifier_that_really_contains_a_dot_wins(collection, ark):
    dotted = Ark.objects.create(collection=collection, identifier="utsc1.pdf", sequence=2)
    assert get_ark("61220/utsc1.pdf") == (dotted, "")


def test_an_unknown_ark_is_reported(ark):
    with pytest.raises(CommandError, match="No such ARK: 61220/utsc9"):
        get_ark("61220/utsc9")
    with pytest.raises(CommandError, match="No such ARK"):
        get_ark("61220/utsc9.pdf")


def test_garbage_is_not_an_ark(ark):
    with pytest.raises(CommandError, match="not a valid ARK"):
        get_ark("")


def test_a_name_must_match_exactly_on_every_engine(collection):
    # MySQL's default collation ignores case, so a plain name= lookup found the
    # collection named 'UTSC' for 'utsc' there, but not on PostgreSQL. Names now
    # match exactly everywhere ('utsc' is still found, as the prefix).
    Collection.objects.create(name="Maps", prefix="map", naan="61220", template=".zd")
    assert get_collection("Maps").prefix == "map"
    with pytest.raises(CommandError, match="No collection"):
        get_collection("maps")
