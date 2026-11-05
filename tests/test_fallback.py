"""
Operator-supplied landing and error pages.

Files in FALLBACK_PAGES_DIR replace Django's bare pages; with the setting empty
nothing changes. Pages are served as they are with the real status, except that
index.html may carry three placeholders. Assets beside them are served under
/fallback/ with a short allow-list and no way out of the directory. Staff who
are refused a page stay inside the staff shell.
"""

import os
from pathlib import Path

import pytest
from django.test import RequestFactory
from django.urls import reverse

from admin_ui.roles import ADMIN, EDITOR, VIEWER, ensure_groups, set_role
from core.models import Ark, Collection, Organisation
from resolver import fallback

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _fresh_cache():
    fallback.clear_cache()
    yield
    fallback.clear_cache()


@pytest.fixture
def pages(settings, tmp_path):
    (tmp_path / "index.html").write_text(
        "<h1>{{organisation_name}}</h1><p>{{ organisation_website }}</p>{{naa_table}}<em>end</em>"
    )
    (tmp_path / "403.html").write_text("<p>public forbidden</p>")
    (tmp_path / "404.html").write_text("<p>our 404</p>")
    (tmp_path / "500.html").write_text("<p>our 500</p>")
    (tmp_path / "style.css").write_text("body{color:red}")
    (tmp_path / "logo.svg").write_text("<svg/>")
    (tmp_path / "notes.txt").write_text("not served")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "deep.css").write_text("x")
    settings.FALLBACK_PAGES_DIR = str(tmp_path)
    return tmp_path


@pytest.fixture
def collection():
    return Collection.objects.create(
        name="UTSC", prefix="utsc", naan="61220", naa="UTSC Library", template=".zd"
    )


@pytest.fixture
def make_user(django_user_model):
    def _make(username, role=None, superuser=False):
        ensure_groups()
        user = django_user_model.objects.create_user(
            username, password="pw", is_superuser=superuser, is_staff=superuser
        )
        if role:
            set_role(user, role)
        return user

    return _make


# --- off by default ----------------------------------------------------------


def test_nothing_changes_while_the_setting_is_empty(client, settings, collection):
    settings.FALLBACK_PAGES_DIR = ""
    assert b"Name assigning authorities" in client.get("/").content
    response = client.get("/ark:/61220/nope")
    assert response.status_code == 404
    assert b"our 404" not in response.content


# --- the landing page --------------------------------------------------------------


def test_the_landing_page_comes_from_the_file(client, pages, collection):
    Organisation.load()
    org = Organisation.load()
    org.name, org.website = "The <Library>", "https://library.example"
    org.save()
    body = client.get("/").content.decode()
    assert "<h1>The &lt;Library&gt;</h1>" in body
    assert "<p>https://library.example</p>" in body
    assert "<code>61220</code></td><td>UTSC Library</td>" in body
    assert "<em>end</em>" in body
    assert "{{" not in body


def test_a_naming_authority_cannot_inject_markup(client, pages):
    Collection.objects.create(name="X", prefix="x", naan="99999", naa="<b>bold</b>", template=".zd")
    body = client.get("/").content.decode()
    assert "&lt;b&gt;bold&lt;/b&gt;" in body and "<b>bold</b>" not in body


def test_a_landing_page_without_placeholders_is_served_untouched(client, pages):
    (pages / "index.html").write_bytes(b"<p>plain {{ not_a_placeholder }}</p>")
    fallback.clear_cache()
    assert client.get("/").content == b"<p>plain {{ not_a_placeholder }}</p>"


def test_placeholders_are_empty_when_the_query_fails(pages, monkeypatch):
    import core.models as models

    monkeypatch.setattr(models.Organisation, "load", classmethod(lambda cls: 1 / 0))
    body = fallback.landing_page().decode()
    assert "<h1></h1>" in body


def test_the_landing_page_allows_inline_styles_only(client, pages, collection):
    policy = client.get("/")["Content-Security-Policy"]
    assert "style-src 'self' 'unsafe-inline'" in policy
    assert "script-src 'self';" in policy
    assert "img-src 'self' data:;" in policy


# --- error pages -------------------------------------------------------------------


def test_an_unknown_ark_gets_the_404_page_with_status_404(client, pages, collection):
    response = client.get("/ark:/61220/nope")
    assert response.status_code == 404
    assert response.content == b"<p>our 404</p>"
    assert response["Content-Type"].startswith("text/html")


