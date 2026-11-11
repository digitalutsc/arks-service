"""
Reading the legacy ARK database.

Legacy kept one table per collection, each a generic key/value store where the
key packed several fields together with tabs::

    :/naa, :/naan, :/template ...             reserved configuration
    61220/utsc1<TAB>URL                       element on the ARK itself
    61220/utsc1<TAB>/page1<TAB>URL            element on a hierarchical part
    61220/utsc1<TAB>/page1<TAB>.png<TAB>URL   ... with a variant
    61220/utsc1<TAB>:/c                       circulation record (when it was minted)
    61220/utsc1<TAB>:/h                       hold marker

Keys are read literally rather than re-derived, so whatever production actually
contains survives the move — including anything the legacy code wrote in a way
its own resolver could not read back.

Two sources are supported. A live database is read over a normal connection;
an export file — what a handover actually consists of — is parsed directly, so
nothing has to be restored into a scratch MySQL server first.

One thing is *not* taken literally: legacy wrote every key and value through
PHP's ``htmlspecialchars``, so an ampersand is stored as ``&amp;``. That is an
artefact of the storage layer rather than something a curator typed, and it is
undone on the way in.
"""

from __future__ import annotations

import gzip
import re
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import unquote, urlparse

from django.utils import timezone

#: Prefix marking a reserved (non-identifier) row.
RESERVED = ":"

#: Element holding an identifier's circulation record: when it was minted.
CIRCULATION_ELEMENT = ":/c"

#: Element marking a hold. Every identifier in a long-term minter has one.
HOLD_ELEMENT = ":/h"

#: Per-identifier bookkeeping elements that are never curatorial metadata.
BOOKKEEPING_ELEMENTS = {CIRCULATION_ELEMENT, HOLD_ELEMENT}

#: Legacy tables that are not collections.
NON_COLLECTION_TABLES = {"system", "user"}

#: Element holding the legacy redirect counter.
REDIRECT_ELEMENT = "REDIRECT"

#: Columns every collection table has, and nothing else does.
COLLECTION_COLUMNS = ("_key", "_value")


def parse_legacy_key(key: str) -> tuple[str, str, str] | None:
    """
    Split a legacy key into ``(ark, qualifier, element)``.

    The qualifier is the concatenation of the middle components, so a hierarchy
    and a variant stored as two tab-separated parts come back as the single
    normalised string this system uses. Returns ``None`` when the key carries no
    element (nothing to bind).
    """
    parts = key.split("\t")
    if len(parts) < 2:
        return None
    return parts[0], "".join(parts[1:-1]), parts[-1]


def is_reserved(key: str) -> bool:
    """True for configuration rows such as ``:/naa``."""
    return key.startswith(RESERVED)


def is_bookkeeping(element: str) -> bool:
    return element.strip().lower() in BOOKKEEPING_ELEMENTS


def is_circulation(element: str) -> bool:
    return element.strip().lower() == CIRCULATION_ELEMENT


def is_hold(element: str) -> bool:
    return element.strip().lower() == HOLD_ELEMENT


# --- what legacy's storage layer did to the data --------------------------

#: The exact inverse of PHP's htmlspecialchars(ENT_QUOTES | ENT_HTML401), which
#: every write went through. ``&amp;`` is undone last so that a curator who
#: really typed "&lt;" — stored as "&amp;lt;" — gets "&lt;" back and not "<".
_ENTITIES = (
    ("&lt;", "<"),
    ("&gt;", ">"),
    ("&quot;", '"'),
    ("&#039;", "'"),
    ("&amp;", "&"),
)


def decode_legacy_text(text: str) -> str:
    """Undo the HTML escaping legacy applied to every key and value."""
    if not text or "&" not in text:
        return text or ""
    for entity, character in _ENTITIES:
        text = text.replace(entity, character)
    return text


def normalise_row(key: str, value: str | None) -> tuple[str, str]:
    """
    Clean up one collection-table row on the way in.

    Entities are decoded on both halves. A trailing carriage return is stripped
    from the value — thousands of them arrived through bulk uploads saved with
    Windows line endings. The *key* keeps its carriage return: the importer has
    to see which spelling a row used before it can decide which one wins.
    """
    return decode_legacy_text(key), decode_legacy_text(value or "").rstrip("\r")


