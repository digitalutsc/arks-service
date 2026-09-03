"""
Cutover verification.

The plan for going live is to run this system alongside the legacy one, resolve
every ARK against both, and only flip the Apache vhost once the diff is clean.
This module decides what to compare and what counts as a difference; the HTTP
fetching lives in the ``resolve_diff`` command.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

from core.models import Ark, Binding, Collection


@dataclass(frozen=True)
class Difference:
    """One path that did not resolve the same way on both systems."""

    path: str
    legacy_status: int
    new_status: int
    legacy: str
    new: str

    @property
    def reason(self) -> str:
        if self.legacy_status != self.new_status:
            return f"status {self.legacy_status} -> {self.new_status}"
        return "different target"

    def as_row(self) -> list[str]:
        return [
            self.path,
            str(self.legacy_status),
            str(self.new_status),
            self.legacy,
            self.new,
            self.reason,
        ]


def iter_check_paths(
    *,
    collection: Collection | None = None,
    sample: int | None = None,
    inflections: bool = False,
) -> Iterator[str]:
    """
    Yield every ARK path worth comparing.

    That is: each NAAN root, each ARK, and each qualifier anything is bound
    under — a qualifier is emitted once however many elements it carries.
    Optionally the ``?`` and ``??`` inflections for each ARK as well.
    """
    collections = (
        Collection.objects.filter(pk=collection.pk) if collection else Collection.objects.all()
    )
    for naan in sorted({c.naan for c in collections if c.naan}):
        yield f"/ark:/{naan}/"

    arks = Ark.objects.all()
    if collection is not None:
        arks = arks.filter(collection=collection)
    arks = arks.order_by("naan", "identifier")
    if sample:
        arks = arks[:sample]

    ark_ids = list(arks.values_list("id", "naan", "identifier"))
    qualifiers: dict[int, set[str]] = {}
    for ark_id, qualifier in (
        Binding.objects.filter(ark_id__in=[row[0] for row in ark_ids])
        .exclude(qualifier="")
        .values_list("ark_id", "qualifier")
        .distinct()
    ):
        qualifiers.setdefault(ark_id, set()).add(qualifier)

    for ark_id, naan, identifier in ark_ids:
        base = f"/ark:/{naan}/{identifier}"
        yield base
        if inflections:
            yield f"{base}?"
            yield f"{base}??"
        for qualifier in sorted(qualifiers.get(ark_id, ())):
            yield f"{base}{qualifier}"


def compare(
    path: str,
    legacy: tuple[int, str],
    new: tuple[int, str],
) -> Difference | None:
    """
    Compare one path's outcome on both systems.

    Each side is ``(status, target)`` where target is the Location header for a
    redirect or the body for a metadata response. Returns ``None`` when they
    agree.
    """
    legacy_status, legacy_target = legacy
    new_status, new_target = new

    if legacy_status == new_status and (legacy_target or "") == (new_target or ""):
        return None

    return Difference(
        path=path,
        legacy_status=legacy_status,
        new_status=new_status,
        legacy=legacy_target or "",
        new=new_target or "",
    )
