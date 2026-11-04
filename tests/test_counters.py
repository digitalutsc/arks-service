"""
Redirect counting must not make every read a write.

Resolution.record issued an UPDATE on every public redirect: one row lock and
one redo flush per hit on a popular ARK, and — more importantly — it meant no
read replica could ever serve resolution, because resolving wrote.
"""

import pytest

from core.counters import flush_counters, record_resolution
from core.models import Ark, Collection, Resolution

pytestmark = pytest.mark.django_db


@pytest.fixture
def collection():
    return Collection.objects.create(name="UTSC", prefix="utsc", naan="61220", template=".zd")


@pytest.fixture
def ark(collection):
    return Ark.objects.create(collection=collection, identifier="utsc1", sequence=1)


def test_recording_writes_nothing_until_flushed(ark):
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    with CaptureQueriesContext(connection) as captured:
        for _ in range(10):
            record_resolution(ark.pk, "")

    writes = [q for q in captured.captured_queries if not q["sql"].lower().startswith("select")]
    assert not writes, f"counting should not touch the database: {writes[:1]}"
    assert not Resolution.objects.exists()


def test_flushing_totals_the_buffered_hits(ark):
    for _ in range(7):
        record_resolution(ark.pk, "")
    flush_counters()
    assert Resolution.objects.get(ark=ark, qualifier="").count == 7


def test_flushing_adds_to_what_is_already_stored(ark):
    Resolution.objects.create(ark=ark, qualifier="", count=100)
    record_resolution(ark.pk, "")
    record_resolution(ark.pk, "")
    flush_counters()
    assert Resolution.objects.get(ark=ark, qualifier="").count == 102


def test_counts_are_kept_per_qualifier(ark):
    record_resolution(ark.pk, "")
    record_resolution(ark.pk, "/page1")
    record_resolution(ark.pk, "/page1")
    flush_counters()
    assert Resolution.objects.get(ark=ark, qualifier="").count == 1
    assert Resolution.objects.get(ark=ark, qualifier="/page1").count == 2


def test_a_second_flush_does_not_double_count(ark):
    record_resolution(ark.pk, "")
    flush_counters()
    flush_counters()
    assert Resolution.objects.get(ark=ark, qualifier="").count == 1


def test_flushing_reports_how_many_hits_it_moved(ark):
    for _ in range(3):
        record_resolution(ark.pk, "")
    assert flush_counters() == 3


def test_counting_survives_a_broken_cache(ark, monkeypatch, counter_redis):
    # If the buffer is unavailable, counts must still be recorded rather than
    # silently lost — the fallback is the old direct write.
    import redis

    def broken(*args, **kwargs):
        raise redis.ConnectionError("redis is down")

    monkeypatch.setattr(counter_redis, "hincrby", broken)

    record_resolution(ark.pk, "")
    assert Resolution.objects.get(ark=ark, qualifier="").count == 1


def test_without_a_server_every_hit_is_written_through(ark, monkeypatch):
    import core.counters as counters

    monkeypatch.setattr(counters, "_client", lambda: None)
    record_resolution(ark.pk, "")
    record_resolution(ark.pk, "")
    assert Resolution.objects.get(ark=ark, qualifier="").count == 2
    assert flush_counters() == 0


def test_an_ark_deleted_before_the_flush_is_skipped(ark):
    record_resolution(ark.pk, "")
    ark_pk = ark.pk
    ark.delete()
    flush_counters()  # must not raise
    assert not Resolution.objects.filter(ark_id=ark_pk).exists()


def test_many_distinct_arks_do_not_evict_each_others_counts(collection):
    # Django's local-memory cache culls at 300 entries by default, which
    # silently discarded counters for a busy service. Whatever backend is in
    # use, buffered hits must survive until they are flushed.
    Ark.objects.bulk_create(
        [
            Ark(collection=collection, naan="61220", identifier=f"c{n}", sequence=n)
            for n in range(500)
        ]
    )
    pks = list(Ark.objects.filter(collection=collection).values_list("id", flat=True))
    for pk in pks:
        record_resolution(pk, "")

    flush_counters()
    assert Resolution.objects.count() == len(pks), "counters were evicted before the flush"
    assert set(Resolution.objects.values_list("count", flat=True)) == {1}


def test_concurrent_hits_are_all_counted(ark):
    # The old buffer read, changed and rewrote a pickled set of pending pairs,
    # so concurrent hits dropped each other. A hash increment cannot.
    import threading

    def hit():
        for _ in range(50):
            record_resolution(ark.pk, "")

    threads = [threading.Thread(target=hit) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    flush_counters()
    assert Resolution.objects.get(ark=ark, qualifier="").count == 400


def test_a_hit_during_a_flush_is_not_lost(ark, monkeypatch):
    # The old flush read a counter and deleted it in two steps, losing any hit
    # that landed in between. Now the hash is renamed first, so a concurrent
    # hit lands in a fresh one and is moved by the same or the next flush.
    import core.counters as counters

    record_resolution(ark.pk, "")
    real_apply = counters._apply
    hit_once = {"done": False}

    def apply_then_hit(batch):
        moved = real_apply(batch)
        if not hit_once["done"]:
            hit_once["done"] = True
            record_resolution(ark.pk, "")
        return moved

    monkeypatch.setattr(counters, "_apply", apply_then_hit)
    flush_counters()
    flush_counters()
    assert Resolution.objects.get(ark=ark, qualifier="").count == 2


def test_an_interrupted_flush_is_finished_by_the_next(collection, monkeypatch):
    import core.counters as counters

    Ark.objects.bulk_create(
        [Ark(collection=collection, naan="61220", identifier=f"i{n}", sequence=n) for n in range(5)]
    )
    pks = list(Ark.objects.filter(collection=collection).values_list("id", flat=True))
    for pk in pks:
        record_resolution(pk, "")

    monkeypatch.setattr(counters, "FLUSH_BATCH", 2)
    real_apply = counters._apply
    calls = {"n": 0}

    def fail_second(batch):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("database went away")
        return real_apply(batch)

    monkeypatch.setattr(counters, "_apply", fail_second)
    with pytest.raises(RuntimeError):
        flush_counters()
    assert Resolution.objects.count() == 2  # the first batch committed

    monkeypatch.setattr(counters, "_apply", real_apply)
    assert flush_counters() == 3
    assert Resolution.objects.count() == 5
    assert set(Resolution.objects.values_list("count", flat=True)) == {1}


def test_a_flush_already_running_is_left_alone(ark, counter_redis):
    import core.counters as counters

    record_resolution(ark.pk, "")
    counter_redis.set(counters.LOCK_KEY, "someone-else")
    assert flush_counters() == 0
    assert not Resolution.objects.exists()


def test_the_last_flush_time_is_recorded(ark):
    from core.counters import last_flush_age

    assert last_flush_age() is None
    flush_counters()
    assert last_flush_age() is not None
    assert last_flush_age() <= 1


def test_qualifiers_containing_colons_survive_the_round_trip(ark):
    record_resolution(ark.pk, "/page:1.image.png")
    flush_counters()
    assert Resolution.objects.get(ark=ark, qualifier="/page:1.image.png").count == 1
