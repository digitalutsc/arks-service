"""
Identifier normalisation (draft-kunze-ark-44 §3.2), as a fallback only.

Three requests a person can reasonably send were 404s here though the spec, and
the N2T -> arks.org chain in front of us, treat them as the same ARK:

- ``ARK:`` in capitals: the label is case-insensitive (step 3);
- a hyphen anywhere after the NAAN: hyphens are insignificant (step 6), and
  arks.org removes them before forwarding to us;
- a trailing ``.``: a citation pasted with its full stop (step 8).

Every existing ARK must keep resolving exactly as before, so the normalised form
is only tried after the request as written has missed. And because the chain
strips hyphens, nothing new may be stored with one: a hyphenated qualifier or
prefix could never be reached through N2T. See INTENTS_identifier_normalisation.md.
"""

import io

import pytest
from django.core.exceptions import ValidationError
from django.core.management import CommandError, call_command
from django.urls import reverse

from admin_ui.roles import ADMIN, EDITOR, ensure_groups, set_role
from core.arkpath import parse_ark_path
from core.counters import flush_counters
from core.models import Ark, Binding, Collection, Resolution
from core.services import bind_element, unbind_elements
from jobs.bulkbind import apply_csv

pytestmark = pytest.mark.django_db


@pytest.fixture
def collection():
    return Collection.objects.create(
        name="UTSC", prefix="utsc", naan="61220", naa="UTSC Library", template=".zd"
    )


@pytest.fixture
def ark(collection):
    ark = Ark.objects.create(collection=collection, identifier="utsc1", sequence=1)
    Binding.objects.create(ark=ark, name="URL", value="https://example.org/1")
    Binding.objects.create(ark=ark, name="WHO?", value="UTSC Library")
    Binding.objects.create(ark=ark, qualifier="/page2", name="URL", value="https://example.org/p2")
    Binding.objects.create(ark=ark, qualifier="/page2", name="WHAT?", value="Page two")
    return ark


def get(client, path):
    """Issue a request, preserving the raw URI so a trailing '?' survives."""
    return client.get(path, RAW_URI=path)


# --- the normalised form --------------------------------------------------


@pytest.mark.parametrize(
    ("path", "identifier", "qualifier"),
    [
        ("ark:/61220/utsc-1", "utsc1", ""),
        ("ark:/61220/utsc1.", "utsc1", ""),
        ("ark:/61220/utsc-1..", "utsc1", ""),
        ("ark:/61220/utsc1/page-2", "utsc1", "/page2"),
        ("ark:/61220/utsc1/page2.", "utsc1", "/page2"),
        ("ark:/61220/utsc1/page2.image.png.", "utsc1", "/page2.image.png"),
        ("ark:/61220/utsc1/page2/.", "utsc1", "/page2"),
        ("ark:/61220/utsc1/.", "utsc1", ""),
        ("ark:/61220/utsc1/utsc%2D1", "utsc1", "/utsc1"),
    ],
)
def test_the_normalised_form_drops_hyphens_and_trailing_dots(path, identifier, qualifier):
    normalised = parse_ark_path(path).normalised()
    assert (normalised.identifier, normalised.qualifier) == (identifier, qualifier)


@pytest.mark.parametrize(
    "path", ["ark:/61220/utsc1", "ark:/61220/utsc1/page2.image.png", "ark:/61220/UTSC1"]
)
def test_there_is_no_normalised_form_when_nothing_would_change(path):
    assert parse_ark_path(path).normalised() is None


def test_a_name_that_normalises_to_nothing_has_no_normalised_form():
    assert parse_ark_path("ark:/61220/-").normalised() is None


def test_the_normalised_form_keeps_the_inflection_and_a_service_suffix():
    parsed = parse_ark_path("ark:/61220/utsc-1/manifest").normalised()
    assert (parsed.identifier, parsed.qualifier) == ("utsc1", "/manifest")
    parsed = parse_ark_path("ark:/61220/utsc-1??").normalised()
    assert not parsed.redirects


def test_case_is_never_normalised():
    # Names and qualifiers are case-sensitive in the spec, and 32,100 of our
    # qualifier bindings use upper case.
    parsed = parse_ark_path("ark:/61220/UTSC-1/Page-2").normalised()
    assert (parsed.identifier, parsed.qualifier) == ("UTSC1", "/Page2")


# --- row 2: the ark: label in any case ------------------------------------


