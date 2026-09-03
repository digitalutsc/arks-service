"""Export ARKs and their bindings as CSV."""

import csv
import sys

from django.core.management.base import BaseCommand

from core.management.commands._common import get_collection
from core.search import export_rows, search_arks


class Command(BaseCommand):
    help = "Export ARKs (and everything bound to them) as CSV, ready for bulk_bind."

    def add_arguments(self, parser):
        parser.add_argument("--collection", help="Collection prefix or name")
        parser.add_argument("--text", default="", help="Free text across identifiers and values")
        parser.add_argument("--element", default="", help="Only ARKs carrying this element")
        parser.add_argument("--value", default="", help="... with this exact value")
        parser.add_argument("--unbound", action="store_true", help="Only ARKs with no elements")
        parser.add_argument("--bound", action="store_true", help="Only ARKs with elements")
        parser.add_argument("--min-redirects", type=int, dest="min_redirects")
        parser.add_argument("--out", help="Write here instead of standard output")

    def handle(self, *args, **options):
        bound = None
        if options["bound"]:
            bound = True
        elif options["unbound"]:
            bound = False

        queryset = search_arks(
            collection=get_collection(options["collection"]) if options["collection"] else None,
            text=options["text"],
            element=options["element"],
            value=options["value"],
            bound=bound,
            min_redirects=options["min_redirects"],
        )

        if options["out"]:
            with open(options["out"], "w", newline="") as handle:
                count = _write(handle, queryset)
            self.stdout.write(self.style.SUCCESS(f"Wrote {count} rows to {options['out']}"))
        else:
            _write(sys.stdout, queryset)


def _write(handle, queryset) -> int:
    writer = csv.writer(handle)
    count = 0
    for row in export_rows(queryset):
        writer.writerow(row)
        count += 1
    return max(count - 1, 0)
