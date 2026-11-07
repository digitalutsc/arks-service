"""
Bulk binding from a CSV.

Staff mint a batch, download a template with the new ARKs already filled in,
add whatever columns the collection needs, and upload it. Every column becomes
an element; nothing is special-cased except the ``Ark_ID`` column itself.

The whole file is validated before a single row is written. The legacy version
posted one row at a time from the browser, so a bad row — or a closed tab — left
the collection half-updated with no record of where it stopped.
"""

from __future__ import annotations

import csv
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field

from django.conf import settings
from django.db import transaction
from django.db.models import Q

from core.arkpath import parse_ark_path
from core.models import Ark, Binding, Collection
from core.search import ARK_ID_COLUMN
from core.services import bulk_upsert_bindings, qualifier_problem

#: Columns offered in the fill-in template after minting.
TEMPLATE_COLUMNS = ["URL", "PID", "LOCAL_ID", "COLLECTION"]

#: ARK names looked up per round trip. Bounds both the SQL IN-list and the
#: memory an upload uses, whatever the size of the collection.
LOOKUP_CHUNK = 2000

#: Rows validated between two progress reports.
CHECK_EVERY = 1000

#: Row statuses reported back to the operator. A row is ``ok`` only while the
#: file is being checked; once the file has been applied it is ``bound``,
#: ``unchanged`` or ``minted``, and stays ``ok`` only when another row failed
#: and nothing was written.
STATUS_OK = "ok"
STATUS_MINTED = "minted"
STATUS_ERROR = "error"
STATUS_BOUND = "bound"
STATUS_UNCHANGED = "unchanged"

#: Left on the valid rows of a file that failed as a whole.
NOT_APPLIED_MESSAGE = "Not applied: another row in the file failed."

#: Order the per-row message lists outcomes in.
OUTCOME_ORDER = ("created", "replaced", "unchanged")


class BulkBindError(Exception):
    """The file as a whole cannot be processed."""


@dataclass
class RowResult:
    number: int
    ark_id: str
    status: str
    message: str = ""


@dataclass
class BulkBindResult:
    created: int = 0
    updated: int = 0
    minted: int = 0
    rows: list[RowResult] = field(default_factory=list)

    @property
    def errors(self) -> list[RowResult]:
        return [row for row in self.rows if row.status == STATUS_ERROR]

    @property
    def failed(self) -> int:
        return len(self.errors)

    @property
    def ok(self) -> bool:
        return self.failed == 0


def template_columns(collection: Collection | None = None) -> list[str]:
    """
    The element columns offered for ``collection``: its first redirect element
    leads, then the conventional ones. Unchanged for the default (``URL`` first).
    """
    lead = collection.redirect_element_list[:1] if collection is not None else []
    return [*lead, *(name for name in TEMPLATE_COLUMNS if name not in lead)]


def template_csv(arks: Iterable[Ark], collection: Collection | None = None) -> Iterator[list[str]]:
    """The fill-in template offered straight after minting."""
    columns = template_columns(collection)
    yield [ARK_ID_COLUMN, *columns]
    for ark in arks:
        yield [ark.name, *([""] * len(columns))]


def _read(handle) -> tuple[list[str], list[dict[str, str]]]:
    reader = csv.DictReader(handle)
    if not reader.fieldnames:
        raise BulkBindError("The file is empty.")

    fieldnames = [(name or "").strip() for name in reader.fieldnames]
    if not any(name.lower() == ARK_ID_COLUMN.lower() for name in fieldnames):
        raise BulkBindError(
            f"The file needs an {ARK_ID_COLUMN!r} column; found: {', '.join(fieldnames) or 'nothing'}."
        )

    rows = []
    for raw in reader:
        rows.append({(key or "").strip(): (value or "").strip() for key, value in raw.items()})
        if len(rows) > settings.BULK_BIND_MAX_ROWS:
            raise BulkBindError(
                f"The file has more than {settings.BULK_BIND_MAX_ROWS} rows. "
                "Split it into smaller uploads."
            )
    if not rows:
        raise BulkBindError("The file has a header but no rows.")
    return fieldnames, rows


def _ark_column(fieldnames: list[str]) -> str:
    return next(name for name in fieldnames if name.lower() == ARK_ID_COLUMN.lower())


def _ark_names(raw: str) -> set[str]:
    """
    The bare ARKs a row may refer to, without its qualifier.

    Two for ``61220/utsc1.pdf``: an ARK of that name, or ``61220/utsc1`` when it
    is the variant ``.pdf`` of the object, as export writes it.
    """
    parsed = parse_ark_path(f"ark:/{(raw or '').strip().lstrip('/')}")
    if parsed is None or not parsed.identifier:
        return set()
    variant = parsed.object_variant()
    return {parsed.name} | ({variant.name} if variant is not None else set())


def _lookup_arks(collection: Collection, names: set[str]) -> dict[str, int]:
    """Resolve ARK names to primary keys, in bounded batches."""
    found: dict[str, int] = {}
    identifiers = sorted({name.partition("/")[2] for name in names if name})
    for start in range(0, len(identifiers), LOOKUP_CHUNK):
        chunk = identifiers[start : start + LOOKUP_CHUNK]
        for pk, naan, identifier in collection.arks.filter(identifier__in=chunk).values_list(
            "id", "naan", "identifier"
        ):
            found[f"{naan}/{identifier}"] = pk
    return found


