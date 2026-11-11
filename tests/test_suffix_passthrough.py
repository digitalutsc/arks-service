"""
Suffix passthrough (R6), a per-collection setting, off by default.

With it on, a part with no URL of its own redirects to its nearest bound
ancestor's URL plus the rest of the path: if utsc1 -> T then utsc1/page7 -> T/page7.
An exact binding always wins, at any reading of the request; passthrough is the
last resort. It is for redirects only, and the hit is counted against the
ancestor that supplied the URL, so made-up paths never create counter rows.

Measured on the imported data: 96.6% of the 248,819 hand-bound part URLs are
exactly what passthrough would produce. See INTENTS_suffix_passthrough.md.
"""

import logging

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from admin_ui.roles import ADMIN, EDITOR, ensure_groups, set_role
from core.counters import flush_counters
from core.models import Ark, Binding, Collection, Resolution
from core.services import resolution_impact, update_resolution_settings

pytestmark = pytest.mark.django_db

BASE = "https://memory.example/61220/utsc1"


@pytest.fixture
def collection():
    return Collection.objects.create(
        name="UTSC",
        prefix="utsc",
        naan="61220",
        naa="UTSC Library",
        template=".zd",
        suffix_passthrough=True,
    )


@pytest.fixture
def ark(collection):
    ark = Ark.objects.create(collection=collection, identifier="utsc1", sequence=1)
    Binding.objects.create(ark=ark, name="URL", value=BASE)
    return ark


def bind(ark, qualifier, name="URL", value="https://example.org/x"):
    Binding.objects.create(ark=ark, qualifier=qualifier, name=name, value=value)


def get(client, path):
    return client.get(path, RAW_URI=path)


def location(client, path):
    response = get(client, path)
    assert response.status_code == 302, (path, response.status_code)
    return response["Location"]


# --- off by default -------------------------------------------------------


def test_it_is_off_for_a_new_collection():
    fresh = Collection.objects.create(name="New", prefix="new", naan="61220", template=".zd")
    fresh.refresh_from_db()
    assert fresh.suffix_passthrough is False


def test_off_keeps_the_legacy_404(client, collection, ark):
    collection.suffix_passthrough = False
    collection.save()
    assert get(client, "/ark:/61220/utsc1/page7").status_code == 404


# --- on -------------------------------------------------------------------


def test_an_unbound_part_passes_through_to_the_objects_url(client, ark):
    assert location(client, "/ark:/61220/utsc1/page7") == f"{BASE}/page7"


def test_a_deep_unbound_part_keeps_its_whole_path(client, ark):
    assert location(client, "/ark:/61220/utsc1/vol2/page7") == f"{BASE}/vol2/page7"


def test_the_nearest_bound_ancestor_is_used(client, ark):
    bind(ark, "/chapter2", value="https://site-b.example/ch2")
    assert location(client, "/ark:/61220/utsc1/chapter2/p5") == "https://site-b.example/ch2/p5"
    assert location(client, "/ark:/61220/utsc1/chapter3/p5") == f"{BASE}/chapter3/p5"


def test_an_exact_binding_always_wins(client, ark):
    bind(ark, "/page7", value="https://elsewhere.example/seven")
    assert location(client, "/ark:/61220/utsc1/page7") == "https://elsewhere.example/seven"


def test_a_normalised_exact_binding_wins_over_passthrough(client, ark):
    bind(ark, "/page7", value="https://elsewhere.example/seven")
    assert location(client, "/ark:/61220/utsc1/page-7") == "https://elsewhere.example/seven"
    assert location(client, "/ark:/61220/utsc-1/page7.") == "https://elsewhere.example/seven"


def test_passthrough_works_through_the_tolerant_readings(client, ark):
    # utsc-1 is no ARK; its normalised reading utsc1 is, and /page8 is unbound.
    assert location(client, "/ark:/61220/utsc-1/page8") == f"{BASE}/page8"


def test_a_trailing_slash_on_the_target_is_not_doubled(client, collection):
    other = Ark.objects.create(collection=collection, identifier="utsc2", sequence=2)
    bind(other, "", value="https://example.org/book/")
    assert location(client, "/ark:/61220/utsc2/page1") == "https://example.org/book/page1"


def test_a_variant_of_a_part_passes_through_as_text(client, ark):
    assert location(client, "/ark:/61220/utsc1/page7.jpg") == f"{BASE}/page7.jpg"


