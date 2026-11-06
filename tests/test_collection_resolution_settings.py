"""
Per-collection resolution settings: which elements hold the redirect URL, and
which qualifier suffixes are proxied as JSON instead of redirected.

Both used to be hard-coded (``URL`` then ``WHERE?``; ``/manifest``). They are
the collection owner's decision, so they are settings on the collection, set
when it is created and changed afterwards only by an admin who has seen what
the change would touch. The defaults reproduce the legacy service exactly.

The suffix setting also fixes R0: legacy answered ``…/manifest`` by proxying
the URL bound *at the qualifier* ``/manifest`` (a pre-generated IIIF manifest);
this system used to proxy the object's own URL instead. See
INTENTS_collection_resolution_settings.md.
"""

import io
import logging

import pytest
from django.core.exceptions import ValidationError
from django.core.management import CommandError, call_command
from django.urls import reverse

from admin_ui.roles import ADMIN, EDITOR, ensure_groups, set_role
from core.arkpath import parse_ark_path
from core.counters import flush_counters
from core.models import Ark, Binding, Collection, Resolution
from core.services import (
    parse_proxied_suffixes,
    parse_redirect_elements,
    resolution_impact,
    update_resolution_settings,
)
from core.verify import iter_check_paths
from jobs.bulkbind import template_csv

pytestmark = pytest.mark.django_db


@pytest.fixture
def collection():
    return Collection.objects.create(
        name="UTSC", prefix="utsc", naan="61220", naa="UTSC Library", template=".zd"
    )


@pytest.fixture
def ark(collection):
    return Ark.objects.create(collection=collection, identifier="utsc1", sequence=1)


def bind(ark, qualifier="", **elements):
    for name, value in elements.items():
        Binding.objects.create(
            ark=ark, qualifier=qualifier, name=name.replace("_Q", "?"), value=value
        )


def get(client, path):
    """Issue a request, preserving the raw URI so a trailing '?' survives."""
    return client.get(path, RAW_URI=path)


@pytest.fixture
def fetched(monkeypatch):
    """Fake the manifest fetch and record which URL was asked for."""
    seen = []

    def fake_fetch(url):
        seen.append(url)
        return b'{"type": "Manifest"}'

    monkeypatch.setattr("resolver.views.fetch_json", fake_fetch)
    return seen


def configure(collection, elements=None, suffixes=None):
    if elements is not None:
        collection.redirect_elements = elements
    if suffixes is not None:
        collection.proxied_suffixes = suffixes
    collection.save()


# --- defaults -------------------------------------------------------------


def test_a_new_collection_has_the_legacy_defaults(collection):
    collection.refresh_from_db()
    assert collection.redirect_element_list == ["URL", "WHERE?"]
    assert collection.proxied_suffix_list == ["manifest"]
    assert collection.resolution_changed_at is None
    assert collection.resolution_changed_by is None


# --- parsing and validation -----------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("URL,WHERE?", ["URL", "WHERE?"]),
        (" url , where? ", ["URL", "WHERE?"]),
        ("TARGET", ["TARGET"]),
        ("URL, URL, PID", ["URL", "PID"]),
    ],
)
def test_redirect_elements_are_normalised(text, expected):
    assert parse_redirect_elements(text) == expected


@pytest.mark.parametrize("text", ["", " , ", "A,B,C,D,E,F"])
def test_redirect_elements_need_one_to_five_names(text):
    with pytest.raises(ValidationError):
        parse_redirect_elements(text)


@pytest.mark.parametrize(
    ("text", "expected"),
    [("manifest", ["manifest"]), ("manifest, iiif", ["manifest", "iiif"]), ("", []), (" ", [])],
)
def test_proxied_suffixes_are_parsed(text, expected):
    assert parse_proxied_suffixes(text) == expected


@pytest.mark.parametrize(
    "text", ["a/b", "info.json", "iiif-v3", "1manifest", "_x", "x?", "x#", "x%2F", "manifest,,x/y"]
)
def test_a_suffix_must_be_a_plain_segment(text):
    with pytest.raises(ValidationError):
        parse_proxied_suffixes(text)


