"""
The staff workflow, end to end through the web interface.

Mint a batch, download the pre-filled template, fill it in, upload it, then
check the ARKs actually resolve. This is the path staff walk every week, so it
is worth exercising as one piece rather than only in parts.
"""

import csv
import io

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from admin_ui.roles import ADMIN, EDITOR, ensure_groups, set_role
from core.models import Ark, Binding, Collection
from jobs.models import BulkBindJob

pytestmark = pytest.mark.django_db


@pytest.fixture
def editor(django_user_model, client):
    ensure_groups()
    user = django_user_model.objects.create_user("editor", password="pw")
    set_role(user, EDITOR)
    client.force_login(user)
    return user


@pytest.fixture
def administrator(django_user_model):
    ensure_groups()
    user = django_user_model.objects.create_user("boss", password="pw")
    set_role(user, ADMIN)
    return user


@pytest.fixture
def collection():
    return Collection.objects.create(
        name="UTSC", prefix="utsc", naan="61220", naa="UTSC Library", template=".zd"
    )


def test_mint_then_template_then_bulk_bind_then_resolve(client, editor, collection, settings):
    settings.CELERY_TASK_ALWAYS_EAGER = True

    # 1. Mint three ARKs through the UI.
    response = client.post(reverse("admin_ui:mint", args=[collection.pk]), {"count": "3"})
    assert response.status_code == 200
    assert Ark.objects.count() == 3

    # 2. Download the fill-in template for exactly those ARKs.
    response = client.get(reverse("admin_ui:mint_template", args=[collection.pk]))
    assert response.status_code == 200
    assert response["Content-Type"] == "text/csv"
    rows = list(csv.reader(io.StringIO(b"".join(response.streaming_content).decode())))
    header, body = rows[0], [r for r in rows[1:] if r]
    assert header[0] == "Ark_ID"
    assert [r[0] for r in body] == ["61220/utsc0", "61220/utsc1", "61220/utsc2"]

    # 3. Fill it in the way a spreadsheet would, and add a column of our own.
    header.append("PHOTOGRAPHER")
    filled = [header]
    for index, row in enumerate(body):
        row = row + [""]
        row[header.index("URL")] = f"https://example.org/item/{index}"
        row[header.index("PID")] = f"islandora:{index}"
        row[header.index("PHOTOGRAPHER")] = "Ansel Adams"
        filled.append(row)

    buffer = io.StringIO()
    csv.writer(buffer).writerows(filled)
    upload = SimpleUploadedFile("filled.csv", buffer.getvalue().encode(), content_type="text/csv")

    # 4. Upload it.
    response = client.post(
        reverse("admin_ui:bulk_bind", args=[collection.pk]), {"file": upload}, follow=True
    )
    assert response.status_code == 200

    job = BulkBindJob.objects.get()
    assert job.status == BulkBindJob.Status.FINISHED
    assert job.failed == 0
    assert job.created == 9  # 3 ARKs x URL, PID, PHOTOGRAPHER

    # 5. The ARKs now resolve.
    ark = Ark.objects.get(identifier="utsc1")
    assert ark.bindings.get(name="PHOTOGRAPHER").value == "Ansel Adams"

    response = client.get("/ark:/61220/utsc1", RAW_URI="/ark:/61220/utsc1")
    assert response.status_code == 302
    assert response["Location"] == "https://example.org/item/1"

    # 6. And an export round-trips back into the same shape.
    response = client.get(reverse("admin_ui:export"), {"collection": collection.pk})
    exported = list(csv.reader(io.StringIO(b"".join(response.streaming_content).decode())))
    assert "PHOTOGRAPHER" in exported[0]
    assert any(row[0] == "61220/utsc1" for row in exported[1:])


def test_a_bad_upload_reports_every_problem_and_changes_nothing(
    client, editor, collection, settings
):
    settings.CELERY_TASK_ALWAYS_EAGER = True
    client.post(reverse("admin_ui:mint", args=[collection.pk]), {"count": "2"})

    body = (
        "Ark_ID,URL\n"
        "61220/utsc0,https://good.example\n"
        "61220/nosuchark,https://bad.example\n"
        "61220/utsc1,https://alsogood.example\n"
    )
    upload = SimpleUploadedFile("bad.csv", body.encode(), content_type="text/csv")
    client.post(reverse("admin_ui:bulk_bind", args=[collection.pk]), {"file": upload}, follow=True)

    job = BulkBindJob.objects.get()
    assert job.failed == 1
    assert job.created == 0
    assert Binding.objects.count() == 0, "a partial apply would leave the collection inconsistent"

    # The per-row results are downloadable so the file can be fixed in one pass.
    response = client.get(reverse("admin_ui:job_results", args=[job.pk]))
    assert response.status_code == 200
    assert "nosuchark" in response.content.decode()


def test_purging_stops_an_ark_resolving_without_reissuing_it(client, administrator, collection):
    client.force_login(administrator)
    client.post(reverse("admin_ui:mint", args=[collection.pk]), {"count": "1"})
    ark = Ark.objects.get()
    Binding.objects.create(ark=ark, name="URL", value="https://example.org/0")

    assert client.get("/ark:/61220/utsc0", RAW_URI="/ark:/61220/utsc0").status_code == 302

    client.post(reverse("admin_ui:ark_purge", args=[ark.pk]))

    assert client.get("/ark:/61220/utsc0", RAW_URI="/ark:/61220/utsc0").status_code == 404
    assert Ark.objects.filter(identifier="utsc0").exists(), "the identifier must never be reissued"
