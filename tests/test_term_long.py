"""
Every collection is long-term (2026-11-11).

Short and Medium change nothing in this service, so the staff form, the
``createcollection`` command (arks-cli) and ``import_legacy`` all create Long
collections, and a collection made without a term gets Long. Long's one effect
is on the form, which then requires the NAA.
"""

import pytest

from core.models import Collection
from tests.test_legacy_import import build_legacy_db, run_import

pytestmark = pytest.mark.django_db


def test_a_collection_created_without_a_term_is_long():
    collection = Collection.objects.create(name="X", prefix="x", naan="61220", template=".zd")
    assert collection.term == Collection.Term.LONG


@pytest.mark.parametrize(
    "flags",
    [
        {":/longterm": "1", ":/wrap": ""},  # long in the legacy minter
        {":/longterm": "", ":/wrap": "1"},  # short
        {":/longterm": "", ":/wrap": ""},  # medium
        {},  # neither flag present
    ],
)
def test_the_legacy_import_always_creates_a_long_term_collection(tmp_path, flags):
    path = tmp_path / "legacy.sqlite3"
    build_legacy_db(path, config=flags)
    run_import(path)
    assert Collection.objects.get().term == Collection.Term.LONG
