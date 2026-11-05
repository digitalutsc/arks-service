"""
Loopholes found in the security audit.

Each test states the input and the behaviour that must hold. They are grouped
by the thing an attacker controls.
"""

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from admin_ui.roles import ADMIN, EDITOR, VIEWER, ensure_groups, role_of, set_role
from core.models import Ark, Binding, Collection

pytestmark = pytest.mark.django_db


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
            username, password="pw-for-tests", is_superuser=superuser, is_staff=superuser
        )
        if role:
            set_role(user, role)
        return user

    return _make


@pytest.fixture
def viewer(client, make_user):
    client.force_login(make_user("v", VIEWER))
    return client


@pytest.fixture
def editor(client, make_user):
    client.force_login(make_user("e", EDITOR))
    return client


@pytest.fixture
def admin(client, make_user):
    client.force_login(make_user("a", ADMIN))
    return client


# --- request parameters must not produce 500s -----------------------------


@pytest.mark.parametrize(
    "params",
    [
        {"collection": "abc"},
        {"collection": "1; DROP TABLE"},
        {"collection": "99999999999999999999"},
        {"min_redirects": "²"},  # str.isdigit() is True for superscripts
        {"min_redirects": "-1"},
        {"min_redirects": "abc"},
        {"page": "abc"},
        {"page": "-5"},
        {"page": "99999999999999999999"},
        {"minted_after": "not-a-date"},
        {"bound": "maybe"},
    ],
)
def test_bad_search_parameters_do_not_error(viewer, collection, params):
    # A bad collection sends the visitor to choose one; anything else is ignored.
    response = viewer.get(reverse("admin_ui:ark_list"), {"collection": collection.pk, **params})
    assert response.status_code in (200, 302), f"{params} produced {response.status_code}"


@pytest.mark.parametrize("params", [{"collection": "abc"}, {"min_redirects": "²"}])
def test_bad_export_parameters_do_not_error(viewer, collection, params):
    response = viewer.get(reverse("admin_ui:export"), {"collection": collection.pk, **params})
    assert response.status_code in (200, 302)


def test_minting_over_the_cap_is_a_message_not_a_crash(editor, collection, settings):
    settings.MINT_MAX_PER_REQUEST = 10
    response = editor.post(reverse("admin_ui:mint", args=[collection.pk]), {"count": "999999"})
    assert response.status_code == 200
    assert Ark.objects.count() == 0


def test_a_non_numeric_user_id_does_not_error(admin):
    response = admin.post(reverse("admin_ui:user_list"), {"user": "abc", "role": ADMIN})
    assert response.status_code in (200, 302)


# --- CSV formula injection ------------------------------------------------

DANGEROUS = ["=cmd|'/c calc'!A1", "+1+1", "-1+1", "@SUM(1+9)", "\tcalc", "\rcalc"]


@pytest.mark.parametrize("payload", DANGEROUS)
def test_exported_values_cannot_execute_in_a_spreadsheet(admin, collection, payload):
    from core.search import export_rows, search_arks

    ark = Ark.objects.create(collection=collection, identifier="utsc0", sequence=0)
    Binding.objects.create(ark=ark, name="NOTE", value=payload)

    rows = list(export_rows(search_arks(collection=collection), collection))
    cell = next(c for row in rows[1:] for c in row if payload in c)
    assert not cell.startswith(("=", "+", "-", "@", "\t", "\r")), (
        f"{cell!r} would be executed by Excel or LibreOffice"
    )


def test_escaping_does_not_change_the_stored_value(admin, collection):
    ark = Ark.objects.create(collection=collection, identifier="utsc0", sequence=0)
    Binding.objects.create(ark=ark, name="NOTE", value="=1+1")
    assert Binding.objects.get(ark=ark, name="NOTE").value == "=1+1"


def test_ordinary_values_are_untouched(admin, collection):
    from core.search import export_rows, search_arks

    ark = Ark.objects.create(collection=collection, identifier="utsc0", sequence=0)
    Binding.objects.create(ark=ark, name="URL", value="https://example.org/a-b")
    rows = list(export_rows(search_arks(collection=collection), collection))
    assert any("https://example.org/a-b" in cell for row in rows[1:] for cell in row)


# --- uploads --------------------------------------------------------------


def test_an_oversized_upload_is_refused_before_a_job_is_created(editor, collection, settings):
    from jobs.models import BulkBindJob

    settings.BULK_BIND_MAX_BYTES = 1024
    payload = b"Ark_ID,URL\n" + b"61220/utsc0,https://example.org/x\n" * 200
    upload = SimpleUploadedFile("big.csv", payload, content_type="text/csv")

    response = editor.post(
        reverse("admin_ui:bulk_bind", args=[collection.pk]), {"file": upload}, follow=True
    )
    assert response.status_code == 200
    assert BulkBindJob.objects.count() == 0, "a rejected upload must not leave a job behind"


def test_a_non_csv_upload_is_refused(editor, collection):
    from jobs.models import BulkBindJob

    upload = SimpleUploadedFile("payload.exe", b"MZ\x00binary", content_type="application/exe")
    editor.post(reverse("admin_ui:bulk_bind", args=[collection.pk]), {"file": upload}, follow=True)
    assert BulkBindJob.objects.count() == 0


# --- authorisation --------------------------------------------------------


def test_the_last_admin_cannot_remove_their_own_role(client, make_user):
    boss = make_user("boss", ADMIN)
    client.force_login(boss)
    client.post(reverse("admin_ui:user_list"), {"user": boss.pk, "role": "none"})
    boss.refresh_from_db()
    assert role_of(boss) == ADMIN, "removing the last Admin would lock everyone out"


