"""
Import a legacy ARK database into this system.

Point it at the export a handover actually consists of, or at a restored copy
of it::

    manage.py import_legacy --legacy-dump /srv/ARK_CORE.sql
    manage.py import_legacy --legacy-dump /srv/ARK_CORE.sql --dry-run --report review.csv
    manage.py import_legacy --legacy-url mysql://user:pw@localhost/ark_legacy

Idempotent: re-running updates what changed and leaves everything else alone,
so it can be rehearsed as often as needed before the real cutover.

A handful of legacy rows cannot be carried over exactly — an element that was
uploaded twice under two spellings, a redirect counter for something that was
never an ARK. Those are never dropped silently: ``--report`` writes each one to
a CSV a curator can act on, and ``resolve_diff --known`` reads the same file.
"""

from __future__ import annotations

import csv
from collections import defaultdict
from contextlib import contextmanager

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from core.legacy import (
    REDIRECT_ELEMENT,
    DumpFormatError,
    LegacyCollection,
    is_circulation,
    is_hold,
    is_reserved,
    open_legacy,
    open_legacy_dump,
    parse_circulation,
    parse_legacy_key,
)
from core.models import Ark, Collection, Organisation, Resolution
from core.services import bulk_upsert_bindings, normalise_element_name
from minting.noid import TemplateError, parse_template, xdig2n

#: Rows per round trip when writing in bulk.
BATCH_SIZE = 2000

#: Legacy rows handled per batch. Each batch is its own unit of work, so memory
#: stays flat however large the source table is.
IMPORT_CHUNK = 20_000


def _batched(iterable, size, key=None):
    """
    Yield lists of at least ``size`` items from ``iterable``.

    With ``key``, a batch is only closed when the key changes, so everything
    belonging to one ARK is decided together however the chunk size falls.
    Legacy tables are read in key order, which puts an ARK's rows side by side.
    """
    batch = []
    current = object()
    for item in iterable:
        if len(batch) >= size and (key is None or key(item) != current):
            yield batch
            batch = []
        batch.append(item)
        if key is not None:
            current = key(item)
    if batch:
        yield batch


#: Columns of the review CSV. ``resolve_diff --known`` reads ``ark_path``.
REPORT_FIELDS = ["reason", "table", "ark_path", "element", "value"]


class _Report:
    """
    The rows that could not be carried over exactly as legacy held them.

    Written as the import goes rather than at the end, so a dry run produces
    the same file as the real thing — reading it is the point of a dry run.
    """

    def __init__(self, path: str | None, writer):
        self.path = path
        self.counts: defaultdict[str, int] = defaultdict(int)
        self._writer = writer

    def add(self, reason: str, table: str, ark_path: str, element: str, value: str):
        self.counts[reason] += 1
        if self._writer is not None:
            self._writer.writerow([reason, table, ark_path, element, value])


