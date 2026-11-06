"""
A bulk-bind upload is deleted as soon as its job can never run again.

Only a PENDING job is ever run, and a claimed job never goes back to PENDING,
so once a job is claimed nothing reads its upload again. Keeping it only filled
the media volume. The results file and the job row stay; retention
(BULK_BIND_RETENTION_DAYS) governs those.
"""

import logging
from datetime import timedelta

import pytest
from django.core.files.base import ContentFile
from django.urls import reverse
from django.utils import timezone

from admin_ui.roles import EDITOR, ensure_groups, set_role
from core.models import Ark, Binding, Collection
from jobs.models import BulkBindJob
from jobs.retention import prune_jobs
from jobs.tasks import reap_stale_jobs, run_bulk_bind

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _media(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path


@pytest.fixture
def collection():
    return Collection.objects.create(name="UTSC", prefix="utsc", naan="61220", template=".zd")


def make_job(collection, body="Ark_ID,URL\n61220/utsc0,https://example.org/0\n", **kwargs):
    job = BulkBindJob(collection=collection, **kwargs)
    job.upload.save("upload.csv", ContentFile(body.encode()), save=False)
    job.save()
    return job


def upload_exists(job, name):
    return job.upload.storage.exists(name)


@pytest.fixture
def ark(collection):
    return Ark.objects.create(collection=collection, identifier="utsc0", sequence=0)


def test_a_finished_job_keeps_its_results_but_not_its_upload(collection, ark):
    job = make_job(collection)
    name = job.upload.name

    run_bulk_bind(job.pk)

    job.refresh_from_db()
    assert job.status == BulkBindJob.Status.FINISHED
    assert Binding.objects.get(name="URL").value == "https://example.org/0"
    assert not upload_exists(job, name)
    assert not job.upload
    assert job.results and job.results.storage.exists(job.results.name)
    assert [row[1] for row in job.iter_results()] == ["61220/utsc0"]


def test_the_job_page_and_download_still_work_without_the_upload(
    collection, ark, client, django_user_model
):
    ensure_groups()
    user = django_user_model.objects.create_user("ed", password="pw")
    set_role(user, EDITOR)
    client.force_login(user)
    job = make_job(collection)
    run_bulk_bind(job.pk)

    page = client.get(reverse("admin_ui:job_detail", args=[job.pk]))
    download = client.get(reverse("admin_ui:job_results", args=[job.pk]))

    assert page.status_code == 200
    assert "61220/utsc0" in page.content.decode()
    assert download.status_code == 200
    assert "61220/utsc0" in download.content.decode()


def test_a_job_failed_by_its_file_loses_its_upload(collection):
    job = make_job(collection, "no,ark,column\n1,2,3\n")
    name = job.upload.name

    run_bulk_bind(job.pk)

    job.refresh_from_db()
    assert job.status == BulkBindJob.Status.FAILED
    assert not upload_exists(job, name)
    assert not job.upload


def test_a_job_that_crashes_loses_its_upload(collection, ark, monkeypatch):
    import jobs.tasks

    def broken(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(jobs.tasks, "apply_csv", broken)
    job = make_job(collection)
    name = job.upload.name

    run_bulk_bind(job.pk)

    job.refresh_from_db()
    assert job.status == BulkBindJob.Status.FAILED
    assert not upload_exists(job, name)


def test_a_job_found_running_on_redelivery_loses_its_upload(collection):
    job = make_job(collection)
    name = job.upload.name
    job.mark_running("first-delivery")

    run_bulk_bind(job.pk)

    job.refresh_from_db()
    assert job.status == BulkBindJob.Status.FAILED
    assert not upload_exists(job, name)
    assert not job.upload


def test_a_redelivered_finished_job_is_skipped_quietly(collection, ark):
    job = make_job(collection)
    run_bulk_bind(job.pk)

    assert run_bulk_bind(job.pk)["skipped"] is True
    job.refresh_from_db()
    assert job.status == BulkBindJob.Status.FINISHED


def test_the_reaper_deletes_the_upload_of_a_job_it_fails(collection, settings):
    job = make_job(collection)
    name = job.upload.name
    job.mark_running("lost")
    BulkBindJob.objects.filter(pk=job.pk).update(
        started_at=timezone.now() - timedelta(seconds=settings.CELERY_TASK_TIME_LIMIT + 400)
    )

    assert reap_stale_jobs()["interrupted"] == 1
    job.refresh_from_db()
    assert not upload_exists(job, name)
    assert not job.upload


def test_the_reaper_keeps_the_upload_of_a_job_it_requeues(collection, monkeypatch):
    import jobs.tasks

    job = make_job(collection)
    name = job.upload.name
    BulkBindJob.objects.filter(pk=job.pk).update(created_at=timezone.now() - timedelta(hours=1))
    monkeypatch.setattr(jobs.tasks.run_bulk_bind, "delay", lambda pk: None)

    assert reap_stale_jobs()["requeued"] == 1
    job.refresh_from_db()
    assert job.status == BulkBindJob.Status.PENDING
    assert upload_exists(job, name)
    assert job.upload.name == name


def test_an_upload_that_cannot_be_deleted_does_not_change_the_outcome(
    collection, ark, monkeypatch, caplog
):
    from django.core.files.storage import FileSystemStorage

    def refuse(self, name):
        raise PermissionError("read-only volume")

    monkeypatch.setattr(FileSystemStorage, "delete", refuse)
    job = make_job(collection)

    with caplog.at_level(logging.WARNING, logger="jobs.models"):
        run_bulk_bind(job.pk)

    job.refresh_from_db()
    assert job.status == BulkBindJob.Status.FINISHED
    assert job.created == 1
    assert job.upload, "the name stays so retention can still remove the file"
    assert "could not delete" in caplog.text


def test_retention_still_prunes_a_job_whose_upload_is_gone(collection, ark):
    job = make_job(collection)
    run_bulk_bind(job.pk)
    job.refresh_from_db()
    results = job.results.name
    BulkBindJob.objects.filter(pk=job.pk).update(finished_at=timezone.now() - timedelta(days=40))
    BulkBindJob.objects.filter(pk=job.pk).update(created_at=timezone.now() - timedelta(days=40))

    pruned = prune_jobs(30)

    assert pruned.jobs == 1
    assert pruned.files == 1
    assert not job.results.storage.exists(results)
    assert not BulkBindJob.objects.exists()
