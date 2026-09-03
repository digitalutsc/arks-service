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

from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db.models import Exists, OuterRef, Sum
from django.utils import timezone

from core.cachekeys import target_cache_key
from core.models import Ark, Binding, Collection, Resolution

#: Rows per round trip when writing in bulk.
BATCH_SIZE = 2000


def invalidate_target(ark_id: int, qualifier: str = "") -> None:
    """
    Forget a cached redirect target.

    Called by every write path. A rebind that did not invalidate would keep
    sending people to the old URL until the entry expired, which is the one
    kind of staleness this service cannot tolerate.
    """
    cache.delete(target_cache_key(ark_id, qualifier))


def invalidate_targets(pairs) -> None:
    """Forget many at once, for the bulk paths."""
    keys = [target_cache_key(ark_id, qualifier) for ark_id, qualifier in pairs]
    if keys:
        cache.delete_many(keys)


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
    invalidate_target(ark.pk, qualifier)
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
    # Collect the qualifiers before deleting, so the right entries are dropped.
    qualifiers = set(bindings.values_list("qualifier", flat=True))
    removed, _ = bindings.delete()
    invalidate_targets((ark.pk, q) for q in qualifiers)
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

    existing = {
        (ark_id, qualifier, name): (pk, value)
        for pk, ark_id, qualifier, name, value in Binding.objects.filter(
            ark_id__in={key[0] for key in normalised}
        ).values_list("id", "ark_id", "qualifier", "name", "value")
    }

    now = timezone.now()
    to_create, to_update = [], []
    for (ark_id, qualifier, name), value in normalised.items():
        found = existing.get((ark_id, qualifier, name))
        if found is None:
            to_create.append(Binding(ark_id=ark_id, qualifier=qualifier, name=name, value=value))
        elif found[1] != value:
            to_update.append(Binding(id=found[0], value=value, updated_at=now))

    if to_create:
        Binding.objects.bulk_create(to_create, batch_size=BATCH_SIZE)
    if to_update:
        # bulk_update skips auto_now fields, so updated_at is set explicitly.
        Binding.objects.bulk_update(to_update, ["value", "updated_at"], batch_size=BATCH_SIZE)

    invalidate_targets((ark_id, qualifier) for ark_id, qualifier, _ in normalised)
    return len(to_create), len(to_update)


def collection_stats(collection: Collection) -> dict[str, int]:
    """The counts both the collection page and `ark_stats` report."""
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
