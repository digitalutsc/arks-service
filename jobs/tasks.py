"""
Background jobs.

Only bulk bind runs off the request cycle: a 100k-row upload takes long enough
that holding an HTTP connection open for it is not reasonable, and staff want to
close the tab and come back to a result.
"""

from __future__ import annotations

import io
import logging

from celery import shared_task

from core.models import Collection
from jobs.bulkbind import BulkBindError, apply_csv
from jobs.models import BulkBindJob

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
    turn means it can be delivered twice — so a job that is no longer pending is
    left alone rather than minting a second batch of ARKs.
    """
    job = BulkBindJob.objects.select_related("collection").get(pk=job_id)

    if job.status != BulkBindJob.Status.PENDING:
        logger.info("bulk bind job %s already %s; skipping redelivery", job_id, job.status)
        return {"ok": not job.had_errors, "skipped": True}

    job.mark_running(self.request.id)

    try:
        with job.upload.open("rb") as raw:
            text = decode_upload(raw.read())
        result = apply_csv(
            Collection.objects.get(pk=job.collection_id),
            io.StringIO(text),
            mint_missing=job.mint_missing,
            purge_first=job.purge_first,
            user=job.created_by,
        )
    except BulkBindError as exc:
        job.mark_failed(str(exc))
        return {"ok": False, "error": str(exc)}
    except Exception as exc:  # noqa: BLE001 - surfaced to the operator on the job page
        logger.exception("bulk bind job %s crashed", job_id)
        job.mark_failed(f"Unexpected error: {exc}")
        return {"ok": False, "error": str(exc)}

    job.mark_finished(result)
    return {
        "ok": result.ok,
        "created": result.created,
        "updated": result.updated,
        "minted": result.minted,
        "failed": result.failed,
    }
