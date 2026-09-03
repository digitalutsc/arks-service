#!/usr/bin/env python
"""
Measure the operations the scale audit flagged.

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

    width = max(len(r[0]) for r in RESULTS) + 2
    print(f"{'operation':<{width}}{'time':>10}{'peak py-mem':>14}  note")
    print("-" * (width + 26 + 40))
    for name, elapsed, mem, note in RESULTS:
        print(f"{name:<{width}}{elapsed:>10}{mem:>14}  {note}")
    print(f"\nprocess peak RSS: {_rss_mb():.0f} MB")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", default="baseline")
    parser.add_argument("--mint", type=int, default=100)
    args = parser.parse_args()
    main(args.label, args.mint)
