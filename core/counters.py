"""
Buffered redirect counting.

Every public resolution used to issue an UPDATE: a row lock and a redo flush per
hit, so one popular ARK was capped at a few hundred redirects a second on cloud
storage. Worse, it made resolving a *write*, which rules out ever serving
resolution from a read replica.

Hits are now counted in the cache and moved into the database periodically. The
trade is explicit: counts lag by up to the flush interval, and a cache outage
loses at most that window. For a hit counter on an identifier resolver that is
the right side of the trade — but the ARK's target itself is never cached in a
way that could serve a stale redirect.
"""

from __future__ import annotations

import logging

from django.core.cache import caches
from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)

#: Buffered hits live in their own cache: evicting one loses counts, so it must
#: not share an eviction budget with ordinary memoisation.
cache = caches["counters"]

#: Cache key holding the set of (ark, qualifier) pairs with pending hits.
PENDING_KEY = "resolution-pending"

#: Prefix for the per-pair counters.
COUNTER_PREFIX = "resolution-count"

#: Counters outlive several flush intervals, so a late flush loses nothing.
COUNTER_TTL = 24 * 60 * 60


def _counter_key(ark_id: int, qualifier: str) -> str:
    return f"{COUNTER_PREFIX}:{ark_id}:{qualifier}"


def record_resolution(ark_id: int, qualifier: str = "") -> None:
    """
    Count one redirect. Cheap, and never blocks the response.

    Falls back to writing straight to the database if the buffer is unavailable,
    so a cache outage degrades performance rather than silently losing counts.
    """
    key = _counter_key(ark_id, qualifier)
    try:
        try:
            cache.incr(key)
        except ValueError:
            # No counter yet. add() rather than set() so two concurrent first
            # hits cannot each reset the other to 1.
            if not cache.add(key, 1, COUNTER_TTL):
                cache.incr(key)
        _remember(ark_id, qualifier)
    except Exception:
        logger.warning("resolution counter buffer unavailable; writing through", exc_info=True)
        _write_through(ark_id, qualifier)


def _remember(ark_id: int, qualifier: str) -> None:
    """Note that this pair has hits waiting, so the flush knows where to look."""
    pending = cache.get(PENDING_KEY) or set()
    pair = (ark_id, qualifier)
    if pair not in pending:
        pending = set(pending)
        pending.add(pair)
        cache.set(PENDING_KEY, pending, COUNTER_TTL)


def _write_through(ark_id: int, qualifier: str) -> None:
    from core.models import Resolution

    ark = _ark(ark_id)
    if ark is not None:
        Resolution.record(ark, qualifier)


def _ark(ark_id: int):
    from core.models import Ark

    return Ark.objects.filter(pk=ark_id).first()


def flush_counters() -> int:
    """
    Move buffered hits into the database. Returns how many hits were moved.

    Safe to run concurrently with itself: each counter is read and cleared in
    one step, so a hit is never counted twice or dropped between the two.
    """
    from django.db.models import F

    from core.models import Ark, Resolution

    pending = cache.get(PENDING_KEY) or set()
    if not pending:
        return 0
    cache.delete(PENDING_KEY)

    moved = 0
    now = timezone.now()
    for ark_id, qualifier in pending:
        key = _counter_key(ark_id, qualifier)
        hits = cache.get(key) or 0
        if not hits:
            continue
        # Clear before writing: a hit arriving now starts a fresh counter and
        # will be picked up by the next flush rather than being lost here.
        cache.delete(key)

        with transaction.atomic():
            updated = Resolution.objects.filter(ark_id=ark_id, qualifier=qualifier).update(
                count=F("count") + hits, last_at=now
            )
            if not updated:
                if not Ark.objects.filter(pk=ark_id).exists():
                    # The ARK went away between the hit and the flush.
                    continue
                Resolution.objects.create(
                    ark_id=ark_id, qualifier=qualifier, count=hits, last_at=now
                )
        moved += hits

    return moved
