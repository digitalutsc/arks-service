"""
Conformance tests for the noid port.

Every expectation here was produced by running the LEGACY PHP implementation
(`tests/fixtures/generate_vectors.php`). If these pass, newly minted ARKs are
indistinguishable from the ~100k already in production and every legacy ARK
still validates.
"""

import json
from pathlib import Path

import pytest

from minting.noid import (
    ALPHABET_CHECKS,
    ALPHABETS,
    NOLIMIT,
    REPERTOIRES,
    TemplateError,
    check_char,
    check_repertoire,
    make_id,
    n2xdig,
    parse_template,
)

VECTORS = json.loads((Path(__file__).parent / "fixtures" / "noid_vectors.json").read_text())


def _ids(records, *fields):
    return [":".join(str(r[f]) for f in fields) for r in records]


# --- constants ------------------------------------------------------------


def test_alphabets_match_legacy():
    assert ALPHABETS == VECTORS["alphabets"]


def test_alphabet_checks_match_legacy():
    assert ALPHABET_CHECKS == VECTORS["alphabet_checks"]


def test_repertoires_match_legacy():
    assert REPERTOIRES == VECTORS["repertoires"]


# --- n2xdig ---------------------------------------------------------------


@pytest.mark.parametrize("case", VECTORS["n2xdig"], ids=_ids(VECTORS["n2xdig"], "mask", "num"))
def test_n2xdig_matches_legacy(case):
    assert n2xdig(case["num"], case["mask"]) == case["expected"]


# --- check character ------------------------------------------------------


@pytest.mark.parametrize(
    "case", VECTORS["check_char"], ids=_ids(VECTORS["check_char"], "alphabet", "id")
)
def test_check_char_matches_legacy(case):
    assert check_char(case["id"], case["alphabet"]) == case["expected"]


def test_check_char_defaults_to_e_repertoire():
    assert check_char("61220/utsc1+") == "61220/utsc1p"


# --- template parsing -----------------------------------------------------

# Legacy returns NOLIMIT with an empty mask for "" and "-" ("no minting possible").
# A collection here always needs a real minting template, so the port rejects those
# instead — the one deliberate divergence, pinned by
# test_empty_template_is_rejected_unlike_legacy below.
DEGENERATE = {"", "-"}
VALID_TEMPLATES = [
    c for c in VECTORS["parse_template"] if c["total"] != 0 and c["template"] not in DEGENERATE
]
INVALID_TEMPLATES = [
    c for c in VECTORS["parse_template"] if c["total"] == 0 or c["template"] in DEGENERATE
]


@pytest.mark.parametrize("case", VALID_TEMPLATES, ids=_ids(VALID_TEMPLATES, "template"))
def test_parse_template_matches_legacy(case):
    spec = parse_template(case["template"])
    assert spec.prefix == case["prefix"]
    assert spec.mask == case["mask"]
    assert spec.gen_type == case["gen_type"]
    assert spec.total == case["total"]
    assert spec.synonym == case["message"]


@pytest.mark.parametrize("case", INVALID_TEMPLATES, ids=_ids(INVALID_TEMPLATES, "template"))
def test_parse_template_rejects_what_legacy_rejects(case):
    with pytest.raises(TemplateError):
        parse_template(case["template"])


@pytest.mark.parametrize("template", sorted(DEGENERATE))
def test_empty_template_is_rejected_unlike_legacy(template):
    # Legacy treated these as "no minting possible" and returned NOLIMIT; a
    # collection in this system must always be able to mint.
    with pytest.raises(TemplateError):
        parse_template(template)


def test_unlimited_template_reports_nolimit():
    assert parse_template(".zd").total == NOLIMIT
    assert parse_template(".zd").unlimited is True
    assert parse_template(".rddd").unlimited is False


def test_template_spec_knows_whether_it_has_a_check_character():
    assert parse_template(".rdedk").has_check_char is True
    assert parse_template(".zd").has_check_char is False


# --- check-character repertoire resolution --------------------------------
# Legacy getAlphabet() returns TRUE (no check char), FALSE (cannot determine),
# or the repertoire letter. The port returns "" , None and the letter.

_ALPHA_EXPECTED = {True: "", False: None}


@pytest.mark.parametrize(
    "case", VECTORS["get_alphabet"], ids=_ids(VECTORS["get_alphabet"], "template")
)
def test_check_repertoire_matches_legacy(case):
    expected = _ALPHA_EXPECTED.get(case["expected"], case["expected"])
    assert check_repertoire(case["template"]) == expected


# --- end-to-end id construction -------------------------------------------


@pytest.mark.parametrize(
    "seq", VECTORS["sequences"], ids=_ids(VECTORS["sequences"], "firstpart", "mask")
)
def test_minted_ids_match_legacy(seq):
    produced = [make_id(seq["firstpart"], seq["mask"], entry["n"]) for entry in seq["ids"]]
    assert produced == [entry["id"] for entry in seq["ids"]]


def test_production_template_mints_the_expected_ark():
    # UTSC production: NAAN 61220, prefix "utsc", template ".zd".
    assert make_id("61220/utsc", "zd", 1) == "61220/utsc1"
    assert make_id("61220/utsc", "zd", 10) == "61220/utsc10"


def test_ids_with_check_characters_round_trip():
    minted = make_id("61220/f5", "reedeedk", 12345)
    assert check_char(minted, "e") == minted