def test_an_unbound_ark_gets_the_404_page_and_is_not_counted(
    client, pages, collection, counter_redis
):
    Ark.objects.create(collection=collection, identifier="utsc0", sequence=0)
    response = client.get("/ark:/61220/utsc0")
    assert response.status_code == 404
    assert response.content == b"<p>our 404</p>"
    assert counter_redis.hgetall("arks:hits") == {}


def test_an_unknown_path_gets_the_404_page(client, pages):
    response = client.get("/no/such/page")
    assert response.status_code == 404 and response.content == b"<p>our 404</p>"


def test_the_500_page_reads_a_file_and_nothing_else(pages, django_assert_num_queries):
    request = RequestFactory().get("/anything")
    with django_assert_num_queries(0):
        response = fallback.server_error(request)
    assert response.status_code == 500 and response.content == b"<p>our 500</p>"


def test_the_500_handler_is_wired(settings):
    from importlib import import_module

    urlconf = import_module(settings.ROOT_URLCONF)
    assert urlconf.handler500 == "resolver.fallback.server_error"
    assert urlconf.handler404 == "resolver.fallback.page_not_found"
    assert urlconf.handler403 == "resolver.fallback.permission_denied"


def test_without_a_500_file_django_s_default_is_used(settings, tmp_path):
    settings.FALLBACK_PAGES_DIR = str(tmp_path)
    response = fallback.server_error(RequestFactory().get("/"))
    assert response.status_code == 500 and b"our 500" not in response.content


def test_a_public_403_gets_the_403_page(pages):
    request = RequestFactory().get("/admin/login/")
    request.user = type("Anon", (), {"is_authenticated": False})()
    response = fallback.permission_denied(request, Exception("nope"))
    assert response.status_code == 403 and response.content == b"<p>public forbidden</p>"


def test_a_csrf_failure_gets_the_public_403_page(pages):
    from django.test import Client

    strict = Client(enforce_csrf_checks=True)
    response = strict.post(reverse("admin_ui:login"), {"username": "x", "password": "y"})
    assert response.status_code == 403
    assert response.content == b"<p>public forbidden</p>"


def test_a_csrf_failure_without_the_directory_is_django_s_page(settings):
    from django.test import Client

    settings.FALLBACK_PAGES_DIR = ""
    strict = Client(enforce_csrf_checks=True)
    response = strict.post(reverse("admin_ui:login"), {"username": "x", "password": "y"})
    assert response.status_code == 403
    assert b"CSRF" in response.content


def test_a_staff_403_stays_in_the_shell_with_the_role_message(client, pages, make_user, collection):
    client.force_login(make_user("vw", VIEWER))
    response = client.get(reverse("admin_ui:mint", args=[collection.pk]))
    body = response.content.decode()
    assert response.status_code == 403
    assert "public forbidden" not in body
    assert "This needs the Editor role; yours is Viewer." in body
    assert 'class="sidebar"' in body
    assert reverse("admin_ui:collection_list") in body


def test_a_staff_403_without_the_directory_is_still_in_the_shell(
    client, settings, make_user, collection
):
    settings.FALLBACK_PAGES_DIR = ""
    client.force_login(make_user("vw", VIEWER))
    body = client.get(reverse("admin_ui:mint", args=[collection.pk])).content.decode()
    assert "This needs the Editor role" in body and 'class="sidebar"' in body


def test_the_shell_403_carries_no_inline_style(client, pages, make_user, collection):
    client.force_login(make_user("vw", VIEWER))
    body = client.get(reverse("admin_ui:mint", args=[collection.pk])).content.decode()
    assert "style=" not in body and "onclick" not in body


# --- the file cache ------------------------------------------------------------------


def test_an_edit_is_seen_once_the_cache_expires(pages, monkeypatch):
    assert fallback.page("404") == b"<p>our 404</p>"
    (pages / "404.html").write_text("<p>changed</p>")
    os.utime(pages / "404.html", (1, 1))  # a clearly different mtime
    assert fallback.page("404") == b"<p>our 404</p>"  # within the cache window
    monkeypatch.setattr(fallback, "CACHE_SECONDS", 0)
    assert fallback.page("404") == b"<p>changed</p>"


def test_a_file_added_later_is_picked_up(settings, tmp_path, monkeypatch):
    settings.FALLBACK_PAGES_DIR = str(tmp_path)
    assert fallback.page("404") is None
    (tmp_path / "404.html").write_text("<p>now</p>")
    monkeypatch.setattr(fallback, "CACHE_SECONDS", 0)
    assert fallback.page("404") == b"<p>now</p>"


def test_an_unreadable_file_falls_back_quietly(pages, caplog):
    path = pages / "404.html"
    path.chmod(0)
    try:
        if os.access(path, os.R_OK):
            pytest.skip("running as a user who can read anything")
        assert fallback.page("404") is None
    finally:
        path.chmod(0o644)