def test_suffixes_keep_their_case():
    assert parse_proxied_suffixes("Manifest") == ["Manifest"]


# --- redirect elements ----------------------------------------------------


def test_the_default_redirects_to_url_then_where(client, ark):
    bind(ark, WHERE_Q="https://example.org/where")
    assert get(client, "/ark:/61220/utsc1")["Location"] == "https://example.org/where"
    bind(ark, URL="https://example.org/url")
    assert get(client, "/ark:/61220/utsc1")["Location"] == "https://example.org/url"


def test_a_custom_element_is_used_and_url_ignored(client, collection, ark):
    configure(collection, elements="TARGET")
    bind(ark, URL="https://example.org/url", TARGET="https://example.org/target")
    assert get(client, "/ark:/61220/utsc1")["Location"] == "https://example.org/target"

    Binding.objects.filter(name="TARGET").delete()
    assert get(client, "/ark:/61220/utsc1").status_code == 404


def test_the_order_of_the_list_decides(client, collection, ark):
    configure(collection, elements="WHERE?,URL")
    bind(ark, URL="https://example.org/url", WHERE_Q="https://example.org/where")
    assert get(client, "/ark:/61220/utsc1")["Location"] == "https://example.org/where"


def test_an_empty_value_falls_through_to_the_next_element(client, collection, ark):
    configure(collection, elements="TARGET,URL")
    bind(ark, TARGET="", URL="https://example.org/url")
    assert get(client, "/ark:/61220/utsc1")["Location"] == "https://example.org/url"


def test_the_setting_applies_at_every_qualifier(client, collection, ark):
    configure(collection, elements="TARGET")
    bind(ark, "/page2", URL="https://example.org/u2", TARGET="https://example.org/t2")
    assert get(client, "/ark:/61220/utsc1/page2")["Location"] == "https://example.org/t2"


def test_settings_are_per_collection(client, collection, ark):
    other = Collection.objects.create(
        name="Maps", prefix="map", naan="61220", template=".zd", redirect_elements="TARGET"
    )
    map1 = Ark.objects.create(collection=other, identifier="map1", sequence=1)
    bind(map1, URL="https://example.org/map-url", TARGET="https://example.org/map-target")
    bind(ark, URL="https://example.org/url", TARGET="https://example.org/target")

    assert get(client, "/ark:/61220/map1")["Location"] == "https://example.org/map-target"
    assert get(client, "/ark:/61220/utsc1")["Location"] == "https://example.org/url"


def test_a_redirect_still_costs_two_reads(client, collection, ark):
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    configure(collection, elements="TARGET,URL")
    bind(ark, URL="https://example.org/url")
    with CaptureQueriesContext(connection) as captured:
        assert get(client, "/ark:/61220/utsc1")["Location"] == "https://example.org/url"
    selects = [q for q in captured.captured_queries if q["sql"].lower().startswith("select")]
    assert len(selects) <= 2


def test_the_normalisation_fallbacks_still_apply(client, collection, ark):
    configure(collection, elements="TARGET")
    bind(ark, "/page2", TARGET="https://example.org/t2")
    assert get(client, "/ark:/61220/utsc-1/page-2.")["Location"] == "https://example.org/t2"


# --- proxied suffixes (R0) ------------------------------------------------


def test_manifest_proxies_the_url_bound_at_manifest(client, ark, fetched):
    # The legacy behaviour R0 restores: a pre-generated manifest at /manifest,
    # the object's HTML page at "".
    bind(ark, URL="http://ecn.example/61220/utsc1")
    bind(ark, "/manifest", URL="https://ecn.example/node/1/book-manifest-pregen")

    response = get(client, "/ark:/61220/utsc1/manifest")

    assert response.status_code == 200
    assert response["Content-Type"] == "application/json"
    assert fetched == ["https://ecn.example/node/1/book-manifest-pregen"]


