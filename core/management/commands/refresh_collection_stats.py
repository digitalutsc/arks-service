"""Recount collections now, instead of waiting for the scheduler."""

from __future__ import annotations

from django.core.management.base import BaseCommand

from core.management.commands._common import get_collection
from core.models import Collection
from core.services import refresh_collection_stats


class Command(BaseCommand):
    help = (
        "Recount ARKs, bound ARKs, elements and redirects for one collection, or "
        "all of them, and store the result the collection pages show. The "
        "scheduler does this every COLLECTION_STATS_SECONDS."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "collection", nargs="?", help="Name, prefix or <naan>/<prefix>; all if omitted"
        )

    def handle(self, *args, collection=None, **options):
        targets = [get_collection(collection)] if collection else list(Collection.objects.all())
        for each in targets:
            stats = refresh_collection_stats(each)
            self.stdout.write(
                f"{each.name}: {stats['total']:,} ARKs, {stats['bound']:,} bound, "
                f"{stats['elements']:,} elements, {stats['redirects']:,} redirects"
            )
