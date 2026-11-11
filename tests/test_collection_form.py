"""
The New collection form, shaped like the legacy admin.php one.

A template dropdown with its description underneath, a required unique prefix,
a textarea for the NAA, and notes instead of placeholders. The validation
messages are the legacy ones where legacy had one.
"""

import re

import pytest
from django.urls import reverse

from admin_ui.roles import ADMIN, ensure_groups, set_role
from core.models import Collection
from minting.noid import TEMPLATE_CATALOGUE, parse_template, template_choices

pytestmark = pytest.mark.django_db

VALID = {
    "name": "UTSC",
    "prefix": "utsc",
    "naan": "61220",
    "naa": "UTSC Library",
    "template": ".zd",
    "term": "medium",
}


def url():
    return reverse("admin_ui:collection_create")


@pytest.fixture
def admin_client(django_user_model, client):
    ensure_groups()
    user = django_user_model.objects.create_user("boss", password="pw")
    set_role(user, ADMIN)
    client.force_login(user)
    return client


# --- rendering ------------------------------------------------------------


def test_form_offers_every_catalogue_template_as_an_option(admin_client):
    body = admin_client.get(url()).content.decode()
    for value, description in TEMPLATE_CATALOGUE:
        assert f'<option value="{value}"' in body
        assert description in body


GROUPS = ["Sequential, no limit", "Sequential, fixed size", "Random"]


def group_of(value):
    spec = parse_template("x" + value)
    if spec.is_random:
        return "Random"
    return "Sequential, no limit" if spec.unlimited else "Sequential, fixed size"


def test_the_templates_are_grouped_by_how_they_mint(admin_client):
    body = admin_client.get(url()).content.decode()
    select = re.search(r'<select id="template".*?</select>', body, re.S).group(0)
    groups = re.findall(r'<optgroup label="([^"]+)">(.*?)</optgroup>', select, re.S)
    assert [label for label, _ in groups] == GROUPS
    grouped = {label: re.findall(r'<option value="([^"]+)"', options) for label, options in groups}
    expected = {label: [] for label in GROUPS}
    for value, _ in TEMPLATE_CATALOGUE:
        expected[group_of(value)].append(value)
    assert grouped == expected  # each template once, in catalogue order, in its own group
    assert ".zd" in grouped["Sequential, no limit"]


def test_form_uses_a_textarea_for_the_naa(admin_client):
    body = admin_client.get(url()).content.decode()
    assert re.search(r'<textarea[^>]*\bname="naa"', body)


def test_form_uses_notes_rather_than_placeholders(admin_client):
    body = admin_client.get(url()).content.decode()
    assert "placeholder=" not in body
    assert "Prefix or Shoulder" in body
    assert "cdlib.org/naan_registry" in body


def test_no_template_is_preselected(admin_client):
    body = admin_client.get(url()).content.decode()
    # Legacy forced a choice; the first option is the disabled "Choose..." one.
    assert not re.search(r'<option value="\.[a-z]+"[^>]*\bselected', body)


def fieldset(body, legend):
    """The HTML of the fieldset whose legend is ``legend``."""
    match = re.search(
        rf"<fieldset[^>]*>\s*<legend>{re.escape(legend)}</legend>(.*?)</fieldset>", body, re.S
    )
    assert match, f"no fieldset with the legend {legend!r}"
    return match.group(1)


def test_collection_fields_and_resolution_settings_are_in_separate_boxes(admin_client):
    body = admin_client.get(url()).content.decode()
    collection = fieldset(body, "Collection settings")
    resolution = fieldset(body, "Resolution settings")
    for name in ("name", "template", "prefix", "naan", "naa"):
        assert f'name="{name}"' in collection
        assert f'name="{name}"' not in resolution
    for name in ("redirect_elements", "proxied_suffixes", "suffix_passthrough"):
        assert f'name="{name}"' in resolution
        assert f'name="{name}"' not in collection


def test_the_naan_is_explained_in_plain_words_and_keeps_the_registry_link(admin_client):
    collection = fieldset(admin_client.get(url()).content.decode(), "Collection settings")
    assert "identifies your organisation" in collection
    assert re.search(
        r'<a href="https://cdlib\.org/naan_registry"[^>]*>NAAN registry</a>', collection
    )


def test_the_naa_is_explained_in_plain_words(admin_client):
    collection = fieldset(admin_client.get(url()).content.decode(), "Collection settings")
    assert "name of your organisation" in collection