#: A plausible span for a Unix timestamp in a circulation record: 2001 to 2286.
_EPOCH_DIGITS = (9, 10)


def parse_circulation(value: str) -> datetime | None:
    """
    When an identifier was minted, from its circulation record.

    The record is ``<status vector>|<local timestamp>|<contact>|<counter>``,
    e.g. ``i|20201022094659|1603374419|1``. The application passed PHP's
    ``time()`` as the contact, so field three is normally a Unix timestamp and
    is unambiguous; the local timestamp is the fallback, read in this service's
    own time zone because that is where legacy ran. Returns ``None`` when the
    record says nothing usable.
    """
    parts = (value or "").split("|")
    if len(parts) < 2:
        return None

    contact = parts[2].strip() if len(parts) > 2 else ""
    if contact.isdigit() and len(contact) in _EPOCH_DIGITS:
        try:
            return datetime.fromtimestamp(int(contact), tz=UTC)
        except (OverflowError, OSError, ValueError):  # pragma: no cover - defensive
            return None

    stamp = parts[1].strip()
    if len(stamp) == 14 and stamp.isdigit():
        try:
            naive = datetime.strptime(stamp, "%Y%m%d%H%M%S")
        except ValueError:
            return None
        try:
            return timezone.make_aware(naive, timezone.get_current_timezone())
        except Exception:  # pragma: no cover - ambiguous local times only
            return naive.replace(tzinfo=UTC)
    return None


@dataclass
class LegacyCollection:
    """One legacy collection table, decoded."""

    table: str
    config: dict[str, str] = field(default_factory=dict)

    @property
    def naan(self) -> str:
        return self.config.get(":/naan", "").strip()

    @property
    def naa(self) -> str:
        return self.config.get(":/naa", "").strip()

    @property
    def prefix(self) -> str:
        return self.config.get(":/prefix", "").strip()

    @property
    def template(self) -> str:
        return self.config.get(":/template", "").strip()

    @property
    def mask(self) -> str:
        return self.config.get(":/mask", "").strip()


class LegacyReader:
    """
    Read-only access to a legacy ARK database.

    Deliberately a plain DB-API connection rather than a Django one: this is a
    foreign database that is never written to and never migrated, so it has no
    business in ``settings.DATABASES``.
    """

    def __init__(self, connection, vendor: str):
        self._connection = connection
        self.vendor = vendor

    def quote(self, identifier: str) -> str:
        """Quote a table name for this vendor, rejecting anything suspicious."""
        if not identifier.replace("_", "").replace("-", "").isalnum():
            raise ValueError(f"Unsupported table name: {identifier!r}")
        return f'"{identifier}"' if self.vendor == "postgresql" else f"`{identifier}`"

    def collection_tables(self) -> list[str]:
        """Every table that holds a collection (all but `system` and `user`)."""
        cursor = self._connection.cursor()
        if self.vendor == "sqlite":
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        elif self.vendor == "postgresql":
            cursor.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname = current_schema() "
                "ORDER BY tablename"
            )
        else:
            cursor.execute("SHOW TABLES")
        names = [row[0] for row in cursor.fetchall()]
        return [
            name
            for name in names
            if name.lower() not in NON_COLLECTION_TABLES and not name.startswith("sqlite_")
        ]

    def rows(self, table: str, batch: int = 5000):
        """
        Stream ``(key, value)`` pairs from a collection table.

        Yields in batches rather than returning the table: a production import
        is millions of rows, and fetchall() put every one of them in memory at
        once before any work started.
        """
        cursor = self._connection.cursor()
        cursor.execute(f"SELECT _key, _value FROM {self.quote(table)}")
        while True:
            rows = cursor.fetchmany(batch)
            if not rows:
                return
            for key, value in rows:
                yield normalise_row(key, value)

    def system_settings(self) -> dict[str, str]:
        """The legacy ``system`` table: organisation name and website."""
        try:
            cursor = self._connection.cursor()
            cursor.execute(f"SELECT _key, _value FROM {self.quote('system')}")
            return dict(cursor.fetchall())
        except Exception:
            return {}

    def close(self):
        self._connection.close()


