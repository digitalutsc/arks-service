#!/usr/bin/env python
"""
Measure the operations the scale audit flagged.

Set REDIS_URL as well as DATABASE_URL so redirects buffer their hits the way
production does (without it every hit is written to the database) and the
counter flush can be timed. On MySQL it also prints table and index sizes.

    DATABASE_URL=... python scripts/bench/measure.py --label "before A1"

Reports wall time and peak RSS for each, so a fix can be shown to work rather
than asserted. Anything that would take longer than --budget seconds is
reported as such instead of being waited out.
"""

from __future__ import annotations

import argparse
import os
import resource
import sys
import time
import tracemalloc
from contextlib import contextmanager
from pathlib import Path

import django

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "arkservice.settings")
os.environ.setdefault("DJANGO_DEBUG", "true")
django.setup()

from django.db import connection, reset_queries  # noqa: E402
from django.test import Client  # noqa: E402

from core.models import Ark, Binding, Collection  # noqa: E402
from core.search import export_rows, search_arks  # noqa: E402

RESULTS: list[tuple[str, str, str, str]] = []


def _rss_mb() -> float:
    usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # Linux reports KiB, macOS bytes.
    return usage / (1024 * 1024) if sys.platform == "darwin" else usage / 1024


@contextmanager
def measured(name: str, note: str = ""):
    tracemalloc.start()
    reset_queries()
    started = time.perf_counter()
    try:
        yield
    except Exception as exc:  # noqa: BLE001 - a failure is a result worth recording
        elapsed = time.perf_counter() - started
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        RESULTS.append((name, f"{elapsed:.2f}s", f"{peak / 1e6:.0f} MB", f"FAILED: {exc}"[:70]))
        return
    elapsed = time.perf_counter() - started
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    RESULTS.append((name, f"{elapsed:.2f}s", f"{peak / 1e6:.0f} MB", note))


def main(label: str, mint_count: int) -> None:
    collection = Collection.objects.order_by("-id").first()
    arks = Ark.objects.filter(collection=collection).count()
    bindings = Binding.objects.filter(ark__collection=collection).count()
    print(f"\n=== {label} · {connection.vendor} · {arks:,} ARKs · {bindings:,} bindings ===\n")

    client = Client()
    # The admin pages are behind a login; an anonymous client would just be
    # redirected and the measurement would be meaningless.
    from django.contrib.auth.models import User

    from admin_ui.roles import ADMIN, ensure_groups, set_role

    ensure_groups()
    bench_user, created = User.objects.get_or_create(username="bench")
    if created:
        bench_user.set_password("bench-password")
        bench_user.save()
    set_role(bench_user, ADMIN)
    client.force_login(bench_user)

    middle = arks // 2

    with measured("resolve one ARK (302)"):
        for _ in range(50):
            client.get(
                f"/ark:/{collection.naan}/{collection.prefix}{middle}",
                RAW_URI=f"/ark:/{collection.naan}/{collection.prefix}{middle}",
            )

    with measured("mint 100"):
        from minting.minter import mint

        mint(collection, count=mint_count)

    with measured("search: exact element value"):
        list(search_arks(collection=collection, element="PID", value=f"islandora:{middle}")[:50])

    with measured("search: starts with (indexes)"):
        from core.search import TEXT_STARTS

        list(
            search_arks(collection=collection, text=f"islandora:{middle}", text_mode=TEXT_STARTS)[
                :50
            ]
        )

    with measured("search: free text (LIKE scan)"):
        list(search_arks(collection=collection, text=f"{collection.prefix}:{middle}")[:50])

    response = client.get("/admin/arks/", {"collection": collection.pk})
    assert response.status_code == 200, f"admin list not reachable: {response.status_code}"

    with measured("admin ARK list, page 1"):
        client.get("/admin/arks/", {"collection": collection.pk})

    with measured("admin ARK list, page 1000"):
        client.get("/admin/arks/", {"collection": collection.pk, "page": "1000"})

    with measured("admin ARK list + free text"):
        client.get(
            "/admin/arks/", {"collection": collection.pk, "q": f"{collection.prefix}:{middle}"}
        )

    with measured("collection_stats"):
        from core.services import collection_stats

        collection_stats(collection)

    with measured("export first 5,000 rows"):
        for rows, _ in enumerate(export_rows(search_arks(collection=collection)), start=1):
            if rows >= 5000:
                break

    with measured("dashboard (collection list)"):
        client.get("/admin/")

    with measured("collection page"):
        client.get(f"/admin/collections/{collection.pk}/")

    with measured("admin ARK list sorted by redirects"):
        client.get("/admin/arks/", {"collection": collection.pk, "sort": "-redirects"})

    with measured("admin ARK list sorted by elements"):
        client.get("/admin/arks/", {"collection": collection.pk, "sort": "-elements"})

    with measured("element names, cache empty"):
        from django.core.cache import cache

        from core.search import element_names

        cache.delete(f"element-names:{collection.pk}")
        element_names(collection.pk)

    with measured("export first 100,000 rows"):
        for rows, _ in enumerate(export_rows(search_arks(collection=collection)), start=1):
            if rows >= 100_000:
                break

    _measure_flush(collection, pairs=50_000)

    _report_sizes()

    width = max(len(r[0]) for r in RESULTS) + 2
    print(f"{'operation':<{width}}{'time':>10}{'peak py-mem':>14}  note")
    print("-" * (width + 26 + 40))
    for name, elapsed, mem, note in RESULTS:
        print(f"{name:<{width}}{elapsed:>10}{mem:>14}  {note}")
    print(f"\nprocess peak RSS: {_rss_mb():.0f} MB")


