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

from django.db.models import Exists, OuterRef, Q, QuerySet

from core.models import Ark, Binding, Resolution

#: First column of an export; also the column bulk bind reads.
ARK_ID_COLUMN = "Ark_ID"

#: Rows pulled from the database at a time when exporting.
EXPORT_CHUNK = 2000


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

    if element:
        element_filter = {"ark": OuterRef("pk"), "name": element.strip().upper()}
        if value:
            element_filter["value"] = value
        queryset = queryset.filter(Exists(Binding.objects.filter(**element_filter)))
    elif value:
        queryset = queryset.filter(Exists(Binding.objects.filter(ark=OuterRef("pk"), value=value)))

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


def export_rows(queryset: QuerySet[Ark]) -> Iterator[list[str]]:
    """
    Yield CSV rows for ``queryset``: a header, then one row per ARK-and-qualifier.

    An ARK with no bindings still gets a row, so an export can be used as a
    fill-in template. The first column holds the ARK including its qualifier,
    which is exactly what bulk bind expects back.
    """
    ark_ids = list(queryset.values_list("id", flat=True))

    columns = sorted(
        Binding.objects.filter(ark_id__in=ark_ids).values_list("name", flat=True).distinct()
    )
    yield [ARK_ID_COLUMN, *columns]

    index = {name: position for position, name in enumerate(columns, start=1)}
    width = len(columns) + 1

    for chunk in _chunks(ark_ids, EXPORT_CHUNK):
        arks = {
            pk: f"{naan}/{identifier}"
            for pk, naan, identifier in Ark.objects.filter(pk__in=chunk).values_list(
                "id", "naan", "identifier"
            )
        }
        rows: dict[tuple[int, str], list[str]] = {}

        for ark_id, qualifier, name, value in (
            Binding.objects.filter(ark_id__in=chunk)
            .order_by("ark_id", "qualifier", "name")
            .values_list("ark_id", "qualifier", "name", "value")
        ):
            row = rows.setdefault((ark_id, qualifier), [""] * width)
            row[0] = arks[ark_id] + qualifier
            row[index[name]] = value

        # Keep unbound ARKs in the output so they can be filled in.
        for ark_id in chunk:
            if not any(key[0] == ark_id for key in rows):
                row = [""] * width
                row[0] = arks[ark_id]
                rows[(ark_id, "")] = row

        position = {ark_id: order for order, ark_id in enumerate(chunk)}
        for key in sorted(rows, key=lambda k: (position[k[0]], k[1])):
            yield rows[key]


def _chunks(items: list, size: int) -> Iterator[list]:
    for start in range(0, len(items), size):
        yield items[start : start + size]