def test_manifest_falls_back_to_the_objects_own_url(client, ark, fetched):
    bind(ark, URL="https://example.org/1.json")
    assert get(client, "/ark:/61220/utsc1/manifest").status_code == 200
    assert fetched == ["https://example.org/1.json"]


def test_manifest_with_nothing_bound_is_not_found(client, ark, fetched):
    bind(ark, TITLE="no url")
    assert get(client, "/ark:/61220/utsc1/manifest").status_code == 404
    assert fetched == []


def test_manifest_of_a_part(client, ark, fetched):
    bind(ark, "/page2", URL="https://example.org/p2")
    assert get(client, "/ark:/61220/utsc1/page2/manifest").status_code == 200
    bind(ark, "/page2/manifest", URL="https://example.org/p2/manifest.json")
    assert get(client, "/ark:/61220/utsc1/page2/manifest").status_code == 200
    assert fetched == ["https://example.org/p2", "https://example.org/p2/manifest.json"]


def test_manifest_uses_the_collections_redirect_elements(client, collection, ark, fetched):
    configure(collection, elements="IIIF")
    bind(ark, "/manifest", URL="https://example.org/ignored", IIIF="https://example.org/m.json")
    get(client, "/ark:/61220/utsc1/manifest")
    assert fetched == ["https://example.org/m.json"]


def test_a_custom_suffix_is_proxied_and_manifest_becomes_an_ordinary_qualifier(
    client, collection, ark, fetched
):
    configure(collection, suffixes="iiif")
    bind(ark, "/iiif", URL="https://example.org/iiif.json")
    bind(ark, "/manifest", URL="https://example.org/manifest-page")

    assert get(client, "/ark:/61220/utsc1/iiif").status_code == 200
    assert fetched == ["https://example.org/iiif.json"]

    response = get(client, "/ark:/61220/utsc1/manifest")
    assert response.status_code == 302
    assert response["Location"] == "https://example.org/manifest-page"


def test_with_no_suffixes_manifest_is_an_ordinary_qualifier(client, collection, ark, fetched):
    configure(collection, suffixes="")
    bind(ark, URL="https://example.org/1")
    bind(ark, "/manifest", URL="https://example.org/m.json")

    response = get(client, "/ark:/61220/utsc1/manifest")
    assert response.status_code == 302
    assert response["Location"] == "https://example.org/m.json"
    assert fetched == []


def test_a_suffix_is_matched_on_the_last_segment_only(client, ark, fetched):
    bind(ark, "/manifest/page2", URL="https://example.org/mp2")
    response = get(client, "/ark:/61220/utsc1/manifest/page2")
    assert response.status_code == 302
    assert fetched == []


def test_the_normalisation_fallbacks_apply_to_a_proxied_suffix(client, ark, fetched):
    bind(ark, "/manifest", URL="https://example.org/m.json")
    assert get(client, "/ark:/61220/utsc-1/manifest").status_code == 200
    assert get(client, "/ark:/61220/utsc1/manifest.").status_code == 200
    assert fetched == ["https://example.org/m.json", "https://example.org/m.json"]


def test_an_inflection_on_manifest_shows_the_manifest_qualifiers_metadata(client, ark, fetched):
    # Legacy built the qualifier from every path part, so 'manifest?' described
    # the /manifest qualifier, not the object.
    bind(ark, URL="https://example.org/1", TITLE="The object")
    bind(ark, "/manifest", URL="https://example.org/m.json", FORMAT="IIIF 3")

    body = get(client, "/ark:/61220/utsc1/manifest?").content.decode()

    assert "Format: IIIF 3" in body
    assert "The object" not in body
    assert fetched == []


def test_a_proxied_request_is_not_counted(client, ark, fetched):
    bind(ark, "/manifest", URL="https://example.org/m.json")
    get(client, "/ark:/61220/utsc1/manifest")
    flush_counters()
    assert not Resolution.objects.exists()


def test_the_parser_no_longer_strips_manifest():
    parsed = parse_ark_path("ark:/61220/utsc1/page2/manifest")
    assert parsed.qualifier == "/page2/manifest"
    assert parsed.last_segment == "manifest"
    assert parsed.parent_qualifier == "/page2"
    bare = parse_ark_path("ark:/61220/utsc1")
    assert (bare.last_segment, bare.parent_qualifier) == ("", "")