@transaction.atomic
def apply_csv(
    collection: Collection,
    handle,
    *,
    mint_missing: bool = False,
    purge_first: bool = False,
    user=None,
    progress=None,
) -> BulkBindResult:
    """
    Apply a CSV to ``collection``.

    Returns a :class:`BulkBindResult`. If any row failed, nothing is written at
    all — the transaction is rolled back and the result reports every problem so
    the whole file can be fixed in one pass.

    ``progress(phase, done, total)``, when given, is told where the work is:
    ``reading`` (total unknown), ``checking`` rows, ``minting`` blank rows,
    ``purging``, then ``writing`` bindings. It is cosmetic; the CLI passes none.
    """
    from minting.minter import mint  # imported here to avoid a circular import

    report = progress or _no_progress
    report("reading", 0, None)
    fieldnames, rows = _read(handle)
    total_rows = len(rows)
    report("checking", 0, total_rows)
    ark_column = _ark_column(fieldnames)
    element_columns = [name for name in fieldnames if name != ark_column and name]

    # Resolve only the ARKs the file actually names. Loading the whole
    # collection to look up a handful of rows cost gigabytes on a large
    # collection and grew with the collection rather than the upload.
    wanted_names = set().union(*(_ark_names(row.get(ark_column, "")) for row in rows))
    known = _lookup_arks(collection, wanted_names)

    result = BulkBindResult()
    planned: dict[tuple[int, str, str], str] = {}
    # Which planned keys each row contributed, so the outcome of the write can
    # be folded back onto the row afterwards.
    row_keys: dict[int, list[tuple[int, str, str]]] = {}
    # Every (ark, qualifier) the file names, whether or not it binds anything.
    # Purge works from this, so a row with all cells blank still clears what it
    # names, and a row naming a qualifier never touches the rest of the ARK.
    named: set[tuple[int, str]] = set()
    seen: set[tuple[str, str, str]] = set()
    to_mint: list[int] = []

    for number, row in enumerate(rows, start=2):  # row 1 is the header
        checked = number - 2
        if checked and checked % CHECK_EVERY == 0:
            report("checking", checked, total_rows)
        raw_ark = (row.get(ark_column) or "").strip()

        if not raw_ark:
            if not mint_missing:
                result.rows.append(
                    RowResult(
                        number,
                        "",
                        STATUS_ERROR,
                        "No Ark_ID. Tick 'mint new ARKs for blank rows' to mint one.",
                    )
                )
                continue
            to_mint.append(number)
            # Reported as an error until the mint actually happens below; a file
            # that fails elsewhere must not claim rows were minted.
            result.rows.append(
                RowResult(number, "", STATUS_ERROR, "Not minted: another row in the file failed.")
            )
            continue

        parsed = parse_ark_path(f"ark:/{raw_ark}")
        if parsed is None or not parsed.identifier:
            result.rows.append(RowResult(number, raw_ark, STATUS_ERROR, "Not a valid ARK."))
            continue

        ark_pk = known.get(parsed.name)
        if ark_pk is None and (variant := parsed.object_variant()) is not None:
            # A variant of the object, as export writes it: '61220/utsc1.pdf'.
            ark_pk = known.get(variant.name)
            if ark_pk is not None:
                parsed = variant
        if ark_pk is None:
            result.rows.append(
                RowResult(
                    number,
                    raw_ark,
                    STATUS_ERROR,
                    f"{parsed.name} is not an ARK in this collection. Mint it first.",
                )
            )
            continue

        # Checked once the row's reading is settled, so a hyphen in the variant
        # of an object ('utsc1.a-b') is caught too.
        problem = qualifier_problem(parsed.qualifier)
        if problem:
            result.rows.append(RowResult(number, raw_ark, STATUS_ERROR, problem))
            continue

        named.add((ark_pk, parsed.qualifier))

        duplicate = False
        for column in element_columns:
            value = row.get(column, "")
            if value == "":
                continue  # an empty cell leaves any existing value alone
            key = (parsed.name, parsed.qualifier, column.upper())
            if key in seen:
                result.rows.append(
                    RowResult(
                        number,
                        raw_ark,
                        STATUS_ERROR,
                        f"{column.upper()} is set twice for {parsed.name}{parsed.qualifier}.",
                    )
                )
                duplicate = True
                break
            seen.add(key)
            planned[(ark_pk, parsed.qualifier, column.upper())] = value
            row_keys.setdefault(number, []).append((ark_pk, parsed.qualifier, column.upper()))

        if not duplicate:
            result.rows.append(RowResult(number, parsed.name + parsed.qualifier, STATUS_OK))

    report("checking", total_rows, total_rows)

    # Mint the blank rows now that the file is known to be well formed. "Well
    # formed" means no row failed for a reason other than awaiting its mint.
    awaiting_mint = set(to_mint)
    blocked = [row for row in result.errors if row.number not in awaiting_mint]
    if to_mint and not blocked:
        report("minting", 0, len(to_mint))
        minted = mint(collection, count=len(to_mint), user=user, enforce_cap=False)
        result.minted = len(minted)
        report("minting", len(minted), len(to_mint))
        by_number = {row.number: row for row in result.rows}
        for number, ark in zip(to_mint, minted, strict=True):
            by_number[number].ark_id = ark.name
            by_number[number].status = STATUS_MINTED
            by_number[number].message = ""
            named.add((ark.pk, ""))
            for column in element_columns:
                value = (rows[number - 2].get(column) or "").strip()
                if value:
                    planned[(ark.pk, "", column.upper())] = value
                    row_keys.setdefault(number, []).append((ark.pk, "", column.upper()))

    if not result.ok:
        # Nothing has been written yet — every row is validated above, and both
        # minting and _write happen below — so this is defence in depth rather
        # than the actual guarantee. It matters if a future change ever writes
        # before validation finishes: returning normally from an atomic block
        # would otherwise commit that partial work.
        transaction.set_rollback(True)
        for row in result.rows:
            if row.status == STATUS_OK:
                row.message = NOT_APPLIED_MESSAGE
        return result

    if purge_first:
        report("purging", 0, None)
        _purge(named)

    outcomes: dict[tuple[int, str, str], str] = {}
    _write(planned, result, report, outcomes)
    _stamp(result, row_keys, outcomes, purge_first=purge_first)
    return result


