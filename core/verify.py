"""
Cutover verification.

The plan for going live is to run this system alongside the legacy one, resolve
every ARK against both, and only flip the Apache vhost once the diff is clean.
This module decides what to compare and what counts as a difference; the HTTP
fetching lives in the ``resolve_diff`` command.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from urllib.parse import urlparse

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
    inflections: bool = True,
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
            yield f"{base}?info"
        for qualifier in sorted(qualifiers.get(ark_id, ())):
            yield f"{base}{qualifier}"


#: Legacy answered an unresolvable ARK by redirecting to its own error page.
LEGACY_NOT_FOUND_PAGE = "404.php"

_TAG = re.compile(r"<[^>]+>")


def _is_legacy_miss(status: int, target: str, legacy_base: str | None) -> bool:
    """True when a legacy 302 is really 'not found' in disguise."""
    if status not in (301, 302, 303, 307, 308) or not target:
        return False
    parsed = urlparse(target)
    if not parsed.path.rstrip("/").endswith(LEGACY_NOT_FOUND_PAGE):
        return False
    if legacy_base:
        # Only the legacy service's own error page counts; a collection that
        # genuinely redirects to a page named 404.php is a real target.
        return parsed.netloc == urlparse(legacy_base).netloc and parsed.path.count("/") <= 1
    return True


def _metadata_lines(body: str) -> set[str]:
    """
    The comparable content of a metadata response.

    Legacy wrapped its ERC block in (nested, unbalanced) <pre> tags and returned
    rows in whatever order MySQL produced; this system emits plain text sorted
    by element name. Compare the set of non-empty lines instead of the bytes.
    """
    text = _TAG.sub("\n", body or "")
    return {line.strip() for line in text.splitlines() if line.strip()}


def compare(
    path: str,
    legacy: tuple[int, str],
    new: tuple[int, str],
    *,
    legacy_base: str | None = None,
) -> Difference | None:
    """
    Compare one path's outcome on both systems.

    Each side is ``(status, target)`` where target is the Location header for a
    redirect or the body for a metadata response. Differences of *expression*
    are normalised away — a legacy redirect to 404.php is a 404, and legacy's
    <pre>-wrapped metadata is compared line-wise — so that what remains is a
    real difference in what the ARK resolves to. Returns ``None`` when the two
    agree.
    """
    legacy_status, legacy_target = legacy
    new_status, new_target = new
    legacy_target = legacy_target or ""
    new_target = new_target or ""

    if _is_legacy_miss(legacy_status, legacy_target, legacy_base) and new_status == 404:
        return None

    if legacy_status == 200 and new_status == 200:
        if _metadata_lines(legacy_target) == _metadata_lines(new_target):
            return None
        return Difference(
            path=path,
            legacy_status=legacy_status,
            new_status=new_status,
            legacy=legacy_target,
            new=new_target,
        )

    if legacy_status == new_status and legacy_target == new_target:
        return None

    return Difference(
        path=path,
        legacy_status=legacy_status,
        new_status=new_status,
        legacy=legacy_target,
        new=new_target,
    )
