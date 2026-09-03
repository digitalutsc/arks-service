"""
Reading the legacy ARK database.

Legacy kept one table per collection, each a generic key/value store where the
key packed several fields together with tabs::

    :/naa, :/naan, :/template ...             reserved configuration
    61220/utsc1<TAB>URL                       element on the ARK itself
    61220/utsc1<TAB>/page1<TAB>URL            element on a hierarchical part
    61220/utsc1<TAB>/page1<TAB>.png<TAB>URL   ... with a variant
    61220/utsc1<TAB>:/c                       circulation bookkeeping

Keys are read literally rather than re-derived, so whatever production actually
contains survives the move — including anything the legacy code wrote in a way
its own resolver could not read back.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, field
from urllib.parse import unquote, urlparse

#: Prefix marking a reserved (non-identifier) row.
RESERVED = ":"

#: Per-identifier bookkeeping elements that carry no curatorial meaning.
BOOKKEEPING_ELEMENTS = {":/c", ":/h"}

#: Legacy tables that are not collections.
NON_COLLECTION_TABLES = {"system", "user"}

#: Element holding the legacy redirect counter.
REDIRECT_ELEMENT = "REDIRECT"


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

    @property
    def term(self) -> str:
        if self.config.get(":/longterm"):
            return "long"
        if self.config.get(":/wrap"):
            return "short"
        return "medium"


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
            yield from rows

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