def test_the_appended_path_is_re_encoded(client, ark):
    assert location(client, "/ark:/61220/utsc1/page%207") == f"{BASE}/page%207"
    assert location(client, "/ark:/61220/utsc1/a%3Fb") == f"{BASE}/a%3Fb"
    assert location(client, "/ark:/61220/utsc1/caf%C3%A9") == f"{BASE}/caf%C3%A9"


def test_the_collections_redirect_elements_are_used(client, collection, ark):
    collection.redirect_elements = "TARGET"
    collection.save()
    bind(ark, "", name="TARGET", value="https://target.example/t1")
    assert location(client, "/ark:/61220/utsc1/page7") == "https://target.example/t1/page7"


def test_a_query_string_is_still_dropped(client, ark):
    assert location(client, "/ark:/61220/utsc1/page7?foo=bar") == f"{BASE}/page7"


# --- refused or unchanged -------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "/ark:/61220/utsc1/../admin",
        "/ark:/61220/utsc1/a/../b",
        "/ark:/61220/utsc1/./x",
        "/ark:/61220/utsc1/a%2F..%2Fb",
    ],
)
def test_dot_segments_are_refused(client, ark, path):
    assert get(client, path).status_code == 404


def test_an_ark_with_no_target_is_still_not_found(client, collection):
    Ark.objects.create(collection=collection, identifier="utsc3", sequence=3)
    assert get(client, "/ark:/61220/utsc3/page1").status_code == 404


def test_an_unknown_ark_is_still_not_found(client, ark):
    assert get(client, "/ark:/61220/utsc9/page1").status_code == 404


def test_an_unbound_object_variant_is_still_not_found(client, ark):
    # Passthrough is for hierarchy parts; a variant of the object has no path to pass.
    assert get(client, "/ark:/61220/utsc1.image.png").status_code == 404


def test_metadata_on_an_unbound_part_is_unchanged(client, ark):
    response = get(client, "/ark:/61220/utsc1/page7?")
    assert response.status_code == 200
    assert response.content.decode() == "erc:\n"


def test_a_proxied_suffix_does_not_pass_through(client, ark, monkeypatch):
    fetched = []
    monkeypatch.setattr("resolver.views.fetch_json", lambda url: fetched.append(url) or b"{}")
    # Nothing at /page7/manifest or /page7: 404, not a fetch of BASE/page7.
    assert get(client, "/ark:/61220/utsc1/page7/manifest").status_code == 404
    assert fetched == []


def test_other_collections_are_unaffected(client, ark):
    off = Collection.objects.create(name="Maps", prefix="map", naan="61220", template=".zd")
    map1 = Ark.objects.create(collection=off, identifier="map1", sequence=1)
    bind(map1, "", value="https://maps.example/1")
    assert get(client, "/ark:/61220/map1/page1").status_code == 404
    assert location(client, "/ark:/61220/utsc1/page1") == f"{BASE}/page1"


# --- counting -------------------------------------------------------------


def test_a_passthrough_hit_counts_against_the_ancestor(client, ark):
    bind(ark, "/chapter2", value="https://site-b.example/ch2")
    get(client, "/ark:/61220/utsc1/page7")
    get(client, "/ark:/61220/utsc1/page8")
    get(client, "/ark:/61220/utsc1/chapter2/p5")
    flush_counters()
    counts = dict(Resolution.objects.filter(ark=ark).values_list("qualifier", "count"))
    assert counts == {"": 2, "/chapter2": 1}


# --- cost -----------------------------------------------------------------


def selects(client, path):
    with CaptureQueriesContext(connection) as captured:
        get(client, path)
    return [q for q in captured.captured_queries if q["sql"].lower().startswith("select")]


def test_an_exact_redirect_still_costs_two_reads(client, ark):
    assert len(selects(client, "/ark:/61220/utsc1")) <= 2


def test_a_passthrough_redirect_costs_one_more_read(client, ark):
    assert len(selects(client, "/ark:/61220/utsc1/a/b/c/d/e/f")) <= 3


# --- the write path -------------------------------------------------------


def test_impact_explains_turning_it_on(collection, ark):
    collection.suffix_passthrough = False
    collection.save()
    bind(ark, "/p1")
    bind(ark, "/p2")
    impact = resolution_impact(
        collection, collection.redirect_element_list, collection.proxied_suffix_list, True
    )
    assert impact["passthrough"] == {"arks_with_target": 1, "part_bindings": 2}
    assert any("1 ARK" in w and "not found" in w for w in impact["warnings"])


