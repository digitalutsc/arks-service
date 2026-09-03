"""
Compare ARK resolution between the legacy service and this one.

The cutover gate: run both systems side by side, resolve every ARK against
each, and only flip the Apache vhost once this reports no differences.

    manage.py resolve_diff \\
        --legacy-base https://ark.digital.utsc.utoronto.ca \\
        --new-base http://127.0.0.1:8001 \\
        --out cutover-diff.csv

Start with --sample 500 for a quick read, then run it clean over everything.
"""

from __future__ import annotations

import csv
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from django.core.management.base import BaseCommand, CommandError

from core.management.commands._common import get_collection
from core.verify import base_path, compare, iter_check_paths, read_known_paths

#: Statuses we compare bodies for rather than Location headers.
BODY_STATUSES = {200}


class Command(BaseCommand):
    help = "Diff ARK resolution between the legacy service and this one."

    def add_arguments(self, parser):
        parser.add_argument("--legacy-base", required=True, help="e.g. https://ark.example")
        parser.add_argument("--new-base", required=True, help="e.g. http://127.0.0.1:8001")
        parser.add_argument("--collection", help="Only check this collection")
        parser.add_argument("--sample", type=int, help="Only check the first N ARKs")
        parser.add_argument(
            "--no-inflections",
            action="store_false",
            dest="inflections",
            help="Skip the ?, ?? and ?info responses (they are checked by default)",
        )
        parser.add_argument("--workers", type=int, default=8)
        parser.add_argument("--timeout", type=int, default=20)
        parser.add_argument("--out", help="Write differences to this CSV")
        parser.add_argument(
            "--known",
            help="An import report CSV. Differences on the ARKs it names are expected, "
            "and do not hold up the cutover.",
        )
        parser.add_argument(
            "--stop-after",
            type=int,
            default=0,
            help="Give up after this many differences (0 = never)",
        )

    def handle(self, *args, **options):
        legacy_base = options["legacy_base"].rstrip("/")
        new_base = options["new_base"].rstrip("/")
        collection = get_collection(options["collection"]) if options["collection"] else None

        known_paths: set[str] = set()
        if options["known"]:
            try:
                known_paths = read_known_paths(options["known"])
            except OSError as exc:
                raise CommandError(f"Could not read {options['known']}: {exc}") from exc

        paths = list(
            iter_check_paths(
                collection=collection,
                sample=options["sample"],
                inflections=options["inflections"],
            )
        )
        if not paths:
            raise CommandError("There is nothing to check - is the database empty?")

        self.stdout.write(f"Comparing {len(paths):,} paths ...")
        timeout = options["timeout"]
        differences = []
        checked = 0

        def check(path):
            legacy = _fetch(legacy_base + path, timeout)
            new = _fetch(new_base + path, timeout)
            return compare(path, legacy, new, legacy_base=legacy_base)

        stop_after = options["stop_after"]
        workers = options["workers"]
        # Submit in batches rather than mapping the whole list: pool.map queues
        # every path up front, so --stop-after would still fetch all of them.
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for batch in _batched(paths, workers * 8):
                for difference in pool.map(check, batch):
                    checked += 1
                    if difference is not None:
                        differences.append(difference)
                    if checked % 5000 == 0:
                        self.stdout.write(f"  {checked:,} checked, {len(differences)} differing")
                if stop_after and len(differences) >= stop_after:
                    self.stdout.write(f"Stopping after {len(differences)} difference(s).")
                    break

        def is_known(difference):
            return base_path(difference.path) in known_paths

        if options["out"]:
            with open(options["out"], "w", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(
                    ["path", "legacy_status", "new_status", "legacy", "new", "reason", "known"]
                )
                writer.writerows(d.as_row() + ["yes" if is_known(d) else ""] for d in differences)
            self.stdout.write(f"Wrote {len(differences)} difference(s) to {options['out']}")

        errors = [d for d in differences if d.is_error]
        known = [d for d in differences if not d.is_error and is_known(d)]
        real = [d for d in differences if not d.is_error and not is_known(d)]

        for difference in real[:20]:
            self.stdout.write(f"  {difference.path}: {difference.reason}")
            self.stdout.write(f"      legacy: {difference.legacy[:120]}")
            self.stdout.write(f"      new:    {difference.new[:120]}")

        if known:
            self.stdout.write(
                f"{len(known)} path(s) differ on ARKs the import already reported, and are "
                "not counted against the cutover."
            )

        if errors:
            self.stdout.write(
                self.style.WARNING(
                    f"{len(errors)} path(s) could not be fetched from one side and prove nothing "
                    "either way — re-run them, and lower --workers if the host ran out of sockets."
                )
            )
            for difference in errors[:5]:
                self.stdout.write(f"  {difference.path}: {difference.legacy or difference.new}")

        if real:
            raise CommandError(
                f"{len(real)} of {checked:,} paths differ. Do not flip the vhost yet."
            )
        if errors:
            raise CommandError(
                f"{len(errors)} of {checked:,} paths could not be checked. Re-run before cutting over."
            )
        if known:
            self.stdout.write(
                self.style.SUCCESS(
                    f"All {checked:,} paths resolve identically apart from {len(known)} "
                    "already reported by the import. Safe to cut over."
                )
            )
            return
        self.stdout.write(
            self.style.SUCCESS(f"All {checked:,} paths resolve identically. Safe to cut over.")
        )


def _batched(items, size):
    for start in range(0, len(items), size):
        yield items[start : start + size]


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Compare the redirect itself rather than wherever it points."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def _fetch(url: str, timeout: int) -> tuple[int, str]:
    """Return ``(status, target)`` where target is the Location or the body."""
    try:
        with _OPENER.open(url, timeout=timeout) as response:
            status = response.status
            if status in BODY_STATUSES:
                return status, response.read(65536).decode("utf-8", "replace").strip()
            return status, response.headers.get("Location", "")
    except urllib.error.HTTPError as exc:
        if exc.code in (301, 302, 303, 307, 308):
            return exc.code, exc.headers.get("Location", "")
        return exc.code, ""
    except Exception as exc:  # network trouble is itself a difference worth seeing
        return 0, f"error: {exc}"
