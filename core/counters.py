"""
Buffered redirect counting.

Every public resolution used to issue an UPDATE: a row lock and a redo flush per
hit, so one popular ARK was capped at a few hundred redirects a second on cloud
storage. Worse, it made resolving a *write*, which rules out ever serving
resolution from a read replica.

Hits are counted in one Redis/Valkey hash and moved into the database
periodically:

- A hit is a single ``HINCRBY arks:hits "<ark_id>:<qualifier>" 1``. Its cost
  does not depend on how many other ARKs have pending hits, and concurrent hits
  cannot overwrite each other.
- A flush renames the hash (atomic: new hits start a fresh one), writes the
  counts in batches, and removes each batch's fields only after its transaction
  commits. A flush that dies part-way leaves the rest in ``arks:hits:flushing``
  for the next flush to finish. The one way to double-count is a crash in the
  instant between a batch's commit and its ``HDEL``: at most one batch counted
  twice, never a hit lost.

The trade is explicit: counts lag by up to the flush interval. If the server is
unreachable, a hit is written straight to the database instead, so counts are
never silently abandoned. Without ``REDIS_URL`` (a bare development box) every
hit is written straight through.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone

logger = logging.getLogger(__name__)

#: Hash of pending hits: field "<ark_id>:<qualifier>", value the count.
HITS_KEY = "arks:hits"
#: The hash a flush is working through.
FLUSHING_KEY = "arks:hits:flushing"
#: Held while a flush runs, so two flushes never work on the same hash.
LOCK_KEY = "arks:flush-lock"
LOCK_SECONDS = 300
#: Unix time of the last completed flush, for /healthz.
LAST_FLUSH_KEY = "arks:last-flush"

#: Pairs written per database transaction.
FLUSH_BATCH = 500

#: At most one "buffer unavailable" warning per process per this many seconds,
#: so an outage does not write a traceback for every redirect.
WARN_INTERVAL_SECONDS = 60

_client_lock = threading.Lock()
_client_instance = None
_last_warning = 0.0


def _client():
    """The Redis client for the buffer, or None when no server is configured."""
    global _client_instance
    url = getattr(settings, "REDIS_URL", "")
    if not url:
        return None
    if _client_instance is None:
        with _client_lock:
            if _client_instance is None:
                import redis

                timeout = getattr(settings, "CACHE_SOCKET_TIMEOUT", 0.5)
                _client_instance = redis.Redis.from_url(
                    url,
                    socket_timeout=timeout,
                    socket_connect_timeout=timeout,
                    health_check_interval=30,
                )
    return _client_instance


def warn_unavailable(what: str) -> None:
    """Log that a cache-side dependency failed, at most once a minute per process."""
    global _last_warning
    now = time.monotonic()
    if now - _last_warning >= WARN_INTERVAL_SECONDS:
        _last_warning = now
        logger.warning("%s unavailable; falling back to the database", what)


def _field(ark_id: int, qualifier: str) -> str:
    return f"{ark_id}:{qualifier}"


def _parse_field(field) -> tuple[int, str]:
    text = field.decode() if isinstance(field, bytes) else field
    ark_id, _, qualifier = text.partition(":")
    return int(ark_id), qualifier


def record_resolution(ark_id: int, qualifier: str = "") -> None:
    """
    Count one redirect. Cheap, and never blocks the response for long.

    Falls back to writing straight to the database if the buffer is unavailable,
    so an outage degrades performance rather than losing counts.
    """
    client = _client()
    if client is not None:
        try:
            client.hincrby(HITS_KEY, _field(ark_id, qualifier), 1)
            return
        except Exception:  # noqa: BLE001 - any failure means "write through instead"
            warn_unavailable("resolution counter buffer")
    _write_through(ark_id, qualifier)


def _write_through(ark_id: int, qualifier: str) -> None:
    from core.models import Ark, Resolution

    ark = Ark.objects.filter(pk=ark_id).first()
    if ark is not None:
        Resolution.record(ark, qualifier)


def last_flush_age() -> int | None:
    """Seconds since the last completed flush, or None if unknown."""
    client = _client()
    if client is None:
        return None
    try:
        stamp = client.get(LAST_FLUSH_KEY)
    except Exception:  # noqa: BLE001
        return None
    if stamp is None:
        return None
    return max(0, int(time.time()) - int(stamp))


def ping() -> bool:
    """Whether the buffer's server answers. True when there is no server to ask."""
    client = _client()
    if client is None:
        return True
    return bool(client.ping())


