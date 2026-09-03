"""Apply a bulk-bind CSV from the command line."""

import csv

from django.core.management.base import BaseCommand, CommandError

from core.management.commands._common import get_collection
from jobs.bulkbind import BulkBindError, apply_csv


class Command(BaseCommand):
    help = "Bind elements to ARKs from a CSV file."

    def add_arguments(self, parser):
        parser.add_argument("collection", help="Collection prefix or name")
        parser.add_argument(
            "csv_path", help="CSV with an Ark_ID column plus one column per element"
        )
        parser.add_argument(
            "--mint-missing",
            action="store_true",
            help="Mint a new ARK for rows with a blank Ark_ID.",
        )
        parser.add_argument(
            "--purge-first",
            action="store_true",
            help="Remove existing elements from the ARKs in the file before binding.",
        )
        parser.add_argument("--results", help="Write a per-row results CSV here.")

    def handle(self, *args, **options):
        collection = get_collection(options["collection"])

        try:
            with open(options["csv_path"], newline="", encoding="utf-8-sig") as handle:
                result = apply_csv(
                    collection,
                    handle,
                    mint_missing=options["mint_missing"],
                    purge_first=options["purge_first"],
                )
        except FileNotFoundError as exc:
            raise CommandError(f"No such file: {options['csv_path']}") from exc
        except BulkBindError as exc:
            raise CommandError(str(exc)) from exc

        if options["results"]:
            with open(options["results"], "w", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(["row", "ark_id", "status", "message"])
                for row in result.rows:
                    writer.writerow([row.number, row.ark_id, row.status, row.message])

        if not result.ok:
            for row in result.errors[:20]:
                self.stderr.write(f"  row {row.number}: {row.message}")
            raise CommandError(
                f"{result.failed} row(s) failed; nothing was written. "
                "Fix the file and run it again."
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"{result.created} created, {result.updated} updated, {result.minted} minted"
            )
        )
