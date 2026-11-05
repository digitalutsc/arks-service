"""
Forms that take a moment say so while the browser waits.

Minting runs inside the request (a capped mint is a second or two) and a bulk
bind upload has to arrive before its job page can open. Neither warrants a real
progress bar, but a button that goes quiet with no sign of life gets clicked
twice. The forms carry data-busy; static/js/app.js disables the button, swaps
its label and reveals a hidden indeterminate bar. No inline script or style,
because the CSP forbids both.
"""

from pathlib import Path

import pytest
from django.urls import reverse

from admin_ui.roles import ADMIN, EDITOR, ensure_groups, set_role
from core.models import Collection

pytestmark = pytest.mark.django_db

APP_JS = Path(__file__).resolve().parent.parent / "static" / "js" / "app.js"


@pytest.fixture
def collection():
    return Collection.objects.create(name="UTSC", prefix="utsc", naan="61220", template=".zd")


@pytest.fixture
def editor(django_user_model, client):
    ensure_groups()
    user = django_user_model.objects.create_user("ed", password="pw")
    set_role(user, EDITOR)
    client.force_login(user)
    return client


@pytest.fixture
def admin(django_user_model, client):
    ensure_groups()
    user = django_user_model.objects.create_user("adm", password="pw")
    set_role(user, ADMIN)
    client.force_login(user)
    return client


def test_the_mint_form_announces_itself_as_busy_on_submit(editor, collection):
    body = editor.get(reverse("admin_ui:mint", args=[collection.pk])).content.decode()
    assert 'data-busy="Minting…"' in body
    assert "<progress" in body
    assert 'class="busy" hidden' in body


def test_the_bulk_bind_form_announces_itself_as_busy_on_submit(editor, collection):
    body = editor.get(reverse("admin_ui:bulk_bind", args=[collection.pk])).content.decode()
    assert 'data-busy="Uploading…"' in body
    assert "<progress" in body
    assert 'class="busy" hidden' in body


def test_the_collection_form_announces_itself_as_busy_on_submit(admin):
    body = admin.get(reverse("admin_ui:collection_create")).content.decode()
    assert 'data-busy="Creating…"' in body


def test_the_shell_script_handles_busy_forms():
    script = APP_JS.read_text()
    assert "form[data-busy]" in script
    assert "disabled" in script
    assert ".busy" in script


def test_the_busy_bar_is_hidden_without_inline_styles(editor, collection):
    body = editor.get(reverse("admin_ui:mint", args=[collection.pk])).content.decode()
    assert "style=" not in body