def flush_counters() -> int:
    """
    Move buffered hits into the database. Returns how many hits were moved.

    Safe to call concurrently: a second caller finds the lock held and returns 0.
    """
    client = _client()
    if client is None:
        return 0

    token = uuid.uuid4().hex
    if not client.set(LOCK_KEY, token, nx=True, ex=LOCK_SECONDS):
        return 0
    try:
        moved = 0
        # First finish whatever an interrupted flush left behind, then take the
        # current hash. Two passes at most.
        for _ in range(2):
            if not client.exists(FLUSHING_KEY):
                try:
                    client.rename(HITS_KEY, FLUSHING_KEY)
                except Exception as exc:  # noqa: BLE001
                    if "no such key" in str(exc).lower():
                        break
                    raise
            moved += _drain(client)
        client.set(LAST_FLUSH_KEY, int(time.time()))
        return moved
    finally:
        if client.get(LOCK_KEY) in (token, token.encode()):
            client.delete(LOCK_KEY)


def _drain(client) -> int:
    """Write every pair in the flushing hash to the database, batch by batch."""
    pending = client.hgetall(FLUSHING_KEY)
    if not pending:
        client.delete(FLUSHING_KEY)
        return 0

    items = []
    for field, hits in pending.items():
        ark_id, qualifier = _parse_field(field)
        items.append((field, ark_id, qualifier, int(hits)))

    moved = 0
    for start in range(0, len(items), FLUSH_BATCH):
        batch = items[start : start + FLUSH_BATCH]
        try:
            moved += _apply(batch)
        except IntegrityError:
            # A write-through during an outage created one of these rows after
            # we looked. Looking again sees it.
            moved += _apply(batch)
        client.hdel(FLUSHING_KEY, *[field for field, *_ in batch])

    client.delete(FLUSHING_KEY)
    return moved


def _apply(batch) -> int:
    """
    Add one batch of buffered hits to the database, in one transaction.

    Existing rows are incremented in SQL (``count = count + n``), one UPDATE per
    distinct hit count in the batch: usually a handful, since most pairs have
    the same few counts. ``bulk_update`` wrote every row's new value through a
    CASE expression instead, which was six times slower on MySQL (23 s for
    50,000 pairs at 4M ARKs) and needed the rows locked first.
    """
    from core.models import Ark, Resolution

    now = timezone.now()
    ark_ids = {ark_id for _, ark_id, _, _ in batch}
    hits_for = {(ark_id, qualifier): hits for _, ark_id, qualifier, hits in batch}

    with transaction.atomic():
        existing = {
            (ark_id, qualifier): pk
            for pk, ark_id, qualifier in Resolution.objects.filter(ark_id__in=ark_ids).values_list(
                "pk", "ark_id", "qualifier"
            )
            if (ark_id, qualifier) in hits_for
        }
        alive = set(Ark.objects.filter(pk__in=ark_ids).values_list("pk", flat=True))

        by_hits: dict[int, list[int]] = {}
        to_create, moved = [], 0
        for pair, hits in hits_for.items():
            pk = existing.get(pair)
            if pk is not None:
                by_hits.setdefault(hits, []).append(pk)
            elif pair[0] in alive:
                to_create.append(
                    Resolution(ark_id=pair[0], qualifier=pair[1], count=hits, last_at=now)
                )
            else:
                # The ARK went away between the hit and the flush.
                continue
            moved += hits

        for hits, pks in by_hits.items():
            Resolution.objects.filter(pk__in=pks).update(count=F("count") + hits, last_at=now)
        if to_create:
            Resolution.objects.bulk_create(to_create, batch_size=FLUSH_BATCH)
    return moved
