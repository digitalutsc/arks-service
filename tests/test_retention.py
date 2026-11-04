"""Old bulk-bind jobs and their files can be pruned; nothing else is touched."""

from datetime import timedelta

import pytest
from django.core.files.base import ContentFile
from django.core.management import call_command
from django.utils import timezone

from core.models import Collection
from jobs.models import BulkBindJob
from jobs.retention import prune_jobs

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _media(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path


@pytest.fixture
def collection():
    return Collection.objects.create(name="UTSC", prefix="utsc", naan="61220", template=".zd")


def make_job(collection, status, age_days):
    job = BulkBindJob(collection=collection, status=status)
    job.upload.save("upload.csv", ContentFile(b"Ark_ID,URL\n"), save=False)
    job.results.save("results.csv", ContentFile(b"row,ark_id,status,message\n"), save=False)
    job.save()
    then = timezone.now() - timedelta(days=age_days)
    finished = then if status in (BulkBindJob.Status.FINISHED, BulkBindJob.Status.FAILED) else None
    BulkBindJob.objects.filter(pk=job.pk).update(created_at=then, finished_at=finished)
    job.refresh_from_db()
    return job


def test_old_finished_jobs_and_their_files_are_deleted(collection):
    old = make_job(collection, BulkBindJob.Status.FINISHED, 100)
    upload, results = old.upload.path, old.results.path

    result = prune_jobs(30)

    assert result.jobs == 1
    assert result.files == 2
    assert not BulkBindJob.objects.filter(pk=old.pk).exists()
    import os

    assert not os.path.exists(upload)
    assert not os.path.exists(results)


def test_recent_and_unfinished_jobs_are_kept(collection):
    recent = make_job(collection, BulkBindJob.Status.FINISHED, 5)
    pending = make_job(collection, BulkBindJob.Status.PENDING, 100)
    running = make_job(collection, BulkBindJob.Status.RUNNING, 100)

    assert prune_jobs(30).jobs == 0
    assert BulkBindJob.objects.filter(pk__in=[recent.pk, pending.pk, running.pk]).count() == 3


def test_a_dry_run_deletes_nothing(collection):
    old = make_job(collection, BulkBindJob.Status.FAILED, 100)
    result = prune_jobs(30, dry_run=True)
    assert result.jobs == 1
    assert BulkBindJob.objects.filter(pk=old.pk).exists()
    assert old.upload.storage.exists(old.upload.name)


def test_the_command_reports_what_it_did(collection, capsys):
    make_job(collection, BulkBindJob.Status.FINISHED, 100)
    call_command("prune_bulk_jobs", "--older-than", "30", "--dry-run")
    assert "Would delete 1 job(s)" in capsys.readouterr().out


def test_the_scheduled_prune_is_off_by_default(collection, settings):
    from jobs.tasks import prune_bulk_jobs

    make_job(collection, BulkBindJob.Status.FINISHED, 1000)
    assert settings.BULK_BIND_RETENTION_DAYS == 0
    assert prune_bulk_jobs() == 0
    assert BulkBindJob.objects.count() == 1


def test_a_missing_file_does_not_stop_the_prune(collection):
    old = make_job(collection, BulkBindJob.Status.FINISHED, 100)
    old.upload.storage.delete(old.upload.name)
    assert prune_jobs(30).jobs == 1
