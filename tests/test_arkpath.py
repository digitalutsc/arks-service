"""
Parsing an incoming ARK URL into its parts.

Mirrors the legacy resolver: the ARK is the first two slash-separated
components; anything after that is a qualifier, split into a hierarchy and an
optional variant at the first dot following the last slash. Legacy stored those
two as separate tab-delimited components; here they are one normalised string.
"""

import pytest

from core.arkpath import Inflection, parse_ark_path

# --- the identifier itself ------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "ark:/61220/utsc1",
        "/ark:/61220/utsc1",
        "ark:61220/utsc1",
        "/ark:61220/utsc1",
        "ark:/61220/utsc1/",
        "/ark:/61220/utsc1  ",
    ],
)
def test_accepts_every_spelling_of_a_bare_ark(path):
    parsed = parse_ark_path(path)
    assert parsed.naan == "61220"
    assert parsed.identifier == "utsc1"
    assert parsed.qualifier == ""
    assert parsed.name == "61220/utsc1"


def test_rejects_a_path_that_is_not_an_ark():
    assert parse_ark_path("/about") is None
    assert parse_ark_path("") is None


def test_naan_only_path_is_flagged():
    parsed = parse_ark_path("ark:/61220/")
    assert parsed.naan_only is True
    assert parsed.naan == "61220"
    assert parsed.identifier == ""


def test_identifier_may_contain_dots_when_there_is_no_hierarchy():
    # Legacy treated the second component as the identifier verbatim.
    parsed = parse_ark_path("ark:/61220/utsc1.2")
    assert parsed.identifier == "utsc1.2"
    assert parsed.qualifier == ""


# --- qualifiers -----------------------------------------------------------


def test_hierarchical_part_becomes_the_qualifier():
    parsed = parse_ark_path("ark:/61220/utsc1/page1")
    assert parsed.name == "61220/utsc1"
    assert parsed.qualifier == "/page1"
    assert parsed.hierarchy == "/page1"
    assert parsed.variant == ""


def test_nested_hierarchy_is_kept_whole():
    parsed = parse_ark_path("ark:/61220/utsc1/vol1/page3")
    assert parsed.qualifier == "/vol1/page3"


def test_variant_is_split_at_the_first_dot_after_the_last_slash():
    parsed = parse_ark_path("ark:/61220/utsc1/page1.image.png")
    assert parsed.name == "61220/utsc1"
    assert parsed.qualifier == "/page1.image.png"
    assert parsed.hierarchy == "/page1"
    assert parsed.variant == ".image.png"


def test_nested_hierarchy_with_a_variant():
    parsed = parse_ark_path("ark:/61220/utsc1/vol1/page3.jpg")
    assert parsed.hierarchy == "/vol1/page3"
    assert parsed.variant == ".jpg"
    assert parsed.qualifier == "/vol1/page3.jpg"


def test_a_dot_inside_a_hierarchy_component_is_not_a_variant():
    # Only a dot after the LAST slash introduces a variant. (Legacy mangled this
    # case into a malformed key; the import reads stored keys literally rather
    # than re-deriving them, so nothing depends on reproducing that bug.)
    parsed = parse_ark_path("ark:/61220/utsc1/a.b/c")
    assert parsed.hierarchy == "/a.b/c"
    assert parsed.variant == ""


def test_qualifier_round_trips_through_hierarchy_and_variant():
    for raw in ["/page1", "/page1.image.png", "/vol1/page3.jpg", ""]:
        parsed = parse_ark_path(f"ark:/61220/utsc1{raw}")
        assert parsed.hierarchy + parsed.variant == parsed.qualifier


# --- inflections ----------------------------------------------------------


def test_plain_ark_has_no_inflection():
    assert parse_ark_path("ark:/61220/utsc1").inflection is Inflection.NONE


def test_single_question_mark_requests_brief_metadata():
    assert parse_ark_path("ark:/61220/utsc1?").inflection is Inflection.BRIEF


