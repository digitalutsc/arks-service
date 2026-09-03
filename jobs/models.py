"""Bulk-bind jobs."""

from __future__ import annotations

import csv
import io

from django.core.files.base import ContentFile
from django.db import models
from django.utils import timezone

from core.search import csv_safe


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

    def _store_results(self, result) -> None:
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(["row", "ark_id", "status", "message"])
        for row in result.rows:
            writer.writerow(
                [row.number, csv_safe(row.ark_id), csv_safe(row.status), csv_safe(row.message)]
            )
        self.results.save(
            f"job-{self.pk}-results.csv", ContentFile(buffer.getvalue().encode()), save=False
        )
