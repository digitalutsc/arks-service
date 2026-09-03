"""
Cutover verification.

Before the Apache vhost is flipped, every ARK must resolve identically on the
legacy service and this one. These are the pieces that decide *what* gets
compared; the HTTP fetching around them is thin.
"""

import pytest

from core.models import Ark, Binding, Collection
from core.verify import Difference, compare, iter_check_paths

pytestmark = pytest.mark.django_db


@pytest.fixture
def collection():
    return Collection.objects.create(
        name="UTSC", prefix="utsc", naan="61220", naa="UTSC Library", template=".zd"
    )


@pytest.fixture
def data(collection):
    a0 = Ark.objects.create(collection=collection, identifier="utsc0", sequence=0)
    Binding.objects.create(ark=a0, name="URL", value="https://example.org/0")
    a1 = Ark.objects.create(collection=collection, identifier="utsc1", sequence=1)
    Binding.objects.create(ark=a1, name="URL", value="https://example.org/1")
    Binding.objects.create(ark=a1, qualifier="/page1", name="URL", value="https://example.org/1/p1")
    Binding.objects.create(
        ark=a1, qualifier="/page1.png", name="URL", value="https://example.org/1/p1.png"
    )
    return a0, a1


def test_every_ark_is_checked(data):
    paths = list(iter_check_paths())
    assert "/ark:/61220/utsc0" in paths
    assert "/ark:/61220/utsc1" in paths


def test_every_bound_qualifier_is_checked(data):
    paths = list(iter_check_paths())
    assert "/ark:/61220/utsc1/page1" in paths
    assert "/ark:/61220/utsc1/page1.png" in paths


def test_a_qualifier_is_only_checked_once_however_many_elements_it_has(data, collection):
    ark = Ark.objects.get(identifier="utsc1")
    Binding.objects.create(ark=ark, qualifier="/page1", name="PID", value="islandora:1")
    paths = list(iter_check_paths())
    assert paths.count("/ark:/61220/utsc1/page1") == 1


def test_inflections_are_included_when_asked(data):
    paths = list(iter_check_paths(inflections=True))
    assert "/ark:/61220/utsc0?" in paths
    assert "/ark:/61220/utsc0??" in paths


def test_inflections_are_excluded_by_default(data):
    assert not any(p.endswith("?") for p in iter_check_paths())


def test_the_naan_root_is_checked(data):
    assert "/ark:/61220/" in list(iter_check_paths())


def test_a_sample_limits_how_many_arks_are_checked(data):
    paths = list(iter_check_paths(sample=1))
    assert sum(1 for p in paths if p.startswith("/ark:/61220/utsc")) < 4


def test_identical_redirects_are_not_a_difference():
    assert (
        compare("/ark:/61220/utsc0", (302, "https://example.org/0"), (302, "https://example.org/0"))
        is None
    )


def test_a_different_target_is_reported():
    difference = compare(
        "/ark:/61220/utsc0", (302, "https://old.example"), (302, "https://new.example")
    )
    assert isinstance(difference, Difference)
    assert difference.legacy == "https://old.example"
    assert difference.new == "https://new.example"


def test_a_different_status_is_reported():
    difference = compare("/ark:/61220/utsc0", (302, "https://x.example"), (404, ""))
    assert difference is not None
    assert "404" in difference.reason or difference.new_status == 404


def test_matching_404s_are_not_a_difference():
    assert compare("/ark:/61220/nope", (404, ""), (404, "")) is None


def test_a_trailing_slash_difference_in_the_target_is_still_a_difference():
    assert (
        compare("/ark:/x", (302, "https://a.example/x"), (302, "https://a.example/x/")) is not None
    )


def test_matching_metadata_bodies_are_not_a_difference():
    assert compare("/ark:/61220/utsc0?", (200, "erc:\nUrl: x"), (200, "erc:\nUrl: x")) is None


def test_different_metadata_bodies_are_reported():
    assert compare("/ark:/61220/utsc0?", (200, "erc:\nUrl: x"), (200, "erc:\nUrl: y")) is not None
