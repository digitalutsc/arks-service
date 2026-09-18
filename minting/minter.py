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
from minting.noid import NOLIMIT, TemplateSpec, make_id, parse_template

#: Identifiers checked against the database per round trip. Bounds both the
#: SQL IN-list and the memory a mint can use, whatever the collection's size.
_PROBE_CHUNK = 1000

#: Rounds of random drawing before falling back to an ordered sweep.
_MAX_DRAW_ROUNDS = 8


class MintError(Exception):
    """Minting could not proceed."""


class TemplateExhausted(MintError):
    """The template has no unused identifiers left."""


def _taken_identifiers(collection: Collection, identifiers: list[str]) -> set[str]:
    """
    Which of ``identifiers`` already exist — asked in bounded chunks.

    Never reads more of the collection than the candidates being considered, so
    the cost of minting does not grow with the collection.
    """
    taken: set[str] = set()
    for start in range(0, len(identifiers), _PROBE_CHUNK):
        chunk = identifiers[start : start + _PROBE_CHUNK]
        taken.update(
            collection.arks.filter(identifier__in=chunk).values_list("identifier", flat=True)
        )
    return taken


def _next_sequential(collection: Collection, spec: TemplateSpec, count: int) -> list[int]:
    """
    The next ``count`` unused counter values, in order.

    Starts from the highest sequence recorded (an index-only lookup) and probes
    forward in bounded batches. Gaps left by deleted rows below that point are
    not reused — identifiers are never reissued anyway, and refilling them would
    mean reading the whole collection.
    """
    highest = (
        collection.arks.exclude(sequence=None)
        .order_by("-sequence")
        .values_list("sequence", flat=True)
        .first()
    )
    candidate = 0 if highest is None else highest + 1
    capacity = None if spec.total == NOLIMIT else spec.total

    chosen: list[int] = []
    while len(chosen) < count:
        wanted = count - len(chosen)
        batch = []
        while len(batch) < wanted:
            if capacity is not None and candidate >= capacity:
                if not batch:
                    raise TemplateExhausted(
                        f"Template {collection.template!r} can mint at most {capacity} identifiers."
                    )
                break
            batch.append(candidate)
            candidate += 1

        identifiers = {n: _identifier_for(collection, spec, n) for n in batch}
        taken = _taken_identifiers(collection, list(identifiers.values()))
        chosen.extend(n for n in batch if identifiers[n] not in taken)

        if capacity is not None and candidate >= capacity and len(chosen) < count:
            raise TemplateExhausted(
                f"Template {collection.template!r} can mint at most {capacity} identifiers."
            )
    return chosen[:count]


def _next_random(collection: Collection, spec: TemplateSpec, count: int) -> list[int]:
    """
    ``count`` unused counter values drawn at random from the template space.

    Draws are checked against the database in bounded batches rather than
    against an in-memory set of everything already minted; the previous version
    materialised ``range(capacity)`` once a space was half full, which is 2.8 GB
    for the 70-million-identifier ``.reedeedk`` template.
    """
    capacity = spec.total
    if capacity == NOLIMIT:  # pragma: no cover - "z" masks are never random
        raise MintError("A random template must have a bounded space.")

    used = collection.arks.count()
    if capacity - used < count:
        raise TemplateExhausted(
            f"Template {collection.template!r} has {capacity - used} identifiers left, "
            f"but {count} were requested."
        )

    chosen: list[int] = []
    drawn: set[int] = set()

    for _round in range(_MAX_DRAW_ROUNDS):
        wanted = count - len(chosen)
        if not wanted:
            return chosen

        # Over-draw so one round usually suffices even when the space is busy.
        candidates: list[int] = []
        while len(candidates) < min(wanted * 4, _PROBE_CHUNK):
            pick = secrets.randbelow(capacity)
            if pick not in drawn:
                drawn.add(pick)
                candidates.append(pick)
            if len(drawn) >= capacity:
                break

        identifiers = {n: _identifier_for(collection, spec, n) for n in candidates}
        taken = _taken_identifiers(collection, list(identifiers.values()))
        for n in candidates:
            if identifiers[n] not in taken:
                chosen.append(n)
                if len(chosen) == count:
                    return chosen

    # The space is too crowded for random probing to land. Walk it in order and
    # take what is free — bounded memory, unlike enumerating the whole range.
    return chosen + _sweep_for_free(collection, spec, capacity, count - len(chosen), drawn)


def _sweep_for_free(
    collection: Collection,
    spec: TemplateSpec,
    capacity: int,
    wanted: int,
    exclude: set[int],
) -> list[int]:
    """Scan the template space in chunks for unused values (crowded spaces)."""
    found: list[int] = []
    for start in range(0, capacity, _PROBE_CHUNK):
        batch = [n for n in range(start, min(start + _PROBE_CHUNK, capacity)) if n not in exclude]
        if not batch:
            continue
        identifiers = {n: _identifier_for(collection, spec, n) for n in batch}
        taken = _taken_identifiers(collection, list(identifiers.values()))
        for n in batch:
            if identifiers[n] not in taken:
                found.append(n)
                if len(found) == wanted:
                    return found
    raise TemplateExhausted(f"Template {collection.template!r} is full.")


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
    # 0 switches the cap off.
    limit = getattr(settings, "MINT_MAX_PER_REQUEST", 10_000)
    if limit and count > limit:
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