def test_resolve_diff_checks_manifest_for_arks_that_bind_it(collection, ark):
    bind(ark, "/manifest", URL="https://example.org/m.json")
    assert "/ark:/61220/utsc1/manifest" in set(iter_check_paths(inflections=False))


# --- the write path -------------------------------------------------------


def test_impact_counts_what_each_element_and_suffix_touches(collection, ark):
    bind(ark, URL="https://example.org/1", WHERE_Q="https://example.org/w")
    bind(ark, "/p1", URL="https://example.org/p1")
    bind(ark, "/manifest", URL="https://example.org/m.json")

    impact = resolution_impact(collection, ["TARGET", "URL"], ["iiif"])

    assert impact["elements"] == {"URL": 3, "WHERE?": 1, "TARGET": 0}
    assert impact["suffixes"] == {"manifest": 1, "iiif": 0}
    assert any("TARGET" in warning for warning in impact["warnings"])
    assert any("WHERE?" in warning for warning in impact["warnings"])
    assert any("manifest" in warning for warning in impact["warnings"])


def test_an_update_is_stamped_and_logged(collection, django_user_model, caplog):
    user = django_user_model.objects.create_user("boss", password="pw")
    with caplog.at_level(logging.WARNING, logger="core.services"):
        update_resolution_settings(collection, ["TARGET", "URL"], ["manifest", "iiif"], user)

    collection.refresh_from_db()
    assert collection.redirect_element_list == ["TARGET", "URL"]
    assert collection.proxied_suffix_list == ["manifest", "iiif"]
    assert collection.resolution_changed_by == user
    assert collection.resolution_changed_at is not None
    assert "URL,WHERE? -> TARGET,URL" in caplog.text
    assert "manifest -> manifest,iiif" in caplog.text
    assert "boss" in caplog.text


# --- creating a collection ------------------------------------------------


def test_createcollection_takes_both_settings():
    call_command(
        "createcollection",
        "Maps",
        "--prefix",
        "map",
        "--naan",
        "61220",
        "--template",
        ".zd",
        "--redirect-elements",
        "target, url",
        "--proxied-suffixes",
        "manifest,iiif",
        stdout=io.StringIO(),
    )
    maps = Collection.objects.get(prefix="map")
    assert maps.redirect_element_list == ["TARGET", "URL"]
    assert maps.proxied_suffix_list == ["manifest", "iiif"]


def test_createcollection_refuses_a_bad_suffix():
    with pytest.raises(CommandError, match="(?i)suffix"):
        call_command(
            "createcollection",
            "Maps",
            "--prefix",
            "map",
            "--naan",
            "61220",
            "--template",
            ".zd",
            "--proxied-suffixes",
            "iiif-v3",
            stdout=io.StringIO(),
        )
    assert not Collection.objects.exists()


@pytest.fixture
def admin_client(django_user_model, client):
    ensure_groups()
    user = django_user_model.objects.create_user("boss", password="pw")
    set_role(user, ADMIN)
    client.force_login(user)
    client.user = user
    return client


NEW = {
    "name": "Maps",
    "prefix": "map",
    "naan": "61220",
    "naa": "",
    "template": ".zd",
    "term": "medium",
}


def test_the_create_form_offers_the_defaults(admin_client):
    page = admin_client.get(reverse("admin_ui:collection_create")).content.decode()
    assert 'name="redirect_elements"' in page and 'value="URL, WHERE?"' in page
    assert 'name="proxied_suffixes"' in page and 'value="manifest"' in page


def test_the_create_form_saves_both_settings(admin_client):
    response = admin_client.post(
        reverse("admin_ui:collection_create"),
        {**NEW, "redirect_elements": "TARGET", "proxied_suffixes": "iiif"},
    )
    assert response.status_code == 302
    maps = Collection.objects.get(prefix="map")
    assert (maps.redirect_element_list, maps.proxied_suffix_list) == (["TARGET"], ["iiif"])


