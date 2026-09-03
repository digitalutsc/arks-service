"""
Import a legacy ARK database into this system.

Point it at a restored copy of the production dump::

    manage.py import_legacy --legacy-url mysql://user:pw@localhost/ark_legacy
    manage.py import_legacy --legacy-url mysql://... --dry-run

Idempotent: re-running updates what changed and leaves everything else alone,
so it can be rehearsed as often as needed before the real cutover.
"""

from __future__ import annotations

from collections import defaultdict

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from core.legacy import (
    REDIRECT_ELEMENT,
    LegacyCollection,
    is_bookkeeping,
    is_reserved,
    open_legacy,
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


def _batched(iterable, size):
    """Yield lists of at most ``size`` items from ``iterable``."""
    batch = []
    for item in iterable:
        batch.append(item)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch


class Command(BaseCommand):
    help = "Import collections, ARKs and bindings from a legacy ARK database."

    def add_arguments(self, parser):
        parser.add_argument(
            "--legacy-url",
            required=True,
            help="Database URL of the legacy database, e.g. mysql://user:pw@host/ark",
        )
        parser.add_argument(
            "--table",
            action="append",
            dest="tables",
            help="Import only this collection table (repeatable). Default: all.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be imported without writing anything.",
        )

    def handle(self, *args, **options):
        legacy_url = options["legacy_url"]
        dry_run = options["dry_run"]
        only_tables = options.get("tables")
        verbosity = options.get("verbosity", 1)

        totals = defaultdict(int)
        try:
            legacy_cm = open_legacy(legacy_url)
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        with legacy_cm as reader:
            try:
                tables = reader.collection_tables()
            except Exception as exc:
                raise CommandError(f"Could not read the legacy database: {exc}") from exc

            if only_tables:
                missing = set(only_tables) - set(tables)
                if missing:
                    raise CommandError(f"No such collection table(s): {', '.join(sorted(missing))}")
                tables = [t for t in tables if t in only_tables]

            with transaction.atomic():
                self._import_organisation(reader, totals)
                for table in tables:
                    self._import_collection(reader, table, totals, verbosity)

                if dry_run:
                    transaction.set_rollback(True)

        if verbosity:
            self._report(totals, tables, dry_run)

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

    def _import_collection(self, reader, table, totals, verbosity):
        # Two passes: the reserved rows define the collection and must be known
        # before any ARK is written, then the element rows stream through in
        # batches. Holding the whole table in memory needed 4-5 GB per million
        # ARKs, which is what made a large import impossible rather than slow.
        legacy = LegacyCollection(table=table)
        for key, value in reader.rows(table):
            if is_reserved(key):
                legacy.config[key] = value

        collection = self._upsert_collection(legacy, totals)

        seen = 0
        for batch in _batched(self._elements(reader, table), IMPORT_CHUNK):
            self._upsert_arks(collection, legacy, batch, totals)
            seen += len(batch)
            if verbosity >= 2:
                self.stdout.write(f"  {table}: {seen:,} element rows")

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
            if is_bookkeeping(element):
                continue
            yield ark_name, qualifier, element, value

    def _upsert_collection(self, legacy: LegacyCollection, totals) -> Collection:
        if not legacy.naan:
            raise CommandError(
                f"Cannot import {legacy.table!r}: it has no ':/naan' row. Every ARK needs a "
                "NAAN, and without one nothing in this collection would resolve."
            )

        clash = (
            Collection.objects.filter(naan=legacy.naan, prefix=legacy.prefix)
            .exclude(name=legacy.table)
            .first()
        )
        if clash is not None:
            raise CommandError(
                f"Cannot import {legacy.table!r}: prefix {legacy.prefix!r} is already used "
                f"under NAAN {legacy.naan} by collection {clash.name!r}. A prefix must be "
                "unique within its NAAN."
            )

        collection, created = Collection.objects.update_or_create(
            name=legacy.table,
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

    def _upsert_arks(self, collection, legacy, elements, totals):
        """
        Write one collection's ARKs, bindings and counters.

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
        self._write_bindings(collection, elements, ark_pks, totals)

    def _create_missing_arks(self, collection, elements, mask, totals) -> dict[str, int]:
        """Ensure every ARK mentioned exists; return {key as written: pk}."""
        # A key is usually "<naan>/<identifier>", but some legacy rows carry the
        # identifier alone. Those belong to this collection's NAAN; treating the
        # whole string as a NAAN would create a junk ARK and silently strand
        # every binding attached to it.
        wanted = {
            ark_name: _split_ark_name(ark_name, collection.naan) for ark_name, _, _, _ in elements
        }

        # Look up only the identifiers this batch mentions. Reading the whole
        # collection here made the import quadratic — every batch re-read every
        # ARK already imported — and put the collection in memory besides.
        existing = _existing_arks(collection, {pair[1] for pair in wanted.values()})
        prefix_length = len(collection.prefix)

        to_create, planned = [], set()
        for _, pair in sorted(wanted.items()):
            if pair in existing or pair in planned:
                continue
            planned.add(pair)
            naan, identifier = pair
            to_create.append(
                Ark(
                    collection=collection,
                    naan=naan,
                    identifier=identifier,
                    sequence=_decode_sequence(identifier, prefix_length, mask),
                )
            )
        if to_create:
            Ark.objects.bulk_create(to_create, batch_size=BATCH_SIZE)
            totals["arks_created"] += len(to_create)
            existing = _existing_arks(collection, {pair[1] for pair in wanted.values()})
        return {name: existing[pair] for name, pair in wanted.items() if pair in existing}

    def _write_bindings(self, collection, elements, ark_pks, totals):
        # Collapse to one row per (ark, qualifier, element); the last value in
        # the legacy table wins, and the unique constraint is never violated.
        wanted: dict[tuple[int, str, str], str] = {}
        counters: dict[tuple[int, str], int] = {}
        for ark_name, qualifier, element, value in elements:
            ark_pk = ark_pks.get(ark_name)
            if ark_pk is None:  # pragma: no cover - defensive
                continue
            name = normalise_element_name(element)
            if name == REDIRECT_ELEMENT:
                counters[(ark_pk, qualifier)] = _to_int(value)
            else:
                wanted[(ark_pk, qualifier, name)] = value or ""

        created, updated = bulk_upsert_bindings(wanted)
        totals["bindings_created"] += created
        totals["bindings_updated"] += updated

        self._write_counters(collection, counters, timezone.now(), totals)

    def _write_counters(self, collection, counters, now, totals):
        existing = {
            (ark_id, qualifier): pk
            for pk, ark_id, qualifier in Resolution.objects.filter(
                ark__collection=collection
            ).values_list("id", "ark_id", "qualifier")
        }
        to_create, to_update = [], []
        for (ark_pk, qualifier), count in counters.items():
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

    def _report(self, totals, tables, dry_run):
        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN - nothing was written"))
        self.stdout.write(f"Collections read: {', '.join(tables) or '(none)'}")
        for label in (
            "collections_created",
            "collections_updated",
            "arks_created",
            "bindings_created",
            "bindings_updated",
            "resolutions",
        ):
            self.stdout.write(f"  {label.replace('_', ' '):24} {totals.get(label, 0)}")


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