# --- reading an export file -----------------------------------------------


class DumpFormatError(Exception):
    """The export file is not in a shape this can read."""


class _Unparsable(Exception):
    """Internal: the scanner hit something that is not a value."""


_INSERT_RE = re.compile(
    r"^INSERT\s+(?:LOW_PRIORITY\s+|DELAYED\s+|HIGH_PRIORITY\s+)?(?:IGNORE\s+)?INTO\s+"
    r"`?(?P<table>[^`\s(]+)`?\s*"
    r"(?:\((?P<columns>[^)]*)\)\s*)?"
    r"VALUES\s*",
    re.IGNORECASE,
)
_CREATE_RE = re.compile(
    r"^CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?`?(?P<table>[^`\s(]+)`?\s*\(",
    re.IGNORECASE,
)
_COLUMN_RE = re.compile(r"^`(?P<name>[^`]+)`\s+\S")
_NAME_RE = re.compile(r"`([^`]+)`|([A-Za-z_][A-Za-z0-9_$]*)")
_BARE_RE = re.compile(r"[A-Za-z0-9_.+\-]+")

#: The overwhelmingly common row: two plain strings with nothing to unescape.
#: Worth its own path — the scanner below is ten times slower, and a production
#: export is three million lines.
_FAST_ROW = re.compile(r"^\('([^'\\]*)',[ ]?'([^'\\]*)'\)[ ]*(,|;)?$")

#: MySQL's string escapes. Anything else after a backslash is that character.
_ESCAPES = {
    "0": "\0",
    "b": "\b",
    "n": "\n",
    "r": "\r",
    "t": "\t",
    "Z": "\x1a",
    "\\": "\\",
    "'": "'",
    '"': '"',
}


def _unquote(text: str) -> str:
    """Column names out of an INSERT's column list."""
    return [(match.group(1) or match.group(2)) for match in _NAME_RE.finditer(text or "") if match]


def _scan_value(text: str, pos: int) -> tuple[str | None, int] | None:
    """One value from ``pos``. ``None`` when the text runs out mid-value."""
    if text[pos] == "'":
        out: list[str] = []
        pos += 1
        end = len(text)
        while pos < end:
            char = text[pos]
            if char == "\\":
                if pos + 1 >= end:
                    return None
                out.append(_ESCAPES.get(text[pos + 1], text[pos + 1]))
                pos += 2
            elif char == "'":
                if pos + 1 < end and text[pos + 1] == "'":
                    out.append("'")
                    pos += 2
                    continue
                return "".join(out), pos + 1
            else:
                out.append(char)
                pos += 1
        return None

    match = _BARE_RE.match(text, pos)
    if not match:
        raise _Unparsable(pos)
    token = match.group(0)
    return (None if token.upper() == "NULL" else token), match.end()


def _scan_row(text: str, pos: int) -> tuple[list[str | None] | None, int]:
    """One ``( ... )`` tuple from ``pos``. ``(None, pos)`` when incomplete."""
    end = len(text)
    pos += 1  # the opening bracket
    values: list[str | None] = []
    while True:
        while pos < end and text[pos] in " \t\r\n":
            pos += 1
        if pos >= end:
            return None, pos
        if text[pos] == ")":
            return values, pos + 1
        scanned = _scan_value(text, pos)
        if scanned is None:
            return None, pos
        value, pos = scanned
        values.append(value)
        while pos < end and text[pos] in " \t\r\n":
            pos += 1
        if pos >= end:
            return None, pos
        if text[pos] == ",":
            pos += 1
        elif text[pos] == ")":
            return values, pos + 1
        else:
            raise _Unparsable(pos)


def _scan(text: str) -> tuple[list[list[str | None]], str, bool]:
    """
    Every complete tuple in ``text``.

    Returns ``(rows, leftover, ended)`` — leftover is a tuple that ran off the
    end of the text and must be completed by the next line, and ended says the
    statement's closing semicolon was reached.
    """
    rows: list[list[str | None]] = []
    pos, end = 0, len(text)
    while True:
        while pos < end and text[pos] in ", \t\r\n":
            pos += 1
        if pos >= end:
            return rows, "", False
        if text[pos] == ";":
            return rows, "", True
        if text[pos] != "(":
            raise _Unparsable(pos)
        values, after = _scan_row(text, pos)
        if values is None:
            return rows, text[pos:], False
        rows.append(values)
        pos = after


