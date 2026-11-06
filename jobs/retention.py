"""
Retention for bulk-bind jobs.

The uploaded CSV is deleted as soon as its job has run
(BulkBindJob.discard_upload); what remains on disk is each job's results file,
which the job page reads. Pruning removes that file and the job row. It is off
by default (BULK_BIND_RETENTION_DAYS=0 keeps everything); the `prune_bulk_jobs`
command runs it by hand.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta

from django.utils import timezone

from jobs.models import BulkBindJob

logger = logging.getLogger(__name__)


@dataclass
class PruneResult:
    jobs: int = 0
    files: int = 0
    bytes: int = 0


def prune_jobs(older_than_days: int, *, dry_run: bool = False) -> PruneResult:
    """
    Delete finished or failed jobs older than ``older_than_days``, with their files.

    Pending and running jobs are never touched. Age is measured from when the
    job finished, or was created if it never finished.
    """
    if older_than_days < 1:
        raise ValueError("older_than_days must be at least 1")

    cutoff = timezone.now() - timedelta(days=older_than_days)
    done = (BulkBindJob.Status.FINISHED, BulkBindJob.Status.FAILED)
    result = PruneResult()

    for job in BulkBindJob.objects.filter(status__in=done, created_at__lt=cutoff).iterator():
        if job.finished_at and job.finished_at >= cutoff:
            continue
        for field in (job.upload, job.results):
            if not field:
                continue
            storage, name = field.storage, field.name
            try:
                size = storage.size(name) if storage.exists(name) else 0
            except OSError:
                size = 0
            if size or storage.exists(name):
                result.files += 1
                result.bytes += size
                if not dry_run:
                    storage.delete(name)
        result.jobs += 1
        if not dry_run:
            job.delete()

    if result.jobs and not dry_run:
        logger.info(
            "pruned %s bulk-bind job(s), %s file(s), %s bytes",
            result.jobs,
            result.files,
            result.bytes,
        )
    return result
