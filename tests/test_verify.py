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


def test_inflections_can_be_switched_off(data):
    assert not any("?" in p for p in iter_check_paths(inflections=False))


def test_the_naan_root_is_checked(data):
    assert "/ark:/61220/" in list(iter_check_paths())


def test_a_sample_limits_how_many_arks_are_checked(data):
    # Counts distinct ARKs, not paths: each ARK contributes several paths once
    # inflections are included.
    sampled = {p.split("?")[0] for p in iter_check_paths(sample=1) if p.count("/") > 2}
    everything = {p.split("?")[0] for p in iter_check_paths() if p.count("/") > 2}
    assert len(sampled) < len(everything)


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


# --- normalising legacy's answers -----------------------------------------
# The two systems say the same thing in different words. Legacy answers a miss
# with a 302 to /404.php and wraps metadata in <pre>; without normalising, every
# unbound ARK and every inflection would report as a difference and the gate
# would never go green.


def test_a_legacy_404_redirect_matches_a_real_404():
    legacy = (302, "https://ark.example/404.php")
    assert compare("/ark:/61220/utsc9", legacy, (404, "")) is None


def test_a_legacy_404_redirect_still_differs_from_a_real_target():
    legacy = (302, "https://ark.example/404.php")
    assert compare("/ark:/61220/utsc9", legacy, (302, "https://example.org/9")) is not None


def test_a_real_redirect_to_a_page_called_404_is_not_treated_as_a_miss():
    # Only the legacy service's own error page counts.
    legacy = (302, "https://example.org/collections/404.php")
    difference = compare("/ark:/61220/utsc9", legacy, (404, ""), legacy_base="https://ark.example")
    assert difference is not None


def test_metadata_wrapped_in_pre_matches_plain_text():
    legacy = (200, "<pre><pre>\nerc:\nWho: Anonymous\nUrl: https://e.example\n</pre><pre/>")
    new = (200, "erc:\nWho: Anonymous\nUrl: https://e.example\n")
    assert compare("/ark:/61220/utsc1?", legacy, new) is None


def test_metadata_order_does_not_matter():
    legacy = (200, "<pre>erc:\nUrl: https://e.example\nWho: Anonymous</pre>")
    new = (200, "erc:\nWho: Anonymous\nUrl: https://e.example\n")
    assert compare("/ark:/61220/utsc1?", legacy, new) is None


def test_a_missing_metadata_line_is_still_reported():
    legacy = (200, "<pre>erc:\nWho: Anonymous\nUrl: https://e.example</pre>")
    new = (200, "erc:\nWho: Anonymous\n")
    difference = compare("/ark:/61220/utsc1?", legacy, new)
    assert difference is not None
    assert "https://e.example" in difference.legacy


def test_a_changed_metadata_value_is_reported():
    legacy = (200, "<pre>erc:\nUrl: https://old.example</pre>")
    new = (200, "erc:\nUrl: https://new.example\n")
    assert compare("/ark:/61220/utsc1?", legacy, new) is not None


def test_inflections_are_checked_by_default():
    # The gate is worthless if the default run skips the paths most likely to
    # differ.
    import inspect

    signature = inspect.signature(iter_check_paths)
    assert signature.parameters["inflections"].default is True


def test_info_inflection_is_checked_too(data):
    paths = list(iter_check_paths(inflections=True))
    assert "/ark:/61220/utsc0?info" in paths
