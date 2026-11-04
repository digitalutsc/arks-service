"""
Operations shared by the admin UI and the management commands.

Staff use whichever surface is to hand, so the two must behave identically; a
difference between them is a difference in the data. Anything both sides do
lives here rather than being written twice.

That includes the bulk upsert: bulk bind and the legacy import each had their
own copy, and the copies had already drifted over whether to touch
``updated_at``.
"""

from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db.models import Exists, OuterRef, Sum
from django.utils import timezone

from core.models import Ark, Binding, Collection, Resolution

#: Rows per round trip when writing in bulk.
BATCH_SIZE = 2000


def normalise_element_name(name: str) -> str:
    """
    The canonical stored form of an element name.

    Every bulk path bypasses ``Binding.save()``, so this cannot live only on the
    model — each writer has to apply it.
    """
    return (name or "").strip().upper()


def bind_element(ark: Ark, name: str, value: str, qualifier: str = "") -> tuple[Binding, bool]:
    """Bind one element, replacing any existing value. Returns (binding, created)."""
    element = normalise_element_name(name)
    if not element:
        raise ValidationError({"name": "An element name is required."})
    result = Binding.objects.update_or_create(
        ark=ark, qualifier=qualifier, name=element, defaults={"value": value or ""}
    )
    return result


def unbind_elements(ark: Ark, name: str | None = None, qualifier: str | None = None) -> int:
    """
    Remove elements from ``ark``; returns how many went.

    With no ``name`` every element under ``qualifier`` goes; with no
    ``qualifier`` the element goes from the ARK itself.
    """
    bindings = ark.bindings.all()
    if qualifier is not None:
        bindings = bindings.filter(qualifier=qualifier)
    if name is not None:
        bindings = bindings.filter(name=normalise_element_name(name))
    removed, _ = bindings.delete()
    return removed


def bulk_upsert_bindings(wanted: dict[tuple[int, str, str], str]) -> tuple[int, int]:
    """
    Write ``{(ark_id, qualifier, element): value}`` in bulk.

    Returns ``(created, updated)``. Values that have not changed are left alone,
    so a re-import or a re-uploaded CSV is a cheap no-op.

    Row-at-a-time ``update_or_create`` costs two queries per element, which for
    a 100k-ARK collection is over 800k round trips.
    """
    if not wanted:
        return 0, 0

    normalised = {
        (ark_id, qualifier, normalise_element_name(name)): value
        for (ark_id, qualifier, name), value in wanted.items()
    }

    # Work through the ARKs BATCH_SIZE at a time: read what exists for that
    # chunk, then write its creates and updates, so only one chunk's existing
    # rows and model instances are in memory at once (a 100k-row file used to
    # hold all ~400k of them). One IN-list holding every ark id would also
    # exceed MySQL's max_allowed_packet somewhere around four million.
    by_ark: dict[int, list[tuple[str, str, str]]] = {}
    for (ark_id, qualifier, name), value in normalised.items():
        by_ark.setdefault(ark_id, []).append((qualifier, name, value))
    del normalised

    ark_ids = sorted(by_ark)
    now = timezone.now()
    created = updated = 0
    for start in range(0, len(ark_ids), BATCH_SIZE):
        chunk = ark_ids[start : start + BATCH_SIZE]
        existing = {
            (ark_id, qualifier, name): (pk, value)
            for pk, ark_id, qualifier, name, value in Binding.objects.filter(
                ark_id__in=chunk
            ).values_list("id", "ark_id", "qualifier", "name", "value")
        }

        to_create, to_update = [], []
        for ark_id in chunk:
            for qualifier, name, value in by_ark[ark_id]:
                found = existing.get((ark_id, qualifier, name))
                if found is None:
                    to_create.append(
                        Binding(ark_id=ark_id, qualifier=qualifier, name=name, value=value)
                    )
                elif found[1] != value:
                    to_update.append(Binding(id=found[0], value=value, updated_at=now))

        if to_create:
            Binding.objects.bulk_create(to_create, batch_size=BATCH_SIZE)
        if to_update:
            # bulk_update skips auto_now fields, so updated_at is set explicitly.
            Binding.objects.bulk_update(to_update, ["value", "updated_at"], batch_size=BATCH_SIZE)
        created += len(to_create)
        updated += len(to_update)

    return created, updated


#: Below this many ARKs the collection pages count live: it costs well under a
#: second, and staff see their own mint or bulk bind reflected at once.
LIVE_STATS_MAX_ARKS = 50_000


def collection_stats(collection: Collection) -> dict[str, int]:
    """The counts both the collection page and `ark_stats` report, counted now."""
    arks = Ark.objects.filter(collection=collection)
    total = arks.count()
    bound = arks.filter(Exists(Binding.objects.filter(ark=OuterRef("pk")))).count()
    return {
        "total": total,
        "bound": bound,
        "unbound": total - bound,
        "elements": Binding.objects.filter(ark__collection=collection).count(),
        "redirects": Resolution.objects.filter(ark__collection=collection).aggregate(
            total=Sum("count")
        )["total"]
        or 0,
    }


def refresh_collection_stats(collection: Collection) -> dict[str, int]:
    """Count ``collection`` now and store the result on it. Returns the counts."""
    stats = collection_stats(collection)
    now = timezone.now()
    fields = {
        "ark_count": stats["total"],
        "bound_count": stats["bound"],
        "binding_count": stats["elements"],
        "redirect_total": stats["redirects"],
        "stats_refreshed_at": now,
    }
    Collection.objects.filter(pk=collection.pk).update(**fields)
    for name, value in fields.items():
        setattr(collection, name, value)
    return stats


def current_stats(collection: Collection):
    """
    The collection's counts for a page, and when they were taken.

    Returns ``(stats, as_of)``. ``as_of`` is None when the counts were taken
    just now; otherwise it is when the scheduler last refreshed them (every
    COLLECTION_STATS_SECONDS). Large collections are never counted on request.
    """
    if collection.stats_refreshed_at and collection.ark_count >= LIVE_STATS_MAX_ARKS:
        stats = {
            "total": collection.ark_count,
            "bound": collection.bound_count,
            "unbound": collection.ark_count - collection.bound_count,
            "elements": collection.binding_count,
            "redirects": collection.redirect_total,
        }
        return stats, collection.stats_refreshed_at
    return refresh_collection_stats(collection), None
