#!/usr/bin/env python
"""
Seed a synthetic collection for scale testing.

    DATABASE_URL=mysql://root:root@127.0.0.1:33306/ark \
        python scripts/bench/seed.py --arks 1000000 --prefix utsc

Writes ARKs and ~4.5 bindings each with raw bulk inserts, bypassing the
application so seeding time does not depend on what we are measuring.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

import django

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "arkservice.settings")
os.environ.setdefault("DJANGO_DEBUG", "true")
django.setup()

from django.db import connection, transaction  # noqa: E402

from core.models import Ark, Binding, Collection  # noqa: E402

CHUNK = 20_000


def seed(count: int, prefix: str, naan: str) -> None:
    collection, _ = Collection.objects.get_or_create(
        prefix=prefix,
        defaults={
            "name": f"Bench {prefix}",
            "naan": naan,
            "naa": "Benchmark collection",
            "template": ".zd",
        },
    )
    existing = Ark.objects.filter(collection=collection).count()
    print(f"collection {prefix!r} has {existing:,} ARKs; seeding to {count:,}")

    started = time.time()
    for start in range(existing, count, CHUNK):
        end = min(start + CHUNK, count)
        with transaction.atomic():
            Ark.objects.bulk_create(
                [
                    Ark(
                        collection=collection,
                        naan=naan,
                        identifier=f"{prefix}{n}",
                        sequence=n,
                    )
                    for n in range(start, end)
                ],
                batch_size=5000,
            )
            pks = dict(
                Ark.objects.filter(
                    collection=collection, sequence__gte=start, sequence__lt=end
                ).values_list("sequence", "id")
            )
            bindings = []
            for n in range(start, end):
                pk = pks[n]
                url = f"https://digital.utsc.utoronto.ca/object/{prefix}:{n}"
                bindings.append(Binding(ark_id=pk, qualifier="", name="URL", value=url))
                bindings.append(
                    Binding(ark_id=pk, qualifier="", name="LOCAL_ID", value=f"{prefix}:{n}")
                )
                bindings.append(
                    Binding(ark_id=pk, qualifier="", name="PID", value=f"islandora:{n}")
                )
                bindings.append(
                    Binding(ark_id=pk, qualifier="", name="COLLECTION", value="Digital Collections")
                )
                if n % 2 == 0:
                    bindings.append(
                        Binding(ark_id=pk, qualifier="/page1", name="URL", value=url + "/p1")
                    )
            Binding.objects.bulk_create(bindings, batch_size=5000)

        done = end - existing
        rate = done / max(time.time() - started, 0.001)
        print(f"  {end:,} ARKs  ({rate:,.0f}/s)", flush=True)

    print(f"done in {time.time() - started:.1f}s on {connection.vendor}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--arks", type=int, default=1_000_000)
    parser.add_argument("--prefix", default="utsc")
    parser.add_argument("--naan", default="61220")
    args = parser.parse_args()
    seed(args.arks, args.prefix, args.naan)
