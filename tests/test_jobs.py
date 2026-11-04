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


# --- reading the results back ---------------------------------------------


def test_the_results_can_be_read_back_row_by_row(collection):
    Ark.objects.create(collection=collection, identifier="utsc0", sequence=0)
    job = make_job(
        collection,
        "Ark_ID,URL\n61220/utsc0,https://ok.example\n61220/nope,https://bad.example\n",
    )
    run_bulk_bind(job.pk)
    job.refresh_from_db()

    rows = list(job.iter_results())

    # Row numbers are spreadsheet rows: the header is row 1.
    assert [(number, ark_id, status) for number, ark_id, status, _ in rows] == [
        (2, "61220/utsc0", "ok"),
        (3, "61220/nope", "error"),
    ]
    assert rows[0][3] == ""
    assert rows[1][3]


def test_reading_results_twice_gives_the_same_rows(collection):
    Ark.objects.create(collection=collection, identifier="utsc0", sequence=0)
    job = make_job(collection, "Ark_ID,URL\n61220/utsc0,https://example.org/0\n")
    run_bulk_bind(job.pk)
    job.refresh_from_db()
    assert list(job.iter_results()) == list(job.iter_results())


def test_values_guarded_for_a_spreadsheet_are_read_back_as_written(collection):
    # The download keeps the guard quote; a web page has no use for it.
    job = make_job(collection, "Ark_ID,URL\n=HYPERLINK(1),https://example.org/0\n")
    run_bulk_bind(job.pk)
    job.refresh_from_db()

    assert "'=HYPERLINK(1)" in job.results.storage.open(job.results.name).read().decode()
    assert [ark_id for _, ark_id, _, _ in job.iter_results()] == ["=HYPERLINK(1)"]


def test_a_job_without_a_results_file_has_no_rows(collection):
    job = make_job(collection, "Ark_ID,URL\n")
    assert list(job.iter_results()) == []


def test_a_results_file_gone_from_storage_reads_as_no_rows(collection):
    Ark.objects.create(collection=collection, identifier="utsc0", sequence=0)
    job = make_job(collection, "Ark_ID,URL\n61220/utsc0,https://example.org/0\n")
    run_bulk_bind(job.pk)
    job.refresh_from_db()
    job.results.storage.delete(job.results.name)

    assert list(job.iter_results()) == []


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


# --- jobs that lost their worker or their queue message ------------------


def test_a_job_found_running_on_redelivery_is_failed_not_left_running(collection):
    # A worker killed mid-run (restart, out of memory) leaves the job RUNNING;
    # Celery redelivers it. It used to be skipped and stay "running" forever.
    job = make_job(collection, "Ark_ID,URL\n,https://example.org/new\n", mint_missing=True)
    job.mark_running("first-delivery")

    run_bulk_bind(job.pk)

    job.refresh_from_db()
    assert job.status == BulkBindJob.Status.FAILED
    assert "upload it again" in job.error
    assert Ark.objects.count() == 0, "an interrupted job must not be run a second time"


def test_only_one_delivery_can_claim_a_job(collection):
    job = make_job(collection, "Ark_ID,URL\n,https://example.org/new\n")
    other = BulkBindJob.objects.get(pk=job.pk)
    assert job.claim("a") is True
    assert other.claim("b") is False


def test_a_failure_part_way_commits_nothing(collection, monkeypatch):
    # Applying the file and recording the outcome share one transaction, which
    # is what makes "interrupted means nothing was applied" true.
    import jobs.models

    Ark.objects.create(collection=collection, identifier="utsc0", sequence=0)
    job = make_job(collection, "Ark_ID,URL\n61220/utsc0,https://example.org/0\n")

    def broken(self, result):
        raise RuntimeError("disk full")

    monkeypatch.setattr(jobs.models.BulkBindJob, "mark_finished", broken)
    run_bulk_bind(job.pk)

    job.refresh_from_db()
    assert job.status == BulkBindJob.Status.FAILED
    assert Binding.objects.count() == 0


def test_the_reaper_fails_a_job_running_past_its_time_limit(collection, settings):
    from datetime import timedelta

    from django.utils import timezone

    from jobs.tasks import reap_stale_jobs

    job = make_job(collection, "Ark_ID,URL\n,https://example.org/new\n")
    job.mark_running("lost")
    BulkBindJob.objects.filter(pk=job.pk).update(
        started_at=timezone.now() - timedelta(seconds=settings.CELERY_TASK_TIME_LIMIT + 400)
    )

    assert reap_stale_jobs()["interrupted"] == 1
    job.refresh_from_db()
    assert job.status == BulkBindJob.Status.FAILED


def test_the_reaper_requeues_a_job_whose_message_was_lost(collection, monkeypatch):
    from datetime import timedelta

    from django.utils import timezone

    import jobs.tasks
    from jobs.tasks import reap_stale_jobs

    Ark.objects.create(collection=collection, identifier="utsc0", sequence=0)
    job = make_job(collection, "Ark_ID,URL\n61220/utsc0,https://example.org/0\n")
    BulkBindJob.objects.filter(pk=job.pk).update(created_at=timezone.now() - timedelta(hours=1))
    queued = []
    monkeypatch.setattr(jobs.tasks.run_bulk_bind, "delay", lambda pk: queued.append(pk))

    assert reap_stale_jobs()["requeued"] == 1
    assert reap_stale_jobs()["requeued"] == 0, "re-queued at most once an hour"
    assert queued == [job.pk]


def test_the_reaper_leaves_fresh_jobs_alone(collection):
    from jobs.tasks import reap_stale_jobs

    make_job(collection, "Ark_ID,URL\n,https://example.org/new\n")
    assert reap_stale_jobs() == {"interrupted": 0, "requeued": 0}
