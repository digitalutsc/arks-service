"""Bulk-bind jobs: the record staff watch while an upload is processed."""

import pytest
from django.core.files.base import ContentFile

from core.models import Ark, Binding, Collection
from jobs.models import BulkBindJob
from jobs.tasks import run_bulk_bind

pytestmark = pytest.mark.django_db


@pytest.fixture
def collection():
    return Collection.objects.create(name="UTSC", prefix="utsc", naan="61220", template=".zd")


def make_job(collection, body, **kwargs):
    job = BulkBindJob(collection=collection, **kwargs)
    job.upload.save("upload.csv", ContentFile(body.encode()), save=False)
    job.save()
    return job


def test_a_new_job_is_pending(collection):
    job = make_job(collection, "Ark_ID,URL\n")
    assert job.status == BulkBindJob.Status.PENDING
    assert job.is_finished is False


def test_running_a_job_binds_the_rows(collection):
    Ark.objects.create(collection=collection, identifier="utsc0", sequence=0)
    job = make_job(collection, "Ark_ID,URL\n61220/utsc0,https://example.org/0\n")

    run_bulk_bind(job.pk)

    job.refresh_from_db()
    assert job.status == BulkBindJob.Status.FINISHED
    assert job.created == 1
    assert Binding.objects.get(ark__identifier="utsc0", name="URL").value == "https://example.org/0"


def test_a_job_records_its_counts(collection):
    Ark.objects.create(collection=collection, identifier="utsc0", sequence=0)
    job = make_job(collection, "Ark_ID,URL,PID\n61220/utsc0,https://e.example,islandora:1\n")
    run_bulk_bind(job.pk)
    job.refresh_from_db()
    assert job.created == 2
    assert job.failed == 0


def test_a_job_with_bad_rows_finishes_but_writes_nothing(collection):
    Ark.objects.create(collection=collection, identifier="utsc0", sequence=0)
    job = make_job(
        collection,
        "Ark_ID,URL\n61220/utsc0,https://ok.example\n61220/nope,https://bad.example\n",
    )
    run_bulk_bind(job.pk)
    job.refresh_from_db()
    assert job.failed == 1
    assert Binding.objects.count() == 0


def test_an_unreadable_file_marks_the_job_failed(collection):
    job = make_job(collection, "no header that we recognise\n")
    run_bulk_bind(job.pk)
    job.refresh_from_db()
    assert job.status == BulkBindJob.Status.FAILED
    assert "Ark_ID" in job.error


def test_a_job_stores_per_row_results_for_download(collection):
    Ark.objects.create(collection=collection, identifier="utsc0", sequence=0)
    job = make_job(collection, "Ark_ID,URL\n61220/utsc0,https://example.org/0\n")
    run_bulk_bind(job.pk)
    job.refresh_from_db()
    assert job.results
    text = job.results.read().decode()
    assert "ark_id" in text
    assert "61220/utsc0" in text


def test_a_job_can_mint_blank_rows_when_configured(collection):
    job = make_job(collection, "Ark_ID,URL\n,https://example.org/new\n", mint_missing=True)
    run_bulk_bind(job.pk)
    job.refresh_from_db()
    assert job.minted == 1
    assert Ark.objects.count() == 1


def test_a_finished_job_knows_it_is_finished(collection):
    Ark.objects.create(collection=collection, identifier="utsc0", sequence=0)
    job = make_job(collection, "Ark_ID,URL\n61220/utsc0,https://example.org/0\n")
    run_bulk_bind(job.pk)
    job.refresh_from_db()
    assert job.is_finished is True
    assert job.finished_at is not None


def test_a_job_that_already_ran_is_not_run_again(collection):
    # Celery redelivers on worker loss. Without a guard, a job with
    # mint_missing would mint a second batch of ARKs on the retry.
    Ark.objects.create(collection=collection, identifier="utsc0", sequence=0)
    job = make_job(collection, "Ark_ID,URL\n61220/utsc0,https://example.org/0\n")
    run_bulk_bind(job.pk)
    run_bulk_bind(job.pk)
    job.refresh_from_db()
    assert Binding.objects.count() == 1
    assert job.created == 1


def test_a_redelivered_minting_job_does_not_mint_twice(collection):
    job = make_job(collection, "Ark_ID,URL\n,https://example.org/new\n", mint_missing=True)
    run_bulk_bind(job.pk)
    run_bulk_bind(job.pk)
    assert Ark.objects.count() == 1


def test_a_windows_encoded_upload_is_read_without_corruption(collection):
    # Excel on Windows exports cp1252; decoding it as UTF-8 with errors=replace
    # silently wrote U+FFFD into binding values.
    Ark.objects.create(collection=collection, identifier="utsc0", sequence=0)
    body = "Ark_ID,PLACE\n61220/utsc0,Café Montréal\n".encode("cp1252")
    job = BulkBindJob(collection=collection)
    job.upload.save("cp1252.csv", ContentFile(body), save=False)
    job.save()

    run_bulk_bind(job.pk)

    assert Binding.objects.get(name="PLACE").value == "Café Montréal"


def test_a_quoted_field_containing_a_newline_stays_one_row(collection):
    Ark.objects.create(collection=collection, identifier="utsc0", sequence=0)
    job = make_job(collection, 'Ark_ID,NOTE\n61220/utsc0,"line one\nline two"\n')
    run_bulk_bind(job.pk)
    job.refresh_from_db()
    assert job.failed == 0
    assert Binding.objects.get(name="NOTE").value == "line one\nline two"
