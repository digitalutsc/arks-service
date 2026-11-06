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

import logging

from django.core.exceptions import ValidationError
from django.db.models import Exists, OuterRef, Sum
from django.utils import timezone

from core.arkpath import HYPHEN_REFUSED
from core.models import Ark, Binding, Collection, Resolution

logger = logging.getLogger(__name__)

#: Rows per round trip when writing in bulk.
BATCH_SIZE = 2000

#: Most redirect elements a collection may list. Each is tried in order on
#: every redirect, so a long list is a sign of a muddle rather than a need.
MAX_REDIRECT_ELEMENTS = 5

#: Characters a proxied suffix may not contain. It is one path segment
#: ('/'), never a variant ('.'), never mistaken for an inflection or a fragment
#: ('?', '#'), compared decoded ('%'), and never hyphenated (see HYPHEN_REFUSED).
_SUFFIX_FORBIDDEN = set("/.?#%-") | {" "}


def normalise_element_name(name: str) -> str:
    """
    The canonical stored form of an element name.

    Every bulk path bypasses ``Binding.save()``, so this cannot live only on the
    model — each writer has to apply it.
    """
    return (name or "").strip().upper()


def qualifier_problem(qualifier: str) -> str | None:
    """
    Why staff may not bind under ``qualifier``, or None when they may.

    Checked on every staff write path (the ARK page, ``bind``, bulk bind) but
    not by unbind, so anything already stored can still be removed, nor by the
    legacy import, which takes the legacy data as it is.
    """
    if "-" in qualifier:
        return f"The qualifier {qualifier} {HYPHEN_REFUSED}"
    return None


def prefix_problem(prefix: str) -> str | None:
    """
    Why a new collection may not use ``prefix``, or None when it may.

    Every ARK a collection mints starts with its prefix, so a hyphen there
    would make all of them unreachable through N2T. Checked when a collection
    is created, not on the model, so an imported legacy collection stays
    editable whatever its prefix.
    """
    if "-" in prefix:
        return f"The prefix {prefix} {HYPHEN_REFUSED}"
    return None


def parse_redirect_elements(text: str) -> list[str]:
    """
    A collection's redirect elements, from the comma-separated form staff type.

    Each name is normalised as every element name is (upper-cased), repeats are
    dropped, and the order is kept: the resolver uses the first one bound.
    """
    names: list[str] = []
    for part in (text or "").split(","):
        name = normalise_element_name(part)
        if name and name not in names:
            names.append(name)
    if not names:
        raise ValidationError(
            {"redirect_elements": "Name at least one redirect element, e.g. URL."}
        )
    if len(names) > MAX_REDIRECT_ELEMENTS:
        raise ValidationError(
            {"redirect_elements": f"Name at most {MAX_REDIRECT_ELEMENTS} redirect elements."}
        )
    return names


def parse_proxied_suffixes(text: str) -> list[str]:
    """
    A collection's proxied suffixes, from the comma-separated form staff type.

    An empty list is allowed: the collection then has no service routes, and
    '…/manifest' is an ordinary qualifier. Each suffix is a single plain path
    segment, case-sensitive like any qualifier. Segments starting with a digit
    or '_' are reserved by the ARK spec for future service points
    (draft-kunze-ark-44 §4.7).
    """
    parts = [part.strip() for part in (text or "").split(",")]
    if not any(parts):
        return []
    suffixes: list[str] = []
    for part in parts:
        problem = None
        if not part:
            problem = "An empty suffix (two commas in a row?) is not allowed."
        elif set(part) & _SUFFIX_FORBIDDEN:
            problem = (
                f"The suffix {part!r} must be one plain path segment: "
                "no '/', '.', '?', '#', '%', '-' or spaces."
            )
        elif part[0].isdigit() or part[0] == "_":
            problem = (
                f"The suffix {part!r} may not start with a digit or '_': "
                "the ARK spec reserves those for future service points."
            )
        if problem:
            raise ValidationError({"proxied_suffixes": problem})
        if part not in suffixes:
            suffixes.append(part)
    return suffixes