def test_the_create_form_reports_a_bad_setting(admin_client):
    response = admin_client.post(
        reverse("admin_ui:collection_create"),
        {**NEW, "redirect_elements": "", "proxied_suffixes": "a/b"},
    )
    page = response.content.decode()
    assert response.status_code == 200
    assert "redirect element" in page.lower()
    assert "suffix" in page.lower()
    assert not Collection.objects.filter(prefix="map").exists()


# --- changing them later --------------------------------------------------


def detail(collection):
    return reverse("admin_ui:collection_detail", args=[collection.pk])


def test_the_collection_page_shows_the_settings(admin_client, collection):
    page = admin_client.get(detail(collection)).content.decode()
    assert "Resolution settings" in page
    assert 'value="URL, WHERE?"' in page
    assert 'value="manifest"' in page


def test_a_change_is_previewed_first_and_writes_nothing(admin_client, collection, ark):
    bind(ark, URL="https://example.org/1")
    response = admin_client.post(
        detail(collection),
        {"action": "resolution", "redirect_elements": "TARGET", "proxied_suffixes": "manifest"},
    )
    page = response.content.decode()

    assert response.status_code == 200
    assert "Confirm" in page
    assert "TARGET" in page and "bound nowhere" in page
    collection.refresh_from_db()
    assert collection.redirect_element_list == ["URL", "WHERE?"]


def test_a_confirmed_change_is_saved_and_shown(admin_client, collection):
    response = admin_client.post(
        detail(collection),
        {
            "action": "resolution",
            "redirect_elements": "TARGET, URL",
            "proxied_suffixes": "manifest",
            "confirm": "yes",
        },
        follow=True,
    )
    collection.refresh_from_db()
    assert collection.redirect_element_list == ["TARGET", "URL"]
    assert collection.resolution_changed_by == admin_client.user
    assert "Last changed" in response.content.decode()


def test_an_invalid_change_is_refused_even_when_confirmed(admin_client, collection):
    response = admin_client.post(
        detail(collection),
        {"action": "resolution", "redirect_elements": "", "proxied_suffixes": "", "confirm": "yes"},
        follow=True,
    )
    assert "redirect element" in response.content.decode().lower()
    collection.refresh_from_db()
    assert collection.redirect_element_list == ["URL", "WHERE?"]


def test_an_editor_cannot_change_them(django_user_model, client, collection):
    ensure_groups()
    user = django_user_model.objects.create_user("ed", password="pw")
    set_role(user, EDITOR)
    client.force_login(user)
    response = client.post(
        detail(collection),
        {
            "action": "resolution",
            "redirect_elements": "TARGET",
            "proxied_suffixes": "",
            "confirm": "yes",
        },
    )
    assert response.status_code == 403
    collection.refresh_from_db()
    assert collection.redirect_element_list == ["URL", "WHERE?"]


def test_renaming_still_works_and_leaves_the_settings_alone(admin_client, collection):
    admin_client.post(detail(collection), {"name": "Renamed", "naa": "UTSC Library"})
    collection.refresh_from_db()
    assert collection.name == "Renamed"
    assert collection.resolution_changed_at is None


# --- follow-on uses -------------------------------------------------------


def test_the_bind_template_starts_with_the_collections_redirect_element(collection, ark):
    configure(collection, elements="TARGET,URL")
    header = next(iter(template_csv([ark], collection)))
    assert header[:3] == ["Ark_ID", "TARGET", "URL"]
    assert header.count("URL") == 1


def test_the_default_bind_template_is_unchanged(collection, ark):
    header = next(iter(template_csv([ark], collection)))
    assert header == ["Ark_ID", "URL", "PID", "LOCAL_ID", "COLLECTION"]


def test_the_ark_page_names_the_collections_redirect_elements(admin_client, collection, ark):
    configure(collection, elements="TARGET,URL")
    page = admin_client.get(reverse("admin_ui:ark_detail", args=[ark.pk])).content.decode()
    assert "<code>TARGET</code>, then <code>URL</code>" in page