def _measure_flush(collection, pairs: int) -> None:
    """Time moving `pairs` distinct buffered (ARK, qualifier) hits into the database."""
    from core import counters

    client = counters._client()
    if client is None:
        RESULTS.append((f"flush {pairs:,} buffered pairs", "-", "-", "skipped: no REDIS_URL"))
        return
    ids = list(
        Ark.objects.filter(collection=collection)
        .order_by("pk")
        .values_list("pk", flat=True)[:pairs]
    )
    pipe = client.pipeline(transaction=False)
    for pk in ids:
        pipe.hincrby(counters.HITS_KEY, f"{pk}:", 1)
    pipe.execute()
    with measured(f"flush {len(ids):,} buffered pairs"):
        counters.flush_counters()


def _report_sizes() -> None:
    """Table and index sizes, MySQL only: what SCALE.md's storage figures come from."""
    if connection.vendor != "mysql":
        return
    with connection.cursor() as cursor:
        cursor.execute("ANALYZE TABLE core_ark, core_binding, core_resolution")
        cursor.fetchall()
        cursor.execute(
            "SELECT table_name, data_length, index_length FROM information_schema.TABLES "
            "WHERE table_schema = DATABASE() AND table_name LIKE 'core_%%' "
            "ORDER BY data_length + index_length DESC"
        )
        tables = cursor.fetchall()
        cursor.execute(
            "SELECT table_name, index_name, stat_value * @@innodb_page_size "
            "FROM mysql.innodb_index_stats WHERE database_name = DATABASE() "
            "AND stat_name = 'size' AND table_name LIKE 'core_%%' ORDER BY 3 DESC"
        )
        indexes = cursor.fetchall()
    print("\ntable sizes (MB): data / indexes")
    for name, data, index in tables:
        print(f"  {name:<24}{data / 1e6:>10,.0f}{index / 1e6:>10,.0f}")
    print("index sizes (MB), PRIMARY is the clustered row data")
    for table, index, size in indexes:
        print(f"  {table:<16}{index:<36}{size / 1e6:>10,.0f}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", default="baseline")
    parser.add_argument("--mint", type=int, default=100)
    args = parser.parse_args()
    main(args.label, args.mint)