class DumpReader:
    """
    Read-only access to a mysqldump or phpMyAdmin export of a legacy database.

    Presents the same surface as :class:`LegacyReader`, so the import does not
    care which one it was handed. The file is streamed rather than loaded: a
    production export is a couple of hundred megabytes, and it is read once per
    pass rather than held in memory.
    """

    vendor = "dump"

    def __init__(self, path: Path, encoding: str = "utf-8"):
        self.path = Path(path)
        self.encoding = encoding
        self._indexed = False
        self._insert_columns: dict[str, list[str]] = {}
        self._create_columns: dict[str, list[str]] = {}
        self._order: list[str] = []
        self._system: dict[str, str] = {}

    # --- the file itself --------------------------------------------------

    @contextmanager
    def _open(self):
        opener = gzip.open if self.path.name.endswith(".gz") else open
        try:
            handle = opener(self.path, "rt", encoding=self.encoding, newline="\n")
        except FileNotFoundError as exc:
            raise DumpFormatError(f"No such file: {self.path}") from exc
        except OSError as exc:
            raise DumpFormatError(f"{self.path} is not readable: {exc}") from exc
        try:
            yield handle
        finally:
            handle.close()

    def _lines(self, handle):
        try:
            yield from handle
        except (UnicodeDecodeError, gzip.BadGzipFile, EOFError) as exc:
            if isinstance(exc, UnicodeDecodeError):
                raise DumpFormatError(
                    f"{self.path} is not valid {self.encoding}. Re-export it with "
                    "`mysqldump --default-character-set=utf8mb4`, or name the encoding "
                    "it really has with --encoding (for example --encoding latin-1)."
                ) from exc
            raise DumpFormatError(f"{self.path} could not be read: {exc}") from exc

    # --- the statements in it ---------------------------------------------

    def _iter_rows(self, wanted: str | None = None):
        """
        Walk the file, yielding ``(table, values)`` for ``wanted`` (or all).

        Column layouts are recorded as they go by, so one pass is enough to
        learn what the file contains as well as to read it.
        """
        with self._open() as handle:
            in_block = False
            creating: str | None = None
            table: str | None = None
            fast: bool = False
            pending = ""
            pending_line = 0

            for line_no, raw in enumerate(self._lines(handle), 1):
                line = raw.strip()

                if not in_block:
                    if creating is not None:
                        if line.startswith(")"):
                            creating = None
                        else:
                            column = _COLUMN_RE.match(line)
                            if column:
                                self._create_columns[creating].append(column.group("name"))
                        continue

                    if not line:
                        continue

                    create = _CREATE_RE.match(line)
                    if create:
                        creating = create.group("table")
                        self._create_columns.setdefault(creating, [])
                        continue

                    insert = _INSERT_RE.match(line)
                    if insert is None:
                        continue

                    table = insert.group("table")
                    if table not in self._insert_columns:
                        self._insert_columns[table] = _unquote(insert.group("columns"))
                        self._order.append(table)
                    in_block = True
                    fast = self._is_default_layout(table)
                    pending, pending_line = "", 0
                    text = line[insert.end() :].strip()
                    if not text:
                        continue
                    start_line = line_no
                else:
                    if not line and not pending:
                        continue
                    if pending:
                        # A value with a real newline in it, split across lines.
                        text = f"{pending}\n{line}"
                        start_line = pending_line
                    else:
                        text = line
                        start_line = line_no

                    if fast and not pending and (wanted is None or table == wanted):
                        quick = _FAST_ROW.match(text)
                        if quick:
                            yield table, [quick.group(1), quick.group(2)]
                            if quick.group(3) == ";":
                                in_block, table = False, None
                            continue

                try:
                    rows, leftover, ended = _scan(text)
                except _Unparsable as exc:
                    raise DumpFormatError(
                        f"{self.path}: could not read line {start_line} of the export "
                        f"(near character {exc.args[0]}). Was it written by mysqldump "
                        "or phpMyAdmin?"
                    ) from exc

                if wanted is None or table == wanted:
                    for values in rows:
                        yield table, values

                pending = leftover
                pending_line = start_line if leftover else 0
                if ended:
                    in_block, table = False, None

            if pending.strip():
                raise DumpFormatError(
                    f"{self.path}: the value starting on line {pending_line} is never "
                    "closed — the export looks truncated."
                )

    def _is_default_layout(self, table: str) -> bool:
        """True when ``(_key, _value)`` are simply the first two columns."""
        columns = self._insert_columns.get(table) or self._create_columns.get(table) or []
        return list(columns[:2]) == list(COLLECTION_COLUMNS)

    def _positions(self, table: str) -> tuple[int, int]:
        columns = self._insert_columns.get(table) or self._create_columns.get(table) or []
        if not columns:
            return 0, 1
        try:
            return columns.index("_key"), columns.index("_value")
        except ValueError:
            return 0, 1

    def _index(self):
        if self._indexed:
            return
        # One pass learns the layout of every table and picks up the two rows
        # of the system table on the way past.
        for _, values in self._iter_rows(wanted="system"):
            if len(values) >= 2:
                key, value = values[0], values[1]
                if key is not None:
                    self._system[key] = value or ""
        self._indexed = True

    # --- the reader surface -----------------------------------------------

    def collection_tables(self) -> list[str]:
        """Every table in the export that holds a collection."""
        self._index()
        tables = []
        for name in self._order:
            if name.lower() in NON_COLLECTION_TABLES:
                continue
            columns = self._insert_columns.get(name) or self._create_columns.get(name) or []
            if columns and not set(COLLECTION_COLUMNS) <= set(columns):
                continue
            tables.append(name)
        return sorted(tables)

    def rows(self, table: str, batch: int = 5000):
        """Stream ``(key, value)`` pairs from one collection table."""
        self._index()
        key_at, value_at = self._positions(table)
        for _, values in self._iter_rows(wanted=table):
            if len(values) <= max(key_at, value_at):
                continue
            key = values[key_at]
            if key is None:
                continue
            yield normalise_row(key, values[value_at])

    def system_settings(self) -> dict[str, str]:
        """The legacy ``system`` table: organisation name and website."""
        self._index()
        return dict(self._system)

    def close(self):
        """Nothing is held open between passes."""


