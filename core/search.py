"""
Searching ARKs and turning a result into CSV.

Two constraints shape this. Search must reach *any* element name, since the
whole point of the binding model is that collections invent their own; and it
must stay inside the portable SQL subset, so free text is a ``LIKE`` scan rather
than a PostgreSQL or MySQL full-text index. At the current scale (100k ARKs,
~400k bindings) that is comfortably fast, and an engine-specific index can be
added later without changing the schema.

Export emits exactly the shape bulk bind consumes, so a search result can be
edited in a spreadsheet and uploaded straight back.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime

from django.core.cache import cache
from django.db.models import (
    BigIntegerField,
    Count,
    Exists,
    OuterRef,
    Q,
    QuerySet,
    Subquery,
    Sum,
    Value,
)
from django.db.models.functions import Coalesce

from core.models import Ark, Binding, Resolution, value_prefix

#: First column of an export; also the column bulk bind reads.
ARK_ID_COLUMN = "Ark_ID"

#: Leading characters that make Excel and LibreOffice treat a cell as a formula.
#: Values are stored verbatim and escaped only on the way out.
FORMULA_LEAD = ("=", "+", "-", "@", "\t", "\r")


def csv_safe(value: str) -> str:
    """Neutralise a value that a spreadsheet would otherwise execute."""
    text = "" if value is None else str(value)
    return "'" + text if text.startswith(FORMULA_LEAD) else text


#: Rows pulled from the database at a time when exporting.
EXPORT_CHUNK = 2000

#: How long the element-name list is cached. Unscoped it is a full index scan.
ELEMENT_NAMES_CACHE_SECONDS = 300

#: Upper bound on distinct element names offered; a runaway import cannot make
#: the export header (or the search datalist) unbounded.
MAX_ELEMENT_NAMES = 500

#: How far the result counter looks before reporting "more than this". InnoDB
#: keeps no row count, so an exact COUNT(*) is a full index scan — minutes on a
#: billion-row table, for a number nobody reads past the first digit.
COUNT_CAP = 10_000


def search_arks(
    *,
    collection=None,
    text: str = "",
    element: str = "",
    value: str = "",
    bound: bool | None = None,
    minted_after: datetime | None = None,
    minted_before: datetime | None = None,
    min_redirects: int | None = None,
    order_by: str = "naan",
) -> QuerySet[Ark]:
    """Build a queryset of ARKs matching the given filters."""
    queryset = Ark.objects.all()

    if collection is not None:
        queryset = queryset.filter(collection=collection)

    if text:
        matching = Binding.objects.filter(ark=OuterRef("pk"), value__icontains=text)
        queryset = queryset.filter(Q(identifier__icontains=text) | Exists(matching))

    if element or value:
        # Match on the indexed prefix first, then re-check the full value: TEXT
        # is not indexable on MySQL, so without this an exact lookup scans every
        # binding carrying that name.
        element_filter = {"ark": OuterRef("pk")}
        if element:
            element_filter["name"] = element.strip().upper()
        if value:
            # The prefix narrows to a handful of rows through the index; iexact
            # then re-checks the whole value, so values sharing a long prefix do
            # not collide and matching stays case-insensitive as it was under
            # MySQL's default collation.
            element_filter["value_prefix"] = value_prefix(value)
            element_filter["value__iexact"] = value
        queryset = queryset.filter(Exists(Binding.objects.filter(**element_filter)))

    if bound is not None:
        has_binding = Exists(Binding.objects.filter(ark=OuterRef("pk")))
        queryset = queryset.filter(has_binding) if bound else queryset.exclude(has_binding)

    if minted_after is not None:
        queryset = queryset.filter(minted_at__gte=minted_after)
    if minted_before is not None:
        queryset = queryset.filter(minted_at__lte=minted_before)

    if min_redirects is not None:
        queryset = queryset.filter(
            Exists(Resolution.objects.filter(ark=OuterRef("pk"), count__gte=min_redirects))
        )

    # Exists() subqueries keep rows distinct without a DISTINCT, which would
    # force a sort over the whole result on both engines.
    return queryset.order_by(order_by, "identifier")


#: Columns the browse table can be ordered by. The value arrives in a query
#: string, so it is only ever looked up here, never handed to order_by().
SORT_KEYS = ("ark", "minted", "redirects", "elements")
DEFAULT_SORT = "ark"

#: Columns whose first click should show the largest or newest rows.
SORT_DESC_FIRST = frozenset({"minted", "redirects", "elements"})


def parse_sort(raw: str | None) -> tuple[str, bool]:
    """
    Turn a ``sort`` parameter into ``(key, descending)``.

    ``minted`` is ascending and ``-minted`` descending. Anything unrecognised is
    the default order rather than an error.
    """
    text = (raw or "").strip()
    descending = text.startswith("-")
    key = text[1:] if descending else text
    if key not in SORT_KEYS:
        return DEFAULT_SORT, False
    return key, descending


def sort_arks(queryset: QuerySet[Ark], key: str, descending: bool = False) -> QuerySet[Ark]:
    """Order a search result by one of ``SORT_KEYS``."""
    if key == "minted":
        # The primary key rides along in every InnoDB secondary index, so the
        # tie-break costs nothing and keeps pages stable when an import stamped
        # thousands of ARKs with the same instant.
        fields = ["minted_at", "id"]
    elif key in ("redirects", "elements"):
        # Neither total is stored, so these order by a per-row subquery and the
        # database sorts the whole filtered set to find one page. That is paid
        # only when someone asks for it; narrowing with a filter first keeps it
        # quick. order_by() keeps Resolution's Meta.ordering out of the grouped
        # subquery, which must come back as exactly one row.
        if key == "redirects":
            per_ark = (
                Resolution.objects.filter(ark=OuterRef("pk"))
                .order_by()
                .values("ark")
                .annotate(total=Sum("count"))
            )
        else:
            per_ark = (
                Binding.objects.filter(ark=OuterRef("pk"))
                .order_by()
                .values("ark")
                .annotate(total=Count("id"))
            )
        queryset = queryset.annotate(
            sort_total=Coalesce(
                Subquery(per_ark.values("total")), Value(0), output_field=BigIntegerField()
            )
        )
        # Ties stay in ARK order whichever way the totals run.
        total = "-sort_total" if descending else "sort_total"
        return queryset.order_by(total, "naan", "identifier")
    else:
        fields = ["naan", "identifier"]

    return queryset.order_by(*(f"-{field}" if descending else field for field in fields))


def counted(queryset: QuerySet[Ark], cap: int = COUNT_CAP) -> tuple[int, bool]:
    """
    Return ``(count, capped)`` for a result set, looking no further than ``cap``.

    ``capped`` is True when there are at least ``cap`` rows and the real total
    was not established, so callers can render "10,000+".
    """
    total = queryset.order_by()[:cap].count()
    return total, total >= cap


def export_rows(queryset: QuerySet[Ark], collection=None) -> Iterator[list[str]]:
    """
    Yield CSV rows for ``queryset``: a header, then one row per ARK-and-qualifier.

    An ARK with no bindings still gets a row, so an export can be used as a
    fill-in template. The first column holds the ARK including its qualifier,
    which is exactly what bulk bind expects back.

    Pass ``collection`` when the export is scoped to one, so the header can be
    built from that collection's element names instead of every name in the
    database.
    """
    # The header comes from the element names in scope, not from a scan of every
    # matching row: materialising the whole id list cost 311 MB and 33 seconds
    # before the first row at 1M ARKs, and above roughly 4M ids the IN-list
    # exceeded MySQL's max_allowed_packet and the export failed outright.
    columns = sorted(element_names(getattr(collection, "pk", collection)))
    yield [ARK_ID_COLUMN, *columns]

    index = {name: position for position, name in enumerate(columns, start=1)}
    width = len(columns) + 1

    for chunk in _id_chunks(queryset, EXPORT_CHUNK):
        arks = {
            pk: f"{naan}/{identifier}"
            for pk, naan, identifier in Ark.objects.filter(pk__in=chunk).values_list(
                "id", "naan", "identifier"
            )
        }
        rows: dict[tuple[int, str], list[str]] = {}

        bound: set[int] = set()
        for ark_id, qualifier, name, value in (
            Binding.objects.filter(ark_id__in=chunk)
            .order_by("ark_id", "qualifier", "name")
            .values_list("ark_id", "qualifier", "name", "value")
        ):
            column = index.get(name)
            if column is None:
                # Bound after the header was computed; a streaming response is
                # already on the wire, so skip rather than abort the download.
                continue
            row = rows.setdefault((ark_id, qualifier), [""] * width)
            row[0] = arks[ark_id] + qualifier
            row[column] = csv_safe(value)
            bound.add(ark_id)

        # Keep unbound ARKs in the output so they can be filled in.
        for ark_id in chunk:
            if ark_id not in bound:
                row = [""] * width
                row[0] = arks[ark_id]
                rows[(ark_id, "")] = row

        position = {ark_id: order for order, ark_id in enumerate(chunk)}
        for key in sorted(rows, key=lambda k: (position[k[0]], k[1])):
            yield rows[key]


def _id_chunks(queryset: QuerySet[Ark], size: int) -> Iterator[list[int]]:
    """
    Yield primary keys in bounded batches, streamed from the database.

    ``.iterator()`` keeps a server-side cursor rather than loading every id, so
    an export of any size uses a fixed amount of memory.
    """
    chunk: list[int] = []
    for pk in queryset.values_list("id", flat=True).iterator(chunk_size=size):
        chunk.append(pk)
        if len(chunk) >= size:
            yield chunk
            chunk = []
    if chunk:
        yield chunk


def element_names(collection_id=None) -> list[str]:
    """
    Distinct element names, for export headers and the search datalist.

    Scoped to one collection when possible. Unscoped this is a full scan of the
    binding name index — 5 billion entries at 1B ARKs — so it is cached; a new
    element name appears in the list within CACHE_SECONDS.
    """
    key = f"element-names:{collection_id or 'all'}"
    names = cache.get(key)
    if names is None:
        bindings = Binding.objects.all()
        if collection_id is not None:
            bindings = bindings.filter(ark__collection_id=collection_id)
        names = sorted(
            bindings.order_by().values_list("name", flat=True).distinct()[:MAX_ELEMENT_NAMES]
        )
        cache.set(key, names, ELEMENT_NAMES_CACHE_SECONDS)
    return names