@pytest.mark.parametrize(
    "path", ["/ARK:/61220/utsc1", "/Ark:/61220/utsc1", "/ARK:61220/utsc1", "/aRk:/61220/utsc1"]
)
def test_the_label_is_case_insensitive(client, ark, path):
    response = get(client, path)
    assert response.status_code == 302
    assert response["Location"] == "https://example.org/1"


def test_an_upper_case_label_still_answers_an_inflection(client, ark):
    response = get(client, "/ARK:/61220/utsc1?")
    assert response.status_code == 200
    assert response.content.decode().startswith("erc:")


def test_an_upper_case_label_still_answers_a_bare_naan(client, collection):
    response = get(client, "/ARK:/61220/")
    assert response.status_code == 200
    assert response.content.decode() == "UTSC Library\n"


# --- rows 3 and 7: hyphens and a trailing dot, on a miss ------------------


@pytest.mark.parametrize(
    ("path", "target"),
    [
        ("/ark:/61220/utsc-1", "https://example.org/1"),
        ("/ark:/61220/u-t-s-c-1", "https://example.org/1"),
        ("/ark:/61220/utsc1.", "https://example.org/1"),
        ("/ark:61220/utsc1.", "https://example.org/1"),
        ("/ark:/61220/utsc-1.", "https://example.org/1"),
        ("/ark:/61220/utsc1/page-2", "https://example.org/p2"),
        ("/ark:/61220/utsc-1/page-2", "https://example.org/p2"),
        ("/ark:/61220/utsc1/page2.", "https://example.org/p2"),
        ("/ark:/61220/utsc1/page2/.", "https://example.org/p2"),
        ("/ARK:/61220/utsc-1/page2.", "https://example.org/p2"),
    ],
)
def test_a_hyphen_or_trailing_dot_resolves_to_the_stored_ark(client, ark, path, target):
    response = get(client, path)
    assert response.status_code == 302
    assert response["Location"] == target


def test_an_exact_match_wins_over_the_normalised_form(client, collection, ark):
    # A stored ARK keeps exact matching: had one been imported with a hyphen,
    # its own URL is the answer, not that of the ARK it normalises to.
    hyphenated = Ark.objects.create(collection=collection, identifier="utsc-1", sequence=0)
    Binding.objects.create(ark=hyphenated, name="URL", value="https://example.org/hyphen")

    assert get(client, "/ark:/61220/utsc-1")["Location"] == "https://example.org/hyphen"
    assert get(client, "/ark:/61220/utsc1")["Location"] == "https://example.org/1"


def test_an_exact_qualifier_wins_over_the_normalised_form(client, ark):
    Binding.objects.create(ark=ark, qualifier="/page-2", name="URL", value="https://example.org/h")
    assert get(client, "/ark:/61220/utsc1/page-2")["Location"] == "https://example.org/h"


def test_normalising_never_walks_up_the_hierarchy(client, ark):
    # /page-3 normalises to /page3, which has nothing bound: still a 404, not
    # the parent's URL. Exact qualifier matching is the legacy contract.
    assert get(client, "/ark:/61220/utsc1/page-3").status_code == 404
    assert get(client, "/ark:/61220/utsc1/page3.").status_code == 404


def test_an_unknown_ark_is_still_not_found(client, ark):
    assert get(client, "/ark:/61220/utsc-9").status_code == 404
    assert get(client, "/ark:/61220/utsc9.").status_code == 404


def test_the_hit_is_counted_against_the_qualifier_that_resolved(client, ark):
    get(client, "/ark:/61220/utsc1/page-2")
    get(client, "/ark:/61220/utsc-1.")
    flush_counters()
    assert Resolution.objects.get(ark=ark, qualifier="/page2").count == 1
    assert Resolution.objects.get(ark=ark, qualifier="").count == 1
    assert not Resolution.objects.filter(qualifier__contains="-").exists()


def test_an_exact_redirect_still_costs_two_reads(client, ark):
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    with CaptureQueriesContext(connection) as captured:
        get(client, "/ARK:/61220/utsc1/page2")
    selects = [q for q in captured.captured_queries if q["sql"].lower().startswith("select")]
    assert len(selects) <= 2


def test_inflections_resolve_the_normalised_form(client, ark):
    response = get(client, "/ark:/61220/utsc-1.?")
    assert response.status_code == 200
    assert "Who: UTSC Library" in response.content.decode()

    response = get(client, "/ark:/61220/utsc1/page-2??")
    assert response.status_code == 200
    assert "What: Page two" in response.content.decode()