@contextmanager
def open_legacy(url: str):
    """Open a legacy database from a URL, closing it afterwards."""
    parsed = urlparse(url)
    scheme = parsed.scheme.split("+")[0].lower()

    if scheme == "sqlite":
        # sqlite:///relative/path vs sqlite:////absolute/path — exactly one
        # leading slash belongs to the URL, the rest belong to the path.
        path = parsed.path[1:] if parsed.path.startswith("/") else parsed.path
        connection = sqlite3.connect(path or parsed.netloc or ":memory:")
        vendor = "sqlite"
    elif scheme in ("mysql", "mariadb"):
        import MySQLdb

        connection = MySQLdb.connect(
            host=parsed.hostname or "localhost",
            port=parsed.port or 3306,
            user=unquote(parsed.username or ""),
            passwd=unquote(parsed.password or ""),
            db=parsed.path.lstrip("/"),
            charset="utf8mb4",
        )
        vendor = "mysql"
    elif scheme in ("postgres", "postgresql"):
        import psycopg

        connection = psycopg.connect(url)
        vendor = "postgresql"
    else:
        raise ValueError(f"Unsupported legacy database URL scheme: {parsed.scheme!r}")

    reader = LegacyReader(connection, vendor)
    try:
        yield reader
    finally:
        reader.close()


@contextmanager
def open_legacy_dump(path, encoding: str = "utf-8"):
    """Open a legacy export file, which is read rather than connected to."""
    path = Path(path)
    # Checked here rather than on the first read: a mistyped path should fail
    # before the import reports that it found no collections.
    if not path.is_file():
        raise DumpFormatError(f"No such file: {path}")
    reader = DumpReader(path, encoding=encoding)
    try:
        yield reader
    finally:
        reader.close()