def test_impact_explains_turning_it_off(collection, ark):
    impact = resolution_impact(
        collection, collection.redirect_element_list, collection.proxied_suffix_list, False
    )
    assert any("404" in w for w in impact["warnings"])


def test_an_update_saves_and_logs_it(collection, django_user_model, caplog):
    collection.suffix_passthrough = False
    collection.save()
    user = django_user_model.objects.create_user("boss", password="pw")
    with caplog.at_level(logging.WARNING, logger="core.services"):
        update_resolution_settings(
            collection,
            collection.redirect_element_list,
            collection.proxied_suffix_list,
            user,
            passthrough=True,
        )
    collection.refresh_from_db()
    assert collection.suffix_passthrough is True
    assert collection.resolution_changed_by == user
    assert "suffix passthrough off -> on" in caplog.text


def test_an_update_without_it_leaves_it_alone(collection):
    update_resolution_settings(collection, ["URL"], ["manifest"])
    collection.refresh_from_db()
    assert collection.suffix_passthrough is True


# --- staff side -----------------------------------------------------------


@pytest.fixture
def admin_client(django_user_model, client):
    ensure_groups()
    user = django_user_model.objects.create_user("boss", password="pw")
    set_role(user, ADMIN)
    client.force_login(user)
    return client


NEW = {
    "name": "Maps",
    "prefix": "map",
    "naan": "61220",
    "naa": "UTSC Library",
    "template": ".zd",
}


def test_the_create_form_has_it_and_saves_it(admin_client):
    page = admin_client.get(reverse("admin_ui:collection_create")).content.decode()
    assert 'name="suffix_passthrough"' in page
    admin_client.post(
        reverse("admin_ui:collection_create"),
        {**NEW, "suffix_passthrough_present": "1", "suffix_passthrough": "on"},
    )
    assert Collection.objects.get(prefix="map").suffix_passthrough is True


def test_the_create_form_leaves_it_off_when_unticked(admin_client):
    admin_client.post(
        reverse("admin_ui:collection_create"), {**NEW, "suffix_passthrough_present": "1"}
    )
    assert Collection.objects.get(prefix="map").suffix_passthrough is False


def detail(collection):
    return reverse("admin_ui:collection_detail", args=[collection.pk])


SETTINGS = {
    "action": "resolution",
    "redirect_elements": "URL, WHERE?",
    "proxied_suffixes": "manifest",
}


def test_turning_it_on_is_previewed_then_confirmed(admin_client, collection, ark):
    collection.suffix_passthrough = False
    collection.save()
    on = {**SETTINGS, "suffix_passthrough_present": "1", "suffix_passthrough": "on"}

    preview = admin_client.post(detail(collection), on)
    page = preview.content.decode()
    assert preview.status_code == 200
    assert "Suffix passthrough" in page and "Confirm change" in page
    collection.refresh_from_db()
    assert collection.suffix_passthrough is False

    admin_client.post(detail(collection), {**on, "confirm": "yes"})
    collection.refresh_from_db()
    assert collection.suffix_passthrough is True


def test_unticking_turns_it_off(admin_client, collection):
    admin_client.post(
        detail(collection), {**SETTINGS, "suffix_passthrough_present": "1", "confirm": "yes"}
    )
    collection.refresh_from_db()
    assert collection.suffix_passthrough is False


def test_a_form_without_the_field_keeps_it(admin_client, collection):
    admin_client.post(
        detail(collection), {**SETTINGS, "proxied_suffixes": "manifest, iiif", "confirm": "yes"}
    )
    collection.refresh_from_db()
    assert collection.proxied_suffix_list == ["manifest", "iiif"]
    assert collection.suffix_passthrough is True


def test_an_editor_cannot_change_it(django_user_model, client, collection):
    ensure_groups()
    user = django_user_model.objects.create_user("ed", password="pw")
    set_role(user, EDITOR)
    client.force_login(user)
    response = client.post(
        detail(collection), {**SETTINGS, "suffix_passthrough_present": "1", "confirm": "yes"}
    )
    assert response.status_code == 403
    collection.refresh_from_db()
    assert collection.suffix_passthrough is True


def test_the_ark_page_says_when_it_is_on(admin_client, collection, ark):
    page = admin_client.get(reverse("admin_ui:ark_detail", args=[ark.pk])).content.decode()
    assert "nearest bound part" in page
    collection.suffix_passthrough = False
    collection.save()
    page = admin_client.get(reverse("admin_ui:ark_detail", args=[ark.pk])).content.decode()
    assert "nearest bound part" not in page