def test_the_naa_help_says_which_collection_answers_for_a_shared_naan(admin_client):
    # resolver/views.py _naa_response: the first collection by name with an NAA.
    collection = fieldset(admin_client.get(url()).content.decode(), "Collection settings")
    assert "comes first alphabetically" in collection


def test_the_prefix_explains_what_unique_means(admin_client):
    collection = fieldset(admin_client.get(url()).content.decode(), "Collection settings")
    assert "starts every ARK in this collection" in collection
    assert "the beginning of" in collection


def test_the_form_does_not_show_the_term_at_all(admin_client):
    # Every collection made here is long-term; there is nothing to choose or explain.
    body = admin_client.get(url()).content.decode()
    assert 'name="term"' not in body
    assert ">Term<" not in body
    assert 'id="term"' not in body


def test_the_naa_is_marked_required(admin_client):
    collection = fieldset(admin_client.get(url()).content.decode(), "Collection settings")
    assert re.search(r'<textarea[^>]*\bname="naa"[^>]*\brequired', collection)


# --- validation -----------------------------------------------------------


def test_a_missing_prefix_is_rejected(admin_client):
    response = admin_client.post(url(), {**VALID, "prefix": ""})
    assert response.status_code == 200
    assert "A prefix or shoulder is required" in response.content.decode()
    assert Collection.objects.count() == 0


def test_a_prefix_already_used_in_the_naan_is_rejected_with_the_legacy_message(admin_client):
    Collection.objects.create(**VALID)
    response = admin_client.post(url(), {**VALID, "name": "Another"})
    assert response.status_code == 200
    assert (
        "The entered prefix has been used, please enter another prefix" in response.content.decode()
    )
    assert Collection.objects.count() == 1


def test_the_same_prefix_under_another_naan_is_allowed(admin_client):
    Collection.objects.create(**VALID)
    response = admin_client.post(url(), {**VALID, "name": "Another", "naan": "99999"})
    assert response.status_code == 302
    assert Collection.objects.count() == 2


def test_every_collection_made_in_the_form_needs_a_name_assigning_authority(admin_client):
    response = admin_client.post(url(), {**VALID, "naa": ""})
    assert response.status_code == 200
    assert "A long-term collection needs a Name Assigning Authority" in response.content.decode()
    assert Collection.objects.count() == 0


@pytest.mark.parametrize("posted", ["short", "medium", "", None])
def test_the_form_always_creates_a_long_term_collection(admin_client, posted):
    data = {key: value for key, value in VALID.items() if key != "term"}
    if posted is not None:
        data["term"] = posted
    response = admin_client.post(url(), data)
    assert response.status_code == 302
    assert Collection.objects.get().term == Collection.Term.LONG


def test_a_failed_submission_keeps_what_was_typed(admin_client):
    body = admin_client.post(url(), {**VALID, "prefix": "", "template": ".rddd"}).content.decode()
    assert 'value="UTSC"' in body
    assert re.search(r'<option value="\.rddd"[^>]*\bselected', body)


def test_a_valid_submission_creates_the_collection_and_redirects(admin_client):
    response = admin_client.post(url(), VALID)
    collection = Collection.objects.get()
    assert response.status_code == 302
    assert response["Location"] == reverse("admin_ui:collection_detail", args=[collection.pk])
    assert (collection.prefix, collection.naan, collection.template, collection.term) == (
        "utsc",
        "61220",
        ".zd",
        "long",
    )


# --- the catalogue itself -------------------------------------------------


def test_every_catalogue_template_parses():
    # "b1" is drawn from the "e" alphabet, which the check-character templates
    # require of the prefix; the others accept anything.
    for value, _ in TEMPLATE_CATALOGUE:
        parse_template("b1" + value)


def test_a_check_character_template_rejects_a_prefix_outside_its_alphabet(admin_client):
    # "utsc" has a "u", which is not in "0123456789bcdfghjkmnpqrstvwxz".
    response = admin_client.post(url(), {**VALID, "template": ".rdedk"})
    assert response.status_code == 200
    assert "may contain only characters from" in response.content.decode()
    assert Collection.objects.count() == 0


def test_capacity_is_unlimited_exactly_for_the_z_masks():
    for choice in template_choices():
        if choice["value"].startswith(".z"):
            assert choice["capacity"] == "unlimited", choice
        else:
            assert re.fullmatch(r"[\d,]+", choice["capacity"]), choice


def test_capacity_matches_the_minter():
    by_value = {choice["value"]: choice["capacity"] for choice in template_choices()}
    assert by_value[".rddd"] == "1,000"
    assert by_value[".sdddddd"] == "1,000,000"
    assert by_value[".reedeedk"] == "70,728,100"