def test_an_admin_can_be_demoted_while_another_remains(client, make_user):
    boss = make_user("boss", ADMIN)
    other = make_user("other", ADMIN)
    client.force_login(boss)
    client.post(reverse("admin_ui:user_list"), {"user": other.pk, "role": VIEWER})
    other.refresh_from_db()
    assert role_of(other) == VIEWER


def test_a_job_from_another_collection_is_not_readable(client, make_user, collection):
    from django.core.files.base import ContentFile

    from jobs.models import BulkBindJob

    job = BulkBindJob(collection=collection)
    job.upload.save("x.csv", ContentFile(b"Ark_ID\n"), save=False)
    job.save()

    client.force_login(make_user("nobody"))  # signed in, no role
    assert client.get(reverse("admin_ui:job_detail", args=[job.pk])).status_code == 403
    assert client.get(reverse("admin_ui:job_results", args=[job.pk])).status_code == 403


# --- login brute force ----------------------------------------------------


def test_repeated_failures_lock_an_account_out(client, make_user, settings):
    settings.LOGIN_MAX_ATTEMPTS = 3
    make_user("target", VIEWER)
    url = reverse("admin_ui:login")

    for _ in range(3):
        client.post(url, {"username": "target", "password": "wrong"})

    # Even the right password is refused while the lockout stands.
    response = client.post(url, {"username": "target", "password": "pw-for-tests"})
    assert response.status_code == 429
    assert "_auth_user_id" not in client.session


def test_a_successful_login_clears_the_counter(client, make_user, settings):
    settings.LOGIN_MAX_ATTEMPTS = 3
    make_user("target", VIEWER)
    url = reverse("admin_ui:login")

    client.post(url, {"username": "target", "password": "wrong"})
    client.post(url, {"username": "target", "password": "pw-for-tests"})
    client.logout()

    # The earlier failure must not count towards a later lockout.
    for _ in range(2):
        client.post(url, {"username": "target", "password": "wrong"})
    response = client.post(url, {"username": "target", "password": "pw-for-tests"})
    assert response.status_code == 302
    assert "_auth_user_id" in client.session


def test_locking_one_account_does_not_lock_another(client, make_user, settings):
    settings.LOGIN_MAX_ATTEMPTS = 2
    make_user("alice", VIEWER)
    make_user("bob", VIEWER)
    url = reverse("admin_ui:login")

    for _ in range(3):
        client.post(url, {"username": "alice", "password": "wrong"})

    response = client.post(url, {"username": "bob", "password": "pw-for-tests"})
    assert response.status_code == 302, "bob must be unaffected by alice's lockout"


def test_a_forged_forwarded_for_does_not_dodge_the_lockout(client, make_user, settings):
    # Apache appends the real client address to whatever X-Forwarded-For the
    # client sent. Keying on the first entry let an attacker invent a new
    # address per attempt and never be locked out.
    settings.LOGIN_MAX_ATTEMPTS = 3
    settings.TRUST_FORWARDED_FOR = True
    make_user("target", VIEWER)
    url = reverse("admin_ui:login")

    for n in range(3):
        client.post(
            url,
            {"username": "target", "password": "wrong"},
            HTTP_X_FORWARDED_FOR=f"10.9.9.{n}, 203.0.113.7",
        )

    response = client.post(
        url,
        {"username": "target", "password": "pw-for-tests"},
        HTTP_X_FORWARDED_FOR="10.9.9.99, 203.0.113.7",
    )
    assert response.status_code == 429


def test_the_address_apache_saw_is_used(rf, settings):
    from admin_ui.throttle import client_address

    settings.TRUST_FORWARDED_FOR = True
    request = rf.get("/", HTTP_X_FORWARDED_FOR="1.2.3.4, 203.0.113.7", REMOTE_ADDR="127.0.0.1")
    assert client_address(request) == "203.0.113.7"

    settings.TRUST_FORWARDED_FOR = False
    assert client_address(request) == "127.0.0.1"


def test_a_locked_out_attempt_says_so(client, make_user, settings):
    settings.LOGIN_MAX_ATTEMPTS = 1
    make_user("target", VIEWER)
    url = reverse("admin_ui:login")
    client.post(url, {"username": "target", "password": "wrong"})
    response = client.post(url, {"username": "target", "password": "wrong"})
    assert b"too many" in response.content.lower()


# --- response headers -----------------------------------------------------


def test_pages_carry_a_content_security_policy(client, collection):
    response = client.get("/")
    assert "Content-Security-Policy" in response
    policy = response["Content-Security-Policy"]
    assert "default-src 'self'" in policy
    assert "object-src 'none'" in policy
    assert "frame-ancestors 'none'" in policy


def test_the_policy_does_not_allow_inline_script(client):
    policy = client.get("/")["Content-Security-Policy"]
    assert "'unsafe-inline'" not in policy.split("script-src")[-1].split(";")[0]


def test_a_referrer_policy_is_set(client):
    # Without this, an ARK's target learns the full referring URL.
    assert client.get("/")["Referrer-Policy"]


def test_redirects_do_not_leak_the_referrer(client, collection):
    ark = Ark.objects.create(collection=collection, identifier="utsc1", sequence=1)
    Binding.objects.create(ark=ark, name="URL", value="https://example.org/1")
    response = client.get("/ark:/61220/utsc1", RAW_URI="/ark:/61220/utsc1")
    assert response.status_code == 302
    assert response["Referrer-Policy"]
