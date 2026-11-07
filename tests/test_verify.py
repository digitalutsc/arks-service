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


# Legacy displayed every metadata value with '_' replaced by a space
# (resolver.php:248); this system emits values verbatim on purpose (INTENT.md),
# because the replacement corrupted URLs. The diff treats the two as equal, but
# only for metadata: a redirect target is still compared exactly.


def test_legacy_underscores_shown_as_spaces_match_our_verbatim_values():
    legacy = (
        200,
        "<pre>erc:\nWho: University of Toronto Scarborough Library\nLocal_id: obj 0</pre>",
    )
    new = (200, "erc:\nWho: University_of_Toronto_Scarborough_Library\nLocal_id: obj_0\n")
    assert compare("/ark:/61220/utsc1?", legacy, new) is None


def test_the_support_block_is_compared_the_same_way():
    legacy = (
        200,
        "<pre>erc:\nWho: Anonymous\n</pre><pre>erc-support:\n"
        "Support-who: University of Toronto Scarborough Library\n"
        "Support-what: Permanent:Dynamic Content\nSupport-when: March 2024\n</pre>",
    )
    new = (
        200,
        "erc:\nWho: Anonymous\n\nerc-support:\n"
        "Support-who: University_of_Toronto_Scarborough_Library\n"
        "Support-what: Permanent:Dynamic_Content\nSupport-when: March_2024\n",
    )
    assert compare("/ark:/61220/utsc1??", legacy, new) is None


def test_a_real_value_change_is_still_reported_despite_underscores():
    legacy = (200, "<pre>erc:\nWho: A C</pre>")
    new = (200, "erc:\nWho: A_B\n")
    assert compare("/ark:/61220/utsc1?", legacy, new) is not None


def test_a_redirect_target_is_still_compared_exactly():
    # In a URL an underscore matters: legacy and new must redirect to the same one.
    legacy = (302, "https://example.org/a b")
    new = (302, "https://example.org/a_b")
    assert compare("/ark:/61220/utsc1", legacy, new) is not None


# Measured on a local legacy copy (2026-11-07): resolver.php sends a relative
# Location for a miss, and prints its HTML/CSS "loader" page before every ARK
# answer, so its metadata and NAA bodies start with <html><head><style>…


def test_a_relative_legacy_404_redirect_is_a_miss():
    legacy = (302, "/404.php")
    assert (
        compare("/ark:/61220/utsc100", legacy, (404, ""), legacy_base="https://ark.example") is None
    )


def test_a_relative_redirect_to_a_deeper_404_page_is_still_a_target():
    legacy = (302, "/some/collection/404.php")
    assert compare("/ark:/61220/utsc100", legacy, (404, ""), legacy_base="https://ark.example")


LOADER = (
    "<html>\n<head>\n  <style>\n    .loader{\n      position: fixed;\n      left: 0px;\n"
    "    }\n    @keyframes spin {\n      0% { transform: rotate(0deg); }\n    }\n"
    "    pre {\n      white-space: pre-wrap;\n    }\n  </style>\n</head>\n<body>\n\n</body>\n</html>\n\n"
)


def test_legacys_loader_page_is_ignored_around_metadata():
    legacy = (200, LOADER + "<pre><pre>erc:\nWho: Anonymous\nUrl: https://e.example\n</pre><pre/>")
    new = (200, "erc:\nWho: Anonymous\nUrl: https://e.example\n")
    assert compare("/ark:/61220/utsc1?", legacy, new) is None


def test_legacys_loader_page_is_ignored_around_the_naa():
    legacy = (200, LOADER + "The U Of T Scarborough Library assigns identifiers")
    new = (200, "The U Of T Scarborough Library assigns identifiers\n")
    assert compare("/ark:/61220/", legacy, new) is None


def test_a_metadata_difference_behind_the_loader_is_still_reported():
    legacy = (200, LOADER + "<pre>erc:\nWho: Anonymous\n</pre>")
    new = (200, "erc:\nWho: Someone else\n")
    assert compare("/ark:/61220/utsc1?", legacy, new) is not None


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


def test_a_fetch_error_is_reported_as_an_error_not_a_difference():
    # A socket failure means "unknown", not "these resolve differently"; an
    # operator needs to re-run those rather than investigate them as findings.
    difference = compare(
        "/ark:/61220/utsc1", (0, "error: connection refused"), (302, "https://e.example")
    )
    assert difference is not None
    assert difference.is_error is True


def test_a_genuine_difference_is_not_an_error():
    difference = compare(
        "/ark:/61220/utsc1", (302, "https://old.example"), (302, "https://new.example")
    )
    assert difference.is_error is False


# --- legacy's storage encoding leaked into its answers --------------------


def test_entities_in_a_legacy_redirect_are_not_a_difference():
    # Legacy stored every value HTML-escaped and redirected to it as it stood,
    # so its Location header carries "&amp;" where the real URL has "&".
    legacy = (302, "https://example.org/search?a=1&amp;b=2")
    new = (302, "https://example.org/search?a=1&b=2")
    assert compare("/ark:/61220/utsc0", legacy, new) is None


def test_a_genuinely_different_target_is_still_a_difference():
    legacy = (302, "https://example.org/search?a=1&amp;b=2")
    new = (302, "https://example.org/search?a=1&b=3")
    assert compare("/ark:/61220/utsc0", legacy, new) is not None


def test_entities_in_legacy_metadata_are_not_a_difference():
    legacy = (200, "<pre>erc:\nWhat: Fish &amp; Chips\nWho: O&#039;Brien</pre>")
    new = (200, "erc:\nWhat: Fish & Chips\nWho: O'Brien")
    assert compare("/ark:/61220/utsc0?", legacy, new) is None


def test_a_trailing_carriage_return_in_legacy_metadata_is_not_a_difference():
    legacy = (200, "<pre>erc:\nTitle: Digital File Name: _A1\r</pre>")
    new = (200, "erc:\nTitle: Digital File Name: _A1")
    assert compare("/ark:/61220/utsc0?", legacy, new) is None


# --- differences the import already told us about -------------------------


def test_known_paths_are_read_from_the_import_report(tmp_path):
    from core.verify import read_known_paths

    report = tmp_path / "report.csv"
    report.write_text(
        "reason,table,ark_path,element,value\n"
        "duplicate-element,dsu_ark,/ark:/61220/utsc0,COLLECTION,Other\n"
        "redirect-for-unknown-ark,dsu_ark,/ark:/61220/utsc9biblio,REDIRECT,8\n"
    )
    assert read_known_paths(report) == {"/ark:/61220/utsc0", "/ark:/61220/utsc9biblio"}


def test_an_empty_report_names_nothing(tmp_path):
    from core.verify import read_known_paths

    report = tmp_path / "empty.csv"
    report.write_text("reason,table,ark_path,element,value\n")
    assert read_known_paths(report) == set()


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/ark:/61220/utsc0", "/ark:/61220/utsc0"),
        ("/ark:/61220/utsc0?", "/ark:/61220/utsc0"),
        ("/ark:/61220/utsc0??", "/ark:/61220/utsc0"),
        ("/ark:/61220/utsc0?info", "/ark:/61220/utsc0"),
        ("/ark:/61220/utsc0/page1?", "/ark:/61220/utsc0/page1"),
    ],
)
def test_an_inflection_is_the_same_ark_as_the_path_it_decorates(path, expected):
    from core.verify import base_path

    assert base_path(path) == expected