def test_double_question_mark_requests_full_metadata():
    assert parse_ark_path("ark:/61220/utsc1??").inflection is Inflection.FULL


def test_question_info_requests_full_metadata():
    assert parse_ark_path("ark:/61220/utsc1?info").inflection is Inflection.FULL


def test_inflection_does_not_leak_into_the_identifier():
    for suffix in ["?", "??", "?info"]:
        parsed = parse_ark_path(f"ark:/61220/utsc1{suffix}")
        assert parsed.identifier == "utsc1"


def test_inflection_does_not_leak_into_the_qualifier():
    for suffix in ["?", "??", "?info"]:
        parsed = parse_ark_path(f"ark:/61220/utsc1/page1{suffix}")
        assert parsed.qualifier == "/page1"


def test_an_ordinary_query_string_is_not_an_inflection():
    parsed = parse_ark_path("ark:/61220/utsc1?utm_source=x")
    assert parsed.identifier == "utsc1"
    assert parsed.inflection is Inflection.NONE
    assert parsed.redirects is True


def test_an_inflected_ark_is_not_redirected():
    assert parse_ark_path("ark:/61220/utsc1?").redirects is False
    assert parse_ark_path("ark:/61220/utsc1").redirects is True


# --- service suffixes (/manifest) -----------------------------------------
# Which final segments are services is a setting of the ARK's collection
# (Collection.proxied_suffixes), so the parser keeps them in the qualifier and
# only exposes the last segment and its parent. See
# tests/test_collection_resolution_settings.py.


def test_a_manifest_suffix_stays_in_the_qualifier():
    parsed = parse_ark_path("ark:/61220/utsc1/manifest")
    assert parsed.name == "61220/utsc1"
    assert parsed.qualifier == "/manifest"
    assert parsed.last_segment == "manifest"
    assert parsed.parent_qualifier == ""


def test_manifest_after_a_qualifier_has_that_qualifier_as_its_parent():
    parsed = parse_ark_path("ark:/61220/utsc1/page1/manifest")
    assert parsed.qualifier == "/page1/manifest"
    assert parsed.parent_qualifier == "/page1"


def test_a_plain_ark_has_no_last_segment():
    parsed = parse_ark_path("ark:/61220/utsc1")
    assert (parsed.last_segment, parsed.parent_qualifier) == ("", "")


# --- percent-encoding -----------------------------------------------------
# The legacy rewrite handed resolver.php a URL-decoded $_GET['q'], and the
# import stores legacy keys literally, so a qualifier stored as "/page 1" is
# reached by requesting "/page%201". Comparing the encoded form would 404.


def test_a_percent_encoded_space_is_decoded():
    parsed = parse_ark_path("/ark:/61220/utsc1/page%201")
    assert parsed.qualifier == "/page 1"


def test_a_percent_encoded_identifier_is_decoded():
    parsed = parse_ark_path("/ark:/61220/utsc%2Da")
    assert parsed.identifier == "utsc-a"


def test_non_ascii_percent_encoding_is_decoded():
    parsed = parse_ark_path("/ark:/61220/caf%C3%A9")
    assert parsed.identifier == "café"


def test_an_encoded_question_mark_is_not_an_inflection():
    # %3F is data inside the identifier, not the metadata inflection.
    parsed = parse_ark_path("/ark:/61220/utsc1%3F")
    assert parsed.identifier == "utsc1?"
    assert parsed.inflection is Inflection.NONE


def test_a_real_question_mark_still_inflects_after_decoding():
    parsed = parse_ark_path("/ark:/61220/caf%C3%A9?")
    assert parsed.identifier == "café"
    assert parsed.inflection is Inflection.BRIEF


def test_an_encoded_slash_does_not_split_the_qualifier():
    # %2F is a literal slash inside one path component, not a separator.
    parsed = parse_ark_path("/ark:/61220/utsc1/a%2Fb")
    assert parsed.qualifier == "/a/b"
    assert parsed.name == "61220/utsc1"