# --- assets ---------------------------------------------------------------------------


def test_assets_beside_the_pages_are_served(client, pages):
    response = client.get("/fallback/style.css")
    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/css")
    assert response["Cache-Control"] == "public, max-age=3600"
    assert b"".join(response.streaming_content) == b"body{color:red}"
    assert client.get("/fallback/logo.svg")["Content-Type"].startswith("image/svg")


@pytest.mark.parametrize(
    "name",
    [
        "notes.txt",
        "index.html",
        "404.html",
        "missing.css",
        "sub",
        "deep.css",
        ".env",
        "style.css.bak",
    ],
)
def test_anything_else_is_not_found(client, pages, name):
    assert client.get(f"/fallback/{name}").status_code == 404


def test_traversal_is_not_found(client, pages):
    assert client.get("/fallback/..%2F.env").status_code == 404
    assert client.get("/fallback/sub%2Fdeep.css").status_code == 404


def test_a_symlink_out_of_the_directory_is_not_found(client, pages, tmp_path_factory):
    outside = tmp_path_factory.mktemp("outside") / "secret.css"
    outside.write_text("secret")
    (pages / "link.css").symlink_to(outside)
    assert client.get("/fallback/link.css").status_code == 404


def test_assets_are_off_with_the_setting_empty(client, settings):
    settings.FALLBACK_PAGES_DIR = ""
    assert client.get("/fallback/style.css").status_code == 404


def test_asset_path_refuses_what_is_not_a_bare_filename(pages):
    for bad in ("", "/etc/passwd", "a/b.css", "../x.css", "404.html", "x.html", "x"):
        assert fallback.asset_path(bad) is None


# --- the superuser card and preview ---------------------------------------------------


def test_active_lists_every_page_and_whether_it_is_there(pages):
    rows = {row["key"]: row["present"] for row in fallback.active()}
    assert rows == {"index": True, "403": True, "404": True, "500": True, "503": False}


def test_active_with_the_setting_empty_shows_nothing_present(settings):
    settings.FALLBACK_PAGES_DIR = ""
    assert not any(row["present"] for row in fallback.active())


def test_a_superuser_sees_the_card_and_an_admin_does_not(client, pages, make_user):
    client.force_login(make_user("adm", ADMIN))
    assert "Fallback pages" not in client.get(reverse("admin_ui:user_list")).content.decode()
    client.force_login(make_user("root", superuser=True))
    body = client.get(reverse("admin_ui:user_list")).content.decode()
    assert "Fallback pages" in body
    assert str(pages) in body
    assert reverse("fallback_preview", args=["404"]) in body
    assert "503.html" in body


def test_the_card_says_when_the_feature_is_off(client, settings, make_user):
    settings.FALLBACK_PAGES_DIR = ""
    client.force_login(make_user("root", superuser=True))
    assert "Not configured" in client.get(reverse("admin_ui:user_list")).content.decode()


def test_preview_serves_a_page_with_status_200(client, pages, make_user, collection):
    client.force_login(make_user("root", superuser=True))
    response = client.get(reverse("fallback_preview", args=["404"]))
    assert response.status_code == 200 and response.content == b"<p>our 404</p>"
    index = client.get(reverse("fallback_preview", args=["index"]))
    assert index.status_code == 200 and b"UTSC Library" in index.content


def test_preview_404s_a_missing_page_or_an_unknown_key(client, pages, make_user):
    client.force_login(make_user("root", superuser=True))
    assert client.get(reverse("fallback_preview", args=["503"])).status_code == 404
    assert client.get("/fallback/preview/418/").status_code == 404


def test_preview_is_for_superusers_only(client, pages, make_user):
    assert client.get(reverse("fallback_preview", args=["404"])).status_code == 302
    client.force_login(make_user("adm", ADMIN))
    assert client.get(reverse("fallback_preview", args=["404"])).status_code == 403
    client.force_login(make_user("ed", EDITOR))
    assert client.get(reverse("fallback_preview", args=["404"])).status_code == 403


def test_the_example_kit_ships_with_the_application():
    kit = Path(__file__).resolve().parent.parent / "docs" / "fallback-example"
    for name in ("index.html", "403.html", "404.html", "500.html", "style.css", "README.md"):
        assert (kit / name).is_file(), name
    index = (kit / "index.html").read_text()
    for token in ("{{organisation_name}}", "{{organisation_website}}", "{{naa_table}}"):
        assert token in index
    for name in ("403.html", "404.html", "500.html"):
        assert "{{" not in (kit / name).read_text(), f"{name} must be static"