@contextmanager
def _open_report(path: str | None):
    """A report that writes to ``path``, or one that quietly counts."""
    if not path:
        yield _Report(None, None)
        return
    with open(path, "w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(REPORT_FIELDS)
        yield _Report(path, writer)


class Command(BaseCommand):
    help = "Import collections, ARKs and bindings from a legacy ARK database or export."

    def add_arguments(self, parser):
        parser.add_argument(
            "--legacy-dump",
            help="Path to a mysqldump or phpMyAdmin export (.sql or .sql.gz).",
        )
        parser.add_argument(
            "--legacy-url",
            help="Database URL of a live legacy database, e.g. mysql://user:pw@host/ark",
        )
        parser.add_argument(
            "--encoding",
            default="utf-8",
            help="Character encoding of the export file (default: utf-8).",
        )
        parser.add_argument(
            "--table",
            action="append",
            dest="tables",
            help="Import only this collection table (repeatable). Default: all.",
        )
        parser.add_argument(
            "--collection-name",
            help="Name to give the imported collection, instead of the legacy table name.",
        )
        parser.add_argument(
            "--report",
            help="Write rows that could not be carried over verbatim to this CSV.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be imported without writing anything.",
        )

    def handle(self, *args, **options):
        legacy_url = options["legacy_url"]
        legacy_dump = options["legacy_dump"]
        if bool(legacy_url) == bool(legacy_dump):
            raise CommandError(
                "Give exactly one of --legacy-dump (an export file) or --legacy-url "
                "(a live database)."
            )

        dry_run = options["dry_run"]
        only_tables = options.get("tables")
        collection_name = options.get("collection_name")
        verbosity = options.get("verbosity", 1)

        totals = defaultdict(int)
        tables: list[str] = []

        with _open_report(options.get("report")) as report:
            try:
                if legacy_dump:
                    legacy_cm = open_legacy_dump(legacy_dump, encoding=options["encoding"])
                else:
                    legacy_cm = open_legacy(legacy_url)
            except (ValueError, DumpFormatError) as exc:
                raise CommandError(str(exc)) from exc

            try:
                with legacy_cm as reader:
                    try:
                        tables = reader.collection_tables()
                    except DumpFormatError as exc:
                        raise CommandError(str(exc)) from exc
                    except Exception as exc:
                        raise CommandError(f"Could not read the legacy database: {exc}") from exc

                    if only_tables:
                        missing = set(only_tables) - set(tables)
                        if missing:
                            raise CommandError(
                                f"No such collection table(s): {', '.join(sorted(missing))}"
                            )
                        tables = [t for t in tables if t in only_tables]

                    if collection_name and len(tables) > 1:
                        raise CommandError(
                            "--collection-name names one collection, but this source holds "
                            f"{len(tables)}: {', '.join(tables)}. Add --table to pick one."
                        )

                    with transaction.atomic():
                        self._import_organisation(reader, totals)
                        for table in tables:
                            self._import_collection(
                                reader, table, collection_name, totals, report, verbosity
                            )

                        if dry_run:
                            transaction.set_rollback(True)
            except DumpFormatError as exc:
                raise CommandError(str(exc)) from exc

        if verbosity:
            self._report(totals, tables, dry_run, report)

    # --- import -----------------------------------------------------------

    def _import_organisation(self, reader, totals):
        settings_rows = reader.system_settings()
        if not settings_rows:
            return
        organisation = Organisation.load()
        organisation.name = settings_rows.get("Organization Name", organisation.name)
        organisation.website = settings_rows.get("Organization Website", organisation.website)
        organisation.save()
        totals["organisation"] = 1

    def _import_collection(self, reader, table, collection_name, totals, report, verbosity):
        # Two passes: the reserved rows define the collection and must be known
        # before any ARK is written, then the element rows stream through in
        # batches. Holding the whole table in memory needed 4-5 GB per million
        # ARKs, which is what made a large import impossible rather than slow.
        legacy = LegacyCollection(table=table)
        for key, value in reader.rows(table):
            if is_reserved(key):
                legacy.config[key] = value

        collection = self._upsert_collection(legacy, collection_name, totals)

        # Redirect counters are held back until the whole table has been read.
        # A counter can appear before the row that proves its ARK exists, and
        # some belong to no ARK at all.
        counters: dict[tuple[str, str], int] = {}

        seen = 0
        for batch in _batched(self._elements(reader, table), IMPORT_CHUNK, key=lambda row: row[0]):
            self._upsert_arks(collection, legacy, batch, counters, totals, report)
            seen += len(batch)
            if verbosity >= 2:
                self.stdout.write(f"  {table}: {seen:,} element rows")

        self._write_counters(collection, counters, totals, report)

        if verbosity and not verbosity >= 2:
            self.stdout.write(f"  {table}: {seen:,} element rows")

    def _elements(self, reader, table):
        """Yield the (ark, qualifier, element, value) tuples worth importing."""
        for key, value in reader.rows(table):
            if is_reserved(key):
                continue
            parsed = parse_legacy_key(key)
            if parsed is None:
                continue
            ark_name, qualifier, element = parsed
            # A hold says nothing this system keeps: every identifier in a
            # long-term minter has one. A circulation record says when the
            # identifier was minted, which is worth keeping.
            if is_hold(element):
                continue
            yield ark_name, qualifier, element, value

    def _upsert_collection(self, legacy: LegacyCollection, name: str | None, totals) -> Collection:
        if not legacy.naan:
            raise CommandError(
                f"Cannot import {legacy.table!r}: it has no ':/naan' row. Every ARK needs a "
                "NAAN, and without one nothing in this collection would resolve."
            )

        name = name or legacy.table
        clash = (
            Collection.objects.filter(naan=legacy.naan, prefix=legacy.prefix)
            .exclude(name=name)
            .first()
        )
        if clash is not None:
            raise CommandError(
                f"Cannot import {legacy.table!r}: prefix {legacy.prefix!r} is already used "
                f"under NAAN {legacy.naan} by collection {clash.name!r}. A prefix must be "
                "unique within its NAAN."
            )

        collection, created = Collection.objects.update_or_create(
            name=name,
            defaults={
                "prefix": legacy.prefix,
                "naan": legacy.naan,
                "naa": legacy.naa,
                "template": legacy.template,
                "term": legacy.term,
            },
        )
        totals["collections_created" if created else "collections_updated"] += 1
        return collection

    def _upsert_arks(self, collection, legacy, elements, counters, totals, report):
        """
        Write one batch of a collection's ARKs and bindings.

        Everything is done in bulk. A row-at-a-time ``update_or_create`` needs
        two queries per element, which for a 100k-ARK collection is well over
        800k round trips — seven minutes on a laptop, and far worse across a
        network to the production database.
        """
        try:
            mask = parse_template(collection.full_template).mask
        except TemplateError:
            mask = legacy.mask or ""

        ark_pks = self._create_missing_arks(collection, elements, mask, totals)
        self._write_bindings(collection, elements, ark_pks, counters, totals, report)

    def _create_missing_arks(self, collection, elements, mask, totals) -> dict[str, int]:
        """Ensure every ARK mentioned exists; return {key as written: pk}."""
        # A key is usually "<naan>/<identifier>", but some legacy rows carry the
        # identifier alone. Those belong to this collection's NAAN; treating the
        # whole string as a NAAN would create a junk ARK and silently strand
        # every binding attached to it.
        wanted: dict[str, tuple[str, str]] = {}
        minted: dict[str, object] = {}
        for ark_name, _, element, value in elements:
            if normalise_element_name(element) == REDIRECT_ELEMENT:
                # The legacy resolver counted every request it was given,
                # including paths that were never ARKs. A counter alone is no
                # evidence that an identifier exists.
                continue
            wanted[ark_name] = _split_ark_name(ark_name, collection.naan)
            if is_circulation(element):
                when = parse_circulation(value)
                if when is not None:
                    minted[ark_name] = when

        # Look up only the identifiers this batch mentions. Reading the whole
        # collection here made the import quadratic — every batch re-read every
        # ARK already imported — and put the collection in memory besides.
        existing = _existing_arks(collection, {pair[1] for pair in wanted.values()})
        prefix_length = len(collection.prefix)
        now = timezone.now()

        to_create, planned = [], set()
        for ark_name, pair in sorted(wanted.items()):
            if pair in existing or pair in planned:
                continue
            planned.add(pair)
            naan, identifier = pair
            when = minted.get(ark_name)
            if when is not None:
                totals["minted_at_recovered"] += 1
            to_create.append(
                Ark(
                    collection=collection,
                    naan=naan,
                    identifier=identifier,
                    sequence=_decode_sequence(identifier, prefix_length, mask),
                    minted_at=when or now,
                )
            )
        if to_create:
            Ark.objects.bulk_create(to_create, batch_size=BATCH_SIZE)
            totals["arks_created"] += len(to_create)
            existing = _existing_arks(collection, {pair[1] for pair in wanted.values()})
        return {name: existing[pair] for name, pair in wanted.items() if pair in existing}

    def _write_bindings(self, collection, elements, ark_pks, counters, totals, report):
        # Collapse to one row per (ark, qualifier, element) so the unique
        # constraint is never violated. Legacy could hold the same element under
        # two spellings — thousands arrived through uploads saved with Windows
        # line endings, whose names ended in a carriage return. The canonical
        # spelling wins and the other is reported rather than lost quietly.
        wanted: dict[tuple[int, str, str], str] = {}
        canonical: dict[tuple[int, str, str], bool] = {}
        paths: dict[tuple[int, str, str], str] = {}

        for ark_name, qualifier, element, value in elements:
            if is_circulation(element):
                continue
            name = normalise_element_name(element)
            if name == REDIRECT_ELEMENT:
                counters[(ark_name, qualifier)] = _to_int(value)
                continue

            ark_pk = ark_pks.get(ark_name)
            if ark_pk is None:  # pragma: no cover - defensive
                continue

            key = (ark_pk, qualifier, name)
            path = _ark_path(ark_name, qualifier, collection.naan)
            is_canonical = element == name
            if key in wanted:
                loser = value if canonical[key] and not is_canonical else wanted[key]
                report.add("duplicate-element", collection.name, path, name, loser)
                totals["elements_merged"] += 1
                if canonical[key] and not is_canonical:
                    continue
            wanted[key] = value or ""
            canonical[key] = is_canonical
            paths[key] = path

        created, updated = bulk_upsert_bindings(wanted)
        totals["bindings_created"] += created
        totals["bindings_updated"] += updated

    def _write_counters(self, collection, counters, totals, report):
        """Turn the legacy redirect counters into resolutions, once."""
        if not counters:
            return
        pairs = {ark_name: _split_ark_name(ark_name, collection.naan) for ark_name, _ in counters}
        found = _existing_arks(collection, {pair[1] for pair in pairs.values()})

        resolved: dict[tuple[int, str], int] = {}
        for (ark_name, qualifier), count in counters.items():
            ark_pk = found.get(pairs[ark_name])
            if ark_pk is None:
                totals["redirects_skipped"] += 1
                report.add(
                    "redirect-for-unknown-ark",
                    collection.name,
                    _ark_path(ark_name, qualifier, collection.naan),
                    REDIRECT_ELEMENT,
                    str(count),
                )
                continue
            resolved[(ark_pk, qualifier)] = count

        now = timezone.now()
        existing = {
            (ark_id, qualifier): pk
            for pk, ark_id, qualifier in Resolution.objects.filter(
                ark__collection=collection
            ).values_list("id", "ark_id", "qualifier")
        }
        to_create, to_update = [], []
        for (ark_pk, qualifier), count in resolved.items():
            pk = existing.get((ark_pk, qualifier))
            if pk is None:
                to_create.append(
                    Resolution(ark_id=ark_pk, qualifier=qualifier, count=count, last_at=now)
                )
            else:
                to_update.append(Resolution(id=pk, count=count, last_at=now))

        if to_create:
            Resolution.objects.bulk_create(to_create, batch_size=BATCH_SIZE)
        if to_update:
            Resolution.objects.bulk_update(to_update, ["count", "last_at"], batch_size=BATCH_SIZE)
        totals["resolutions"] += len(to_create) + len(to_update)

    # --- output -----------------------------------------------------------

    def _report(self, totals, tables, dry_run, report):
        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN - nothing was written"))
        self.stdout.write(f"Collections read: {', '.join(tables) or '(none)'}")
        for label in (
            "collections_created",
            "collections_updated",
            "arks_created",
            "minted_at_recovered",
            "bindings_created",
            "bindings_updated",
            "elements_merged",
            "resolutions",
            "redirects_skipped",
        ):
            self.stdout.write(f"  {label.replace('_', ' '):24} {totals.get(label, 0)}")

        # How many identifiers came across with no metadata is worth knowing, but
        # it is a question about the result rather than about the import, and
        # `refresh_collection_stats` (and the collection page) already answers it
        # from committed, analysed data. Asking it
        # here means an anti-join over every binding inside the write
        # transaction, which on a rehearsed import is minutes of nothing.
        if not dry_run:
            self.stdout.write(
                "Run `refresh_collection_stats` (or open the collection page) for what "
                "the collections now hold."
            )

        if report.path:
            self.stdout.write(f"Rows needing review: {report.path}")
        elif report.counts:
            self.stdout.write(
                self.style.WARNING(
                    "Some rows could not be carried over verbatim. Re-run with --report "
                    "FILE to see which."
                )
            )


def _existing_arks(collection, identifiers: set[str]) -> dict[tuple[str, str], int]:
    """Resolve just these identifiers to primary keys, in bounded batches."""
    found: dict[tuple[str, str], int] = {}
    ordered = sorted(identifiers)
    for start in range(0, len(ordered), BATCH_SIZE):
        chunk = ordered[start : start + BATCH_SIZE]
        for pk, naan, identifier in collection.arks.filter(identifier__in=chunk).values_list(
            "id", "naan", "identifier"
        ):
            found[(naan, identifier)] = pk
    return found


def _split_ark_name(name: str, default_naan: str) -> tuple[str, str]:
    """Split a legacy key's ARK part, falling back to the collection's NAAN."""
    if "/" in name:
        naan, _, identifier = name.partition("/")
        return naan, identifier
    return default_naan, name


def _ark_path(ark_name: str, qualifier: str, default_naan: str) -> str:
    """The path this row is about, as someone would request it."""
    naan, identifier = _split_ark_name(ark_name, default_naan)
    return f"/ark:/{naan}/{identifier}{qualifier}"


def _decode_sequence(identifier: str, prefix_length: int, mask: str) -> int | None:
    """The counter value that would have produced this identifier, if any."""
    if not mask:
        return None
    try:
        return xdig2n(identifier[prefix_length:], mask)
    except ValueError:
        # Hand-made or otherwise off-template; it still imports, it just does
        # not tell us where to resume minting.
        return None


def _to_int(value) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return 0
