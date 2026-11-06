"""
Background jobs.

Only bulk bind runs off the request cycle: a 100k-row upload takes long enough
that holding an HTTP connection open for it is not reasonable, and staff want to
close the tab and come back to a result.
"""

from __future__ import annotations

import io
import logging
from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

from core.models import Collection
from jobs.bulkbind import BulkBindError, apply_csv
from jobs.models import BulkBindJob
from jobs.progress import Reporter

#: A PENDING job older than this has probably lost its queue message.
STALE_PENDING_SECONDS = 15 * 60
#: Re-queue a stale PENDING job at most this often.
REQUEUE_INTERVAL_SECONDS = 60 * 60

logger = logging.getLogger(__name__)

#: Encodings tried in order. Excel on Windows still exports cp1252, and decoding
#: that as UTF-8 with errors="replace" silently writes U+FFFD into values.
UPLOAD_ENCODINGS = ("utf-8-sig", "cp1252")


def decode_upload(raw: bytes) -> str:
    """Decode an uploaded CSV, or raise :class:`BulkBindError` saying why not."""
    for encoding in UPLOAD_ENCODINGS:
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise BulkBindError(
        "The file is not valid UTF-8 or Windows-1252 text. Re-export it as CSV UTF-8."
    )


@shared_task(bind=True, acks_late=True, reject_on_worker_lost=True)
def run_bulk_bind(self, job_id: int) -> dict:
    """
    Apply an uploaded CSV, recording progress on the job row.

    ``acks_late`` means a job survives a worker being killed mid-run, which in
    turn means it can be delivered twice. Only a PENDING job is run, claimed in
    one statement so two deliveries cannot both start it. The file is applied
    and the outcome recorded in a single transaction, so a job found RUNNING on
    redelivery committed nothing: it is failed with a message saying so, rather
    than left "running" forever or run a second time.
    """
    job = BulkBindJob.objects.select_related("collection").get(pk=job_id)

    if job.status == BulkBindJob.Status.RUNNING:
        if job.mark_interrupted():
            logger.warning("bulk bind job %s was interrupted; marked failed", job_id)
            job.discard_upload()
        return {"ok": False, "interrupted": True}

    if not job.claim(self.request.id):
        logger.info("bulk bind job %s already %s; skipping redelivery", job_id, job.status)
        return {"ok": not job.had_errors, "skipped": True}

    # Progress goes to the cache, where the job page can read it while the
    # transaction below is still open; the key is removed once the row holds
    # the final counts.
    report = Reporter("bulkbind", job_id)
    try:
        report("reading", 0, None)
        # No names held for the raw bytes or the decoded text, so each copy of
        # the file can be freed as soon as the next one exists.
        with job.upload.open("rb") as raw:
            handle = io.StringIO(decode_upload(raw.read()))
        with transaction.atomic():
            result = apply_csv(
                Collection.objects.get(pk=job.collection_id),
                handle,
                mint_missing=job.mint_missing,
                purge_first=job.purge_first,
                user=job.created_by,
                progress=report,
            )
            job.mark_finished(result)
    except BulkBindError as exc:
        job.mark_failed(str(exc))
        return {"ok": False, "error": str(exc)}
    except Exception as exc:  # noqa: BLE001 - surfaced to the operator on the job page
        logger.exception("bulk bind job %s crashed", job_id)
        job.mark_failed(f"Unexpected error: {exc}")
        return {"ok": False, "error": str(exc)}
    finally:
        report.finish()
        # Claimed, so never run again: the upload has served its purpose.
        job.discard_upload()

    return {
        "ok": result.ok,
        "created": result.created,
        "updated": result.updated,
        "minted": result.minted,
        "failed": result.failed,
    }


@shared_task
def flush_resolution_counters() -> int:
    """
    Move buffered redirect counts into the database.

    Scheduled by Celery beat; also runnable by hand as
    `manage.py flush_counters` if the schedule is not wanted.
    """
    from core.counters import flush_counters

    moved = flush_counters()
    if moved:
        logger.info("flushed %s buffered resolution(s)", moved)
    return moved


@shared_task
def reap_stale_jobs() -> dict:
    """
    Unstick bulk-bind jobs whose worker or queue message went away.

    - RUNNING for longer than the task time limit (plus a margin): the worker
      died without Celery redelivering, e.g. the broker lost the message. Failed
      with the "nothing was applied" message.
    - PENDING for longer than STALE_PENDING_SECONDS: the queue message was
      probably lost (a broker restarted without persistence). Re-queued, at most
      once an hour per job; the atomic claim makes a duplicate delivery harmless.
    """
    now = timezone.now()
    running_limit = timedelta(seconds=settings.CELERY_TASK_TIME_LIMIT + 300)
    interrupted = 0
    for job in BulkBindJob.objects.filter(
        status=BulkBindJob.Status.RUNNING, started_at__lt=now - running_limit
    ):
        if job.mark_interrupted():
            job.discard_upload()
            interrupted += 1
            logger.warning("bulk bind job %s ran past its time limit; marked failed", job.pk)

    requeued = 0
    for job_id in BulkBindJob.objects.filter(
        status=BulkBindJob.Status.PENDING,
        created_at__lt=now - timedelta(seconds=STALE_PENDING_SECONDS),
    ).values_list("pk", flat=True):
        if cache.add(f"bulkbind-requeued:{job_id}", 1, REQUEUE_INTERVAL_SECONDS):
            run_bulk_bind.delay(job_id)
            requeued += 1
            logger.warning("bulk bind job %s was still pending; re-queued", job_id)

    return {"interrupted": interrupted, "requeued": requeued}


@shared_task
def prune_bulk_jobs() -> int:
    """Daily retention, when BULK_BIND_RETENTION_DAYS is set above 0."""
    from jobs.retention import prune_jobs

    days = getattr(settings, "BULK_BIND_RETENTION_DAYS", 0)
    if days < 1:
        return 0
    return prune_jobs(days).jobs


@shared_task
def clear_expired_sessions() -> None:
    """Delete expired sessions; Django never does this by itself."""
    from django.core.management import call_command

    call_command("clearsessions")


@shared_task
def refresh_collection_stats() -> int:
    """
    Recount every collection and rebuild the element-name lists.

    Runs every COLLECTION_STATS_SECONDS so that no staff page has to count a
    large collection, or scan every binding for its element names, on request.
    """
    from core.models import Collection
    from core.search import element_names
    from core.services import refresh_collection_stats as refresh

    lifetime = settings.COLLECTION_STATS_SECONDS * 3
    collections = list(Collection.objects.all())
    for collection in collections:
        refresh(collection)
        element_names(collection.pk, refresh=True, lifetime=lifetime)
    element_names(None, refresh=True, lifetime=lifetime)
    return len(collections)