#: Element names a row message lists before summarising the rest as "+N more".
MESSAGE_NAMES = 4


def _names(names: list[str]) -> str:
    """'URL, PID, LOCAL_ID, TITLE +2 more': brief, but says which elements."""
    shown = ", ".join(names[:MESSAGE_NAMES])
    extra = len(names) - MESSAGE_NAMES
    return f"{shown} +{extra} more" if extra > 0 else shown


def _row_message(by_outcome: dict[str, list[str]], *, minted: bool, purged: bool) -> str:
    """
    One line saying what happened to which elements of a row.

    'New ARK minted; bound URL, PID', 'Added PID; replaced URL; LOCAL_ID already
    had this value', 'No change: URL, PID already had these values'.
    """
    every = [name for kind in OUTCOME_ORDER for name in by_outcome.get(kind, [])]
    if minted:
        return (
            f"New ARK minted; bound {_names(every)}" if every else "New ARK minted; nothing bound"
        )
    if purged:
        return (
            f"Removed the old elements; bound {_names(every)}"
            if every
            else "Removed the old elements; nothing bound"
        )
    if not every:
        return "Nothing to bind: every element cell was empty"

    created, replaced = by_outcome.get("created", []), by_outcome.get("replaced", [])
    unchanged = by_outcome.get("unchanged", [])
    kept = ""
    if unchanged:
        value = "this value" if len(unchanged) == 1 else "these values"
        kept = f"{_names(unchanged)} already had {value}"
    if not created and not replaced:
        return f"No change: {kept}"
    parts = []
    if created:
        parts.append(f"added {_names(created)}")
    if replaced:
        parts.append(f"replaced {_names(replaced)}")
    if kept:
        parts.append(kept)
    message = "; ".join(parts)
    return message[0].upper() + message[1:]


def _stamp(result: BulkBindResult, row_keys, outcomes, *, purge_first: bool) -> None:
    """
    Say on each row what happened to which of its elements, once they are written.

    Done after ``_write`` so a row never claims a binding that was rolled back.
    A minted row keeps its status; a checked row becomes ``bound`` when anything
    was created or replaced (or when the row was purged, which is itself a
    change), otherwise ``unchanged``. Element names are listed in the file's
    column order (``_row_message``).
    """
    for row in result.rows:
        if row.status == STATUS_ERROR:
            continue
        by_outcome: dict[str, list[str]] = {}
        for key in row_keys.get(row.number, ()):
            by_outcome.setdefault(outcomes.get(key, "unchanged"), []).append(key[2])
        minted = row.status == STATUS_MINTED
        row.message = _row_message(by_outcome, minted=minted, purged=purge_first and not minted)
        if minted:
            continue
        if purge_first or by_outcome.get("created") or by_outcome.get("replaced"):
            row.status = STATUS_BOUND
        else:
            row.status = STATUS_UNCHANGED


def _no_progress(phase: str, done: int, total: int | None) -> None:
    """The default ``progress`` callback: nobody is watching."""


def _purge(named: set[tuple[int, str]]) -> None:
    """Remove every element under exactly the (ark, qualifier) pairs named."""
    if not named:
        return
    pairs = sorted(named)
    for start in range(0, len(pairs), LOOKUP_CHUNK):
        condition = Q()
        for ark_pk, qualifier in pairs[start : start + LOOKUP_CHUNK]:
            condition |= Q(ark_id=ark_pk, qualifier=qualifier)
        Binding.objects.filter(condition).delete()


def _write(
    planned: dict[tuple[int, str, str], str], result: BulkBindResult, report, outcomes
) -> None:
    result.created, result.updated = bulk_upsert_bindings(
        planned, progress=report, outcomes=outcomes
    )
