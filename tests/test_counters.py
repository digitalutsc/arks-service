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


def test_counting_survives_a_broken_cache(ark, monkeypatch):
    # If the buffer is unavailable, counts must still be recorded rather than
    # silently lost — the fallback is the old direct write.
    import core.counters as counters

    def broken(*args, **kwargs):
        raise RuntimeError("redis is down")

    monkeypatch.setattr(counters.cache, "incr", broken)
    monkeypatch.setattr(counters.cache, "add", broken)

    record_resolution(ark.pk, "")
    assert Resolution.objects.get(ark=ark, qualifier="").count == 1


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
