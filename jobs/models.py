"""Bulk-bind jobs."""

from __future__ import annotations

import csv
import io
import logging
from collections.abc import Iterator

from django.core.files.base import ContentFile
from django.db import models
from django.utils import timezone

from core.search import csv_safe, csv_unsafe

logger = logging.getLogger(__name__)

#: Header of the per-row results file, and of the table the job page draws from it.
RESULT_COLUMNS = ("row", "ark_id", "status", "message")

#: Shown on a job whose worker stopped while it ran.
INTERRUPTED_MESSAGE = (
    "Interrupted: the worker stopped while this job was running. "
    "Nothing from this file was applied; upload it again."
)


class BulkBindJob(models.Model):
    """One uploaded CSV, and what became of it."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        RUNNING = "running", "Running"
        FINISHED = "finished", "Finished"
        FAILED = "failed", "Failed"

    collection = models.ForeignKey(
        "core.Collection", on_delete=models.CASCADE, related_name="bulk_bind_jobs"
    )
    upload = models.FileField(upload_to="bulk-bind/%Y/%m/")
    results = models.FileField(upload_to="bulk-bind/%Y/%m/results/", blank=True)

    mint_missing = models.BooleanField(default=False)
    purge_first = models.BooleanField(default=False)

    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    task_id = models.CharField(max_length=255, blank=True)
    error = models.TextField(blank=True)

    created = models.IntegerField(default=0)
    updated = models.IntegerField(default=0)
    minted = models.IntegerField(default=0)
    failed = models.IntegerField(default=0)

    created_by = models.ForeignKey(
        "auth.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="bulk_bind_jobs"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Bulk bind #{self.pk} into {self.collection_id} ({self.status})"

    @property
    def is_finished(self) -> bool:
        return self.status in (self.Status.FINISHED, self.Status.FAILED)

    @property
    def had_errors(self) -> bool:
        return self.failed > 0 or self.status == self.Status.FAILED

    def mark_running(self, task_id: str = "") -> None:
        self.status = self.Status.RUNNING
        self.task_id = task_id or ""
        self.started_at = timezone.now()
        self.save(update_fields=["status", "task_id", "started_at"])

    def claim(self, task_id: str = "") -> bool:
        """
        Move PENDING to RUNNING in one statement; False if someone else got there.

        Celery can deliver the same job twice (redelivery after a lost worker, or
        the stale-job reaper re-queueing it). Reading the status and then saving
        it would let both deliveries through; a conditional UPDATE lets one.
        """
        now = timezone.now()
        claimed = (
            type(self)
            .objects.filter(pk=self.pk, status=self.Status.PENDING)
            .update(status=self.Status.RUNNING, task_id=task_id or "", started_at=now)
        )
        if claimed:
            self.status, self.task_id, self.started_at = self.Status.RUNNING, task_id or "", now
        return bool(claimed)

    def mark_interrupted(self) -> bool:
        """
        Fail a job that was RUNNING when its worker went away.

        A run applies the whole file and records the outcome in one transaction,
        so a job still marked RUNNING committed nothing: saying so is accurate,
        and re-uploading is safe.
        """
        now = timezone.now()
        failed = (
            type(self)
            .objects.filter(pk=self.pk, status=self.Status.RUNNING)
            .update(status=self.Status.FAILED, error=INTERRUPTED_MESSAGE, finished_at=now)
        )
        if failed:
            self.status, self.error, self.finished_at = self.Status.FAILED, INTERRUPTED_MESSAGE, now
        return bool(failed)

    def discard_upload(self) -> None:
        """
        Delete the uploaded CSV once this job can never run again.

        Only a PENDING job is run, and a claimed job never returns to PENDING,
        so after the claim nothing reads the upload. The results file and this
        row stay; retention removes those. A file that cannot be deleted is
        logged and left named, so the job's outcome never depends on it and a
        later prune can still remove it.
        """
        if not self.upload:
            return
        name = self.upload.name
        try:
            self.upload.storage.delete(name)
        except OSError as exc:
            logger.warning("bulk bind job %s: could not delete upload %s: %s", self.pk, name, exc)
            return
        type(self).objects.filter(pk=self.pk).update(upload="")
        self.upload.name = ""

    def mark_failed(self, message: str) -> None:
        self.status = self.Status.FAILED
        self.error = message
        self.finished_at = timezone.now()
        self.save(update_fields=["status", "error", "finished_at"])

    def mark_finished(self, result) -> None:
        self.status = self.Status.FINISHED
        self.created = result.created
        self.updated = result.updated
        self.minted = result.minted
        self.failed = result.failed
        self.finished_at = timezone.now()
        self._store_results(result)
        self.save(
            update_fields=[
                "status",
                "created",
                "updated",
                "minted",
                "failed",
                "finished_at",
                "results",
            ]
        )

    def iter_results(self) -> Iterator[tuple[int, str, str, str]]:
        """
        Yield ``(row, ark_id, status, message)`` from the stored results file.

        The job page shows the same rows the download holds, so it reads the
        same file rather than keeping a second copy that could disagree. Values
        come back as they were before ``csv_safe`` guarded them for a
        spreadsheet. A job with no file, or whose file has gone from storage,
        simply has no rows: the page must still open.
        """
        if not self.results:
            return
        try:
            # Through the storage, not the FieldFile: a fresh handle each time,
            # whatever state an earlier read or save left the field in.
            handle = self.results.storage.open(self.results.name, "rb")
        except FileNotFoundError:
            return
        with handle:
            reader = csv.reader(io.TextIOWrapper(handle, encoding="utf-8", newline=""))
            next(reader, None)  # the header
            for line in reader:
                if not line:
                    continue
                number, ark_id, status, message = (line + [""] * 4)[:4]
                yield (
                    int(number) if number.isascii() and number.isdigit() else 0,
                    csv_unsafe(ark_id),
                    csv_unsafe(status),
                    csv_unsafe(message),
                )

    def _store_results(self, result) -> None:
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(RESULT_COLUMNS)
        for row in result.rows:
            writer.writerow(
                [row.number, csv_safe(row.ark_id), csv_safe(row.status), csv_safe(row.message)]
            )
        self.results.save(
            f"job-{self.pk}-results.csv", ContentFile(buffer.getvalue().encode()), save=False
        )