def test_an_inflection_on_an_exact_ark_is_unchanged(client, ark):
    # An exact ARK with nothing at the named qualifier answered with an empty
    # record before this change, and still does.
    response = get(client, "/ark:/61220/utsc1/nothing?")
    assert response.status_code == 200
    assert response.content.decode() == "erc:\n"


def test_manifest_resolves_the_normalised_form(client, ark, monkeypatch):
    fetched = []

    def fake_fetch(url):
        fetched.append(url)
        return b'{"ok": true}'

    monkeypatch.setattr("resolver.views.fetch_json", fake_fetch)
    response = get(client, "/ark:/61220/utsc-1/page2/manifest")
    assert response.status_code == 200
    assert fetched == ["https://example.org/p2"]


# --- row 3: nothing new is stored with a hyphen ---------------------------


def test_bind_refuses_a_hyphen_in_a_qualifier(ark):
    with pytest.raises(ValidationError, match="(?i)hyphen"):
        bind_element(ark, "URL", "https://example.org/x", "/page-3")
    assert not Binding.objects.filter(qualifier="/page-3").exists()


def test_bind_still_allows_a_hyphen_in_a_value_or_an_element_name(ark):
    bind_element(ark, "SOURCE-ID", "a-b-c", "/page3")
    assert Binding.objects.get(qualifier="/page3", name="SOURCE-ID").value == "a-b-c"


def test_an_existing_hyphenated_qualifier_can_still_be_unbound(ark):
    Binding.objects.create(ark=ark, qualifier="/page-9", name="URL", value="https://x.example")
    assert unbind_elements(ark, qualifier="/page-9") == 1


def test_the_bind_command_refuses_a_hyphen_in_a_qualifier(ark):
    with pytest.raises(CommandError, match="(?i)hyphen"):
        call_command(
            "bind", "61220/utsc1/page-3", "URL", "https://example.org/x", stdout=io.StringIO()
        )


def test_the_ark_page_refuses_a_hyphen_in_a_qualifier(django_user_model, client, ark):
    ensure_groups()
    user = django_user_model.objects.create_user("editor", password="pw")
    set_role(user, EDITOR)
    client.force_login(user)

    response = client.post(
        reverse("admin_ui:ark_detail", args=[ark.pk]),
        {"action": "bind", "name": "URL", "value": "https://example.org/x", "qualifier": "/p-3"},
        follow=True,
    )
    assert "hyphen" in response.content.decode().lower()
    assert not Binding.objects.filter(qualifier="/p-3").exists()


def test_bulk_bind_refuses_a_hyphen_in_a_qualifier(collection, ark):
    result = apply_csv(
        collection,
        io.StringIO(
            "Ark_ID,URL\n61220/utsc1/page3,https://example.org/3\n"
            "61220/utsc1/page-4,https://example.org/4\n"
        ),
    )
    assert result.failed == 1
    assert "hyphen" in result.errors[0].message.lower()
    assert not Binding.objects.filter(qualifier__in=["/page3", "/page-4"]).exists()


def test_the_collection_form_refuses_a_hyphen_in_the_prefix(django_user_model, client):
    ensure_groups()
    user = django_user_model.objects.create_user("boss", password="pw")
    set_role(user, ADMIN)
    client.force_login(user)

    response = client.post(
        reverse("admin_ui:collection_create"),
        {
            "name": "Maps",
            "prefix": "utsc-maps",
            "naan": "61220",
            "naa": "",
            "template": ".zd",
            "term": "medium",
        },
    )
    assert response.status_code == 200
    assert "hyphen" in response.content.decode().lower()
    assert not Collection.objects.filter(name="Maps").exists()


def test_createcollection_refuses_a_hyphen_in_the_prefix():
    with pytest.raises(CommandError, match="(?i)hyphen"):
        call_command(
            "createcollection",
            "Maps",
            "--prefix",
            "utsc-maps",
            "--naan",
            "61220",
            "--template",
            ".zd",
            stdout=io.StringIO(),
        )
    assert not Collection.objects.exists()


def test_an_existing_hyphenated_prefix_does_not_block_editing_the_collection(
    django_user_model, client
):
    # Imported legacy collections are kept as they are; only new ones are held
    # to the rule.
    legacy = Collection.objects.create(name="Old", prefix="old-x", naan="61220", template=".zd")
    ensure_groups()
    user = django_user_model.objects.create_user("boss", password="pw")
    set_role(user, ADMIN)
    client.force_login(user)

    client.post(reverse("admin_ui:collection_detail", args=[legacy.pk]), {"name": "Renamed"})
    legacy.refresh_from_db()
    assert legacy.name == "Renamed"
