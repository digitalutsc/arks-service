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
from core.services import bulk_upsert_bindings

#: Columns offered in the fill-in template after minting.
TEMPLATE_COLUMNS = ["URL", "PID", "LOCAL_ID", "COLLECTION"]

#: ARK names looked up per round trip. Bounds both the SQL IN-list and the
#: memory an upload uses, whatever the size of the collection.
LOOKUP_CHUNK = 2000

#: Row statuses reported back to the operator.
STATUS_OK = "ok"
STATUS_MINTED = "minted"
STATUS_ERROR = "error"


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


def template_csv(arks: Iterable[Ark]) -> Iterator[list[str]]:
    """The fill-in template offered straight after minting."""
    yield [ARK_ID_COLUMN, *TEMPLATE_COLUMNS]
    for ark in arks:
        yield [ark.name, *([""] * len(TEMPLATE_COLUMNS))]


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


def _ark_name(raw: str) -> str:
    """The bare ARK a row refers to, without its qualifier."""
    parsed = parse_ark_path(f"ark:/{(raw or '').strip().lstrip('/')}")
    return parsed.name if parsed and parsed.identifier else ""


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
) -> BulkBindResult:
    """
    Apply a CSV to ``collection``.

    Returns a :class:`BulkBindResult`. If any row failed, nothing is written at
    all — the transaction is rolled back and the result reports every problem so
    the whole file can be fixed in one pass.
    """
    from minting.minter import mint  # imported here to avoid a circular import

    fieldnames, rows = _read(handle)
    ark_column = _ark_column(fieldnames)
    element_columns = [name for name in fieldnames if name != ark_column and name]

    # Resolve only the ARKs the file actually names. Loading the whole
    # collection to look up a handful of rows cost gigabytes on a large
    # collection and grew with the collection rather than the upload.
    wanted_names = {name for name in (_ark_name(row.get(ark_column, "")) for row in rows) if name}
    known = _lookup_arks(collection, wanted_names)

    result = BulkBindResult()
    planned: dict[tuple[int, str, str], str] = {}
    # Every (ark, qualifier) the file names, whether or not it binds anything.
    # Purge works from this, so a row with all cells blank still clears what it
    # names, and a row naming a qualifier never touches the rest of the ARK.
    named: set[tuple[int, str]] = set()
    seen: set[tuple[str, str, str]] = set()
    to_mint: list[int] = []

    for number, row in enumerate(rows, start=2):  # row 1 is the header
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

        if not duplicate:
            result.rows.append(RowResult(number, parsed.name + parsed.qualifier, STATUS_OK))

    # Mint the blank rows now that the file is known to be well formed. "Well
    # formed" means no row failed for a reason other than awaiting its mint.
    blocked = [row for row in result.errors if row.number not in set(to_mint)]
    if to_mint and not blocked:
        minted = mint(collection, count=len(to_mint), user=user)
        result.minted = len(minted)
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

    if not result.ok:
        # Nothing has been written yet — every row is validated above, and both
        # minting and _write happen below — so this is defence in depth rather
        # than the actual guarantee. It matters if a future change ever writes
        # before validation finishes: returning normally from an atomic block
        # would otherwise commit that partial work.
        transaction.set_rollback(True)
        return result

    if purge_first:
        _purge(named)

    _write(planned, result)
    return result


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


def _write(planned: dict[tuple[int, str, str], str], result: BulkBindResult) -> None:
    result.created, result.updated = bulk_upsert_bindings(planned)
