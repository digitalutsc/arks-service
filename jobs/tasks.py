"""
Background jobs.

Only bulk bind runs off the request cycle: a 100k-row upload takes long enough
that holding an HTTP connection open for it is not reasonable, and staff want to
close the tab and come back to a result.
"""

from __future__ import annotations

import logging

from celery import shared_task

from core.models import Collection
from jobs.bulkbind import BulkBindError, apply_csv
from jobs.models import BulkBindJob

logger = logging.getLogger(__name__)


@shared_task(bind=True)
def run_bulk_bind(self, job_id: int) -> dict:
    """Apply an uploaded CSV, recording progress on the job row."""
    job = BulkBindJob.objects.select_related("collection").get(pk=job_id)
    job.mark_running(self.request.id)

    try:
        with job.upload.open("rb") as raw:
            text = raw.read().decode("utf-8-sig", errors="replace").splitlines(keepends=True)
        result = apply_csv(
            Collection.objects.get(pk=job.collection_id),
            iter(text),
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
