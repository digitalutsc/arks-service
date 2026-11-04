"""Delete old bulk-bind jobs and their uploaded and results files."""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from jobs.retention import prune_jobs


class Command(BaseCommand):
    help = (
        "Delete finished and failed bulk-bind jobs older than --older-than days, "
        "together with their uploaded CSV and results file. Pending and running "
        "jobs are never touched."
    )

    def add_arguments(self, parser):
        parser.add_argument("--older-than", type=int, required=True, metavar="DAYS")
        parser.add_argument(
            "--dry-run", action="store_true", help="Report what would go; delete nothing."
        )

    def handle(self, *args, older_than: int, dry_run: bool, **options):
        try:
            result = prune_jobs(older_than, dry_run=dry_run)
        except ValueError as exc:
            raise CommandError(str(exc)) from exc
        verb = "Would delete" if dry_run else "Deleted"
        self.stdout.write(
            f"{verb} {result.jobs} job(s) and {result.files} file(s), "
            f"{result.bytes / (1024 * 1024):.1f} MB."
        )