def resolution_impact(collection: Collection, elements: list[str], suffixes: list[str]) -> dict:
    """
    What changing ``collection``'s resolution settings would touch, for the preview.

    ``elements``: for each element in the old or the new list, how many
    (ARK, qualifier) pairs bind it. ``suffixes``: for each suffix in the old or
    the new list, how many ARKs bind something at a qualifier ending in it.
    ``warnings``: the changes that alter what existing ARKs answer.
    """
    old_elements = collection.redirect_element_list
    old_suffixes = collection.proxied_suffix_list
    bindings = Binding.objects.filter(ark__collection=collection)

    element_counts = {
        name: bindings.filter(name=name).count()
        for name in dict.fromkeys([*old_elements, *elements])
    }
    suffix_counts = {
        suffix: bindings.filter(qualifier__endswith=f"/{suffix}")
        .values("ark_id")
        .distinct()
        .count()
        for suffix in dict.fromkeys([*old_suffixes, *suffixes])
    }

    warnings: list[str] = []
    for name in elements:
        if element_counts[name] == 0:
            warnings.append(f"{name} is bound nowhere in this collection, so it redirects nothing.")
    for name in old_elements:
        if name not in elements and element_counts[name]:
            warnings.append(
                f"{name} is bound in {_counted(element_counts[name], 'place')} and will no longer "
                "be used for redirects; those ARKs may stop resolving or resolve elsewhere."
            )
    if elements != old_elements and set(elements) == set(old_elements):
        warnings.append("The order changes: where both are bound, a different URL wins.")
    for suffix in old_suffixes:
        if suffix not in suffixes and suffix_counts[suffix]:
            warnings.append(
                f"/{suffix} is bound on {_counted(suffix_counts[suffix], 'ARK')}; those requests "
                "will redirect instead of returning JSON."
            )
    for suffix in suffixes:
        if suffix not in old_suffixes and suffix_counts[suffix]:
            warnings.append(
                f"/{suffix} is bound on {_counted(suffix_counts[suffix], 'ARK')}; those requests "
                "will return the target's JSON instead of redirecting."
            )
    return {"elements": element_counts, "suffixes": suffix_counts, "warnings": warnings}


def _counted(count: int, noun: str) -> str:
    """'1 ARK', '2 ARKs', '1,204 places'."""
    return f"{count:,} {noun}{'' if count == 1 else 's'}"


def update_resolution_settings(
    collection: Collection, elements: list[str], suffixes: list[str], user=None
) -> None:
    """
    Save new resolution settings, stamp who changed them, and log old -> new.

    Changing them re-points every ARK in the collection at once, so the change
    is logged at WARNING with both values: the app log is the history.
    """
    old_elements, old_suffixes = collection.redirect_elements, collection.proxied_suffixes
    collection.redirect_elements = ",".join(elements)
    collection.proxied_suffixes = ",".join(suffixes)
    collection.resolution_changed_at = timezone.now()
    collection.resolution_changed_by = user if getattr(user, "pk", None) else None
    collection.save(
        update_fields=[
            "redirect_elements",
            "proxied_suffixes",
            "resolution_changed_at",
            "resolution_changed_by",
        ]
    )
    logger.warning(
        "collection %s: redirect elements %s -> %s; proxied suffixes %s -> %s by %s",
        collection.name,
        old_elements,
        collection.redirect_elements,
        old_suffixes or "(none)",
        collection.proxied_suffixes or "(none)",
        user.get_username() if getattr(user, "pk", None) else "(system)",
    )


def bind_element(ark: Ark, name: str, value: str, qualifier: str = "") -> tuple[Binding, bool]:
    """Bind one element, replacing any existing value. Returns (binding, created)."""
    element = normalise_element_name(name)
    if not element:
        raise ValidationError({"name": "An element name is required."})
    problem = qualifier_problem(qualifier)
    if problem:
        raise ValidationError({"qualifier": problem})
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


def bulk_upsert_bindings(
    wanted: dict[tuple[int, str, str], str], *, progress=None, outcomes=None
) -> tuple[int, int]:
    """
    Write ``{(ark_id, qualifier, element): value}`` in bulk.

    Returns ``(created, updated)``. Values that have not changed are left alone,
    so a re-import or a re-uploaded CSV is a cheap no-op.

    ``progress(phase, done, total)``, when given, is called after each chunk with
    how many of the wanted elements have been dealt with (created, updated or
    left alone), so a caller can show a bar. ``outcomes``, when a dict is given,
    is filled with ``key -> "created" | "replaced" | "unchanged"`` for every key,
    so a caller can say what happened to each row of its file.

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
    total = len(normalised)
    del normalised

    ark_ids = sorted(by_ark)
    now = timezone.now()
    created = updated = done = 0
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
                    outcome = "created"
                elif found[1] != value:
                    to_update.append(Binding(id=found[0], value=value, updated_at=now))
                    outcome = "replaced"
                else:
                    outcome = "unchanged"
                if outcomes is not None:
                    outcomes[(ark_id, qualifier, name)] = outcome

        if to_create:
            Binding.objects.bulk_create(to_create, batch_size=BATCH_SIZE)
        if to_update:
            # bulk_update skips auto_now fields, so updated_at is set explicitly.
            Binding.objects.bulk_update(to_update, ["value", "updated_at"], batch_size=BATCH_SIZE)
        created += len(to_create)
        updated += len(to_update)
        done += sum(len(by_ark[ark_id]) for ark_id in chunk)
        if progress is not None:
            progress("writing", done, total)

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
