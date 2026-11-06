"""Mint new ARKs."""

import csv

from django.core.management.base import BaseCommand, CommandError

from core.management.commands._common import get_collection
from jobs.bulkbind import template_csv
from minting.minter import MintError, mint


class Command(BaseCommand):
    help = "Mint new ARKs in a collection."

    def add_arguments(self, parser):
        parser.add_argument("collection", help="Collection prefix or name")
        parser.add_argument("count", type=int, nargs="?", default=1)
        parser.add_argument(
            "--template",
            help="Write a fill-in CSV of the new ARKs here, ready for bulk_bind.",
        )

    def handle(self, *args, **options):
        collection = get_collection(options["collection"])
        count = options["count"]
        if count < 1:
            raise CommandError("count must be at least 1")

        try:
            arks = mint(collection, count=count)
        except MintError as exc:
            raise CommandError(str(exc)) from exc

        for ark in arks:
            self.stdout.write(ark.name)

        if options["template"]:
            with open(options["template"], "w", newline="") as handle:
                csv.writer(handle).writerows(template_csv(arks, collection))
            self.stdout.write(
                self.style.SUCCESS(f"Wrote {len(arks)} rows to {options['template']}")
            )
