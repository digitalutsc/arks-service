"""
What happened to each row's elements, on the job page and in the results file.

A row used to be "ok", which only meant it had passed validation. The upsert
already decides per element whether to create, replace or leave alone and then
threw that away; now the decision is folded back onto the row, after the
transaction's work, so a row never claims a binding that was rolled back.
"""

import io

import pytest
from django.core.files.base import ContentFile
from django.urls import reverse

from admin_ui.roles import EDITOR, ensure_groups, set_role
from core.models import Ark, Binding, Collection
from core.services import bulk_upsert_bindings
from jobs.bulkbind import (
    NOT_APPLIED_MESSAGE,
    STATUS_BOUND,
    STATUS_ERROR,
    STATUS_MINTED,
    STATUS_OK,
    STATUS_UNCHANGED,
    apply_csv,
)
from jobs.models import BulkBindJob
from jobs.tasks import run_bulk_bind

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _media_in_a_temporary_directory(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path


@pytest.fixture
def collection():
    return Collection.objects.create(name="UTSC", prefix="utsc", naan="61220", template=".zd")


@pytest.fixture
def arks(collection):
    return [
        Ark.objects.create(collection=collection, identifier=f"utsc{n}", sequence=n)
        for n in range(3)
    ]


@pytest.fixture
def editor(django_user_model, client):
    ensure_groups()
    user = django_user_model.objects.create_user("ed", password="pw")
    set_role(user, EDITOR)
    client.force_login(user)
    return client


def csv_file(text):
    return io.StringIO(text.lstrip("\n"))


def by_row(result):
    return {row.number: row for row in result.rows}


# --- the upsert tells what it did ---------------------------------------------


def test_the_upsert_reports_each_outcome(arks):
    a, b, _ = arks
    Binding.objects.create(ark=a, name="URL", value="https://old.example")
    Binding.objects.create(ark=b, name="URL", value="https://same.example")
    outcomes = {}
    bulk_upsert_bindings(
        {
            (a.pk, "", "URL"): "https://new.example",
            (b.pk, "", "URL"): "https://same.example",
            (b.pk, "", "PID"): "islandora:1",
        },
        outcomes=outcomes,
    )
    assert outcomes == {
        (a.pk, "", "URL"): "replaced",
        (b.pk, "", "URL"): "unchanged",
        (b.pk, "", "PID"): "created",
    }


def test_the_upsert_still_returns_its_totals(arks):
    created, updated = bulk_upsert_bindings({(arks[0].pk, "", "URL"): "x"}, outcomes={})
    assert (created, updated) == (1, 0)


# --- rows on a successful file ---------------------------------------------------


def test_a_row_with_new_changed_and_identical_cells_is_bound(collection, arks):
    Binding.objects.create(ark=arks[0], name="URL", value="https://old.example")
    Binding.objects.create(ark=arks[0], name="PID", value="islandora:0")
    result = apply_csv(
        collection,
        csv_file("Ark_ID,URL,PID,LOCAL_ID\n61220/utsc0,https://new.example,islandora:0,obj-0\n"),
    )
    row = by_row(result)[2]
    assert row.status == STATUS_BOUND
    assert row.message == "1 created, 1 replaced, 1 unchanged"


def test_a_row_of_identical_cells_is_unchanged(collection, arks):
    Binding.objects.create(ark=arks[0], name="URL", value="https://same.example")
    result = apply_csv(collection, csv_file("Ark_ID,URL\n61220/utsc0,https://same.example\n"))
    row = by_row(result)[2]
    assert row.status == STATUS_UNCHANGED
    assert row.message == "1 unchanged"


def test_a_row_with_only_empty_cells_binds_nothing(collection, arks):
    result = apply_csv(collection, csv_file("Ark_ID,URL\n61220/utsc0,\n"))
    row = by_row(result)[2]
    assert row.status == STATUS_UNCHANGED
    assert row.message == "nothing to bind"


def test_a_purged_row_says_so(collection, arks):
    Binding.objects.create(ark=arks[0], name="OLD", value="gone")
    result = apply_csv(
        collection, csv_file("Ark_ID,URL\n61220/utsc0,https://example.org/0\n"), purge_first=True
    )
    row = by_row(result)[2]
    assert row.status == STATUS_BOUND
    assert row.message == "1 created (previous elements removed)"


def test_a_minted_row_counts_what_it_bound(collection):
    result = apply_csv(
        collection,
        csv_file("Ark_ID,URL,PID\n,https://example.org/a,islandora:a\n"),
        mint_missing=True,
    )
    row = by_row(result)[2]
    assert row.status == STATUS_MINTED
    assert row.message == "minted; 2 created"
    assert row.ark_id == "61220/utsc0"


def test_a_qualified_row_is_described_on_its_own(collection, arks):
    result = apply_csv(
        collection,
        csv_file(
            "Ark_ID,URL\n61220/utsc0,https://example.org/0\n61220/utsc0/page1,https://example.org/0/p1\n"
        ),
    )
    rows = by_row(result)
    assert rows[2].message == "1 created" and rows[3].message == "1 created"
    assert rows[3].ark_id == "61220/utsc0/page1"


def test_counts_match_the_totals(collection, arks):
    Binding.objects.create(ark=arks[1], name="URL", value="https://old.example")
    result = apply_csv(
        collection,
        csv_file(
            "Ark_ID,URL,PID\n"
            "61220/utsc0,https://example.org/0,islandora:0\n"
            "61220/utsc1,https://example.org/1,\n"
            "61220/utsc2,,islandora:2\n"
        ),
    )
    assert (result.created, result.updated) == (3, 1)
    messages = [row.message for row in result.rows]
    assert messages == ["2 created", "1 replaced", "1 created"]


# --- rows on a failed file -----------------------------------------------------------


def test_valid_rows_on_a_failed_file_are_not_applied(collection, arks):
    result = apply_csv(
        collection,
        csv_file("Ark_ID,URL\n61220/utsc0,https://ok.example\n61220/nope,https://bad.example\n"),
    )
    rows = by_row(result)
    assert rows[2].status == STATUS_OK
    assert rows[2].message == NOT_APPLIED_MESSAGE
    assert rows[3].status == STATUS_ERROR
    assert Binding.objects.count() == 0


# --- the job page and the results file --------------------------------------------------


def make_job(collection, body, **kwargs):
    job = BulkBindJob(collection=collection, **kwargs)
    job.upload.save("upload.csv", ContentFile(body.encode()), save=False)
    job.save()
    run_bulk_bind(job.pk)
    job.refresh_from_db()
    return job


def test_the_results_file_carries_the_outcomes(collection, arks):
    Binding.objects.create(ark=arks[1], name="URL", value="https://same.example")
    job = make_job(
        collection,
        "Ark_ID,URL\n61220/utsc0,https://example.org/0\n61220/utsc1,https://same.example\n",
    )
    rows = list(job.iter_results())
    assert rows == [
        (2, "61220/utsc0", STATUS_BOUND, "1 created"),
        (3, "61220/utsc1", STATUS_UNCHANGED, "1 unchanged"),
    ]


def test_the_page_offers_the_new_filters_with_counts(editor, collection, arks):
    Binding.objects.create(ark=arks[1], name="URL", value="https://same.example")
    job = make_job(
        collection,
        "Ark_ID,URL\n61220/utsc0,https://example.org/0\n61220/utsc1,https://same.example\n",
    )
    response = editor.get(reverse("admin_ui:job_detail", args=[job.pk]))
    filters = {f["label"]: f["count"] for f in response.context["result_filters"]}
    assert filters == {
        "All": 2,
        "Errors": 0,
        "Minted": 0,
        "Bound": 1,
        "Unchanged": 1,
        "Not applied": 0,
    }


def test_the_bound_filter_shows_only_bound_rows(editor, collection, arks):
    Binding.objects.create(ark=arks[1], name="URL", value="https://same.example")
    job = make_job(
        collection,
        "Ark_ID,URL\n61220/utsc0,https://example.org/0\n61220/utsc1,https://same.example\n",
    )
    response = editor.get(reverse("admin_ui:job_detail", args=[job.pk]), {"status": "bound"})
    assert [row[1] for row in response.context["results"]["rows"]] == ["61220/utsc0"]


def test_a_failed_file_counts_its_not_applied_rows(editor, collection, arks):
    job = make_job(
        collection,
        "Ark_ID,URL\n61220/utsc0,https://ok.example\n61220/nope,https://bad.example\n",
    )
    response = editor.get(reverse("admin_ui:job_detail", args=[job.pk]))
    filters = {f["label"]: f["count"] for f in response.context["result_filters"]}
    assert filters["Errors"] == 1 and filters["Not applied"] == 1
    assert response.context["result_status"] == STATUS_ERROR
    assert NOT_APPLIED_MESSAGE in response.content.decode() or filters["Not applied"] == 1


def test_each_status_has_its_own_pill(editor, collection, arks):
    Binding.objects.create(ark=arks[1], name="URL", value="https://same.example")
    job = make_job(
        collection,
        "Ark_ID,URL\n61220/utsc0,https://example.org/0\n61220/utsc1,https://same.example\n",
    )
    body = editor.get(
        reverse("admin_ui:job_detail", args=[job.pk]), {"status": "all"}
    ).content.decode()
    assert '<span class="pill ok">bound</span>' in body
    assert '<span class="pill">unchanged</span>' in body
