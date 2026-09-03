"""
Minting new ARKs.

The legacy minter kept its position in a ``:/oacounter`` row and, for random
templates, replayed Perl's ``rand()`` so the n-th identifier was reproducible
even after a rebuild. None of that survives here. Identifiers are still built
by the same ``n2xdig`` base conversion, so they are indistinguishable from the
ones already in production, but *which* number comes next is decided against
the database — and a unique constraint on (naan, identifier) makes a duplicate
impossible rather than merely unlikely.
"""

from __future__ import annotations

import secrets

from django.conf import settings
from django.db import transaction

from core.models import Ark, Collection
from minting.noid import NOLIMIT, TemplateSpec, make_id, parse_template, xdig2n

#: Above this fraction of a random template's space, drawing at random starts
#: colliding too often; switch to picking from what is actually left.
_DENSE_FRACTION = 0.5

#: Give up on random draws after this many consecutive collisions.
_MAX_DRAWS_PER_ID = 64


class MintError(Exception):
    """Minting could not proceed."""


class TemplateExhausted(MintError):
    """The template has no unused identifiers left."""


def _used_identifiers(collection: Collection) -> set[str]:
    return set(collection.arks.values_list("identifier", flat=True))


def _used_sequences(collection: Collection, spec: TemplateSpec) -> set[int]:
    """
    Every counter value already spoken for in this collection.

    Rows minted here carry their sequence. Rows that arrived some other way —
    an import, or a hand-created identifier — are decoded back to the counter
    value that would have produced them, so they still block that slot.
    """
    used: set[int] = set()
    prefix_length = len(collection.prefix)
    for identifier, sequence in collection.arks.values_list("identifier", "sequence"):
        if sequence is not None:
            used.add(sequence)
            continue
        try:
            used.add(xdig2n(identifier[prefix_length:], spec.mask))
        except ValueError:
            # Not an identifier this template could have produced, so it cannot
            # collide with one we are about to generate.
            continue
    return used


def _next_sequential(collection: Collection, spec: TemplateSpec, count: int) -> list[int]:
    """The next ``count`` unused counter values, in order."""
    highest = (
        collection.arks.exclude(sequence=None)
        .order_by("-sequence")
        .values_list("sequence", flat=True)
        .first()
    )
    candidate = 0 if highest is None else highest + 1
    used = _used_identifiers(collection)
    capacity = None if spec.total == NOLIMIT else spec.total

    chosen: list[int] = []
    while len(chosen) < count:
        if capacity is not None and candidate >= capacity:
            raise TemplateExhausted(
                f"Template {collection.template!r} can mint at most {capacity} identifiers."
            )
        if _identifier_for(collection, spec, candidate) not in used:
            chosen.append(candidate)
        candidate += 1
    return chosen


def _next_random(collection: Collection, spec: TemplateSpec, count: int) -> list[int]:
    """``count`` unused counter values drawn at random from the template space."""
    capacity = spec.total
    if capacity == NOLIMIT:  # pragma: no cover - "z" masks are never random
        raise MintError("A random template must have a bounded space.")

    taken = _used_sequences(collection, spec)
    remaining = capacity - len(taken)
    if remaining < count:
        raise TemplateExhausted(
            f"Template {collection.template!r} has {remaining} identifiers left, "
            f"but {count} were requested."
        )

    chosen: list[int] = []

    # Once the space is crowded, random probing wastes more time than simply
    # listing what is free.
    if len(taken) >= capacity * _DENSE_FRACTION:
        free = [n for n in range(capacity) if n not in taken]
        for _ in range(count):
            pick = free.pop(secrets.randbelow(len(free)))
            chosen.append(pick)
        return chosen

    for _ in range(count):
        for _attempt in range(_MAX_DRAWS_PER_ID):
            pick = secrets.randbelow(capacity)
            if pick not in taken:
                taken.add(pick)
                chosen.append(pick)
                break
        else:
            free = [n for n in range(capacity) if n not in taken]
            if not free:
                raise TemplateExhausted(f"Template {collection.template!r} is full.")
            pick = free[secrets.randbelow(len(free))]
            taken.add(pick)
            chosen.append(pick)
    return chosen


def _identifier_for(collection: Collection, spec: TemplateSpec, sequence: int) -> str:
    """The identifier (without the NAAN) for a counter value."""
    full = make_id(collection.firstpart, spec.mask, sequence)
    if full is None:  # pragma: no cover - only if a check char cannot be built
        raise MintError(f"Could not build an identifier for {sequence}.")
    return full[len(collection.naan) + 1 :]


@transaction.atomic
def mint(collection: Collection, count: int = 1, user=None) -> list[Ark]:
    """
    Mint ``count`` new ARKs in ``collection`` and return them.

    All or nothing: if the template runs out part way, nothing is created.
    Concurrent callers are serialised on the collection row, and the unique
    constraint on (naan, identifier) is the backstop if anything slips past.
    """
    if count < 1:
        raise ValueError("count must be at least 1")
    limit = getattr(settings, "MINT_MAX_PER_REQUEST", 10_000)
    if count > limit:
        raise ValueError(
            f"Refusing to mint {count:,} identifiers in one go; at most {limit:,} per request. "
            "Run it as several batches."
        )

    # Serialise minters so two callers cannot choose the same counter value.
    locked = Collection.objects.select_for_update().get(pk=collection.pk)
    spec = parse_template(locked.full_template)

    sequences = (
        _next_random(locked, spec, count)
        if spec.is_random
        else _next_sequential(locked, spec, count)
    )

    arks = [
        Ark(
            collection=locked,
            naan=locked.naan,
            identifier=_identifier_for(locked, spec, sequence),
            sequence=sequence,
            minted_by=user,
        )
        for sequence in sequences
    ]
    Ark.objects.bulk_create(arks, batch_size=1000)

    if any(ark.pk is None for ark in arks):
        # MySQL — the production engine — cannot return primary keys from a
        # multi-row insert, so bulk_create leaves them unset. Callers bind to
        # what they just minted, so read the rows back rather than hand out
        # objects with pk None.
        by_identifier = {
            identifier: pk
            for pk, identifier in Ark.objects.filter(
                collection=locked, identifier__in=[a.identifier for a in arks]
            ).values_list("id", "identifier")
        }
        for ark in arks:
            ark.pk = by_identifier.get(ark.identifier)

    return arks
