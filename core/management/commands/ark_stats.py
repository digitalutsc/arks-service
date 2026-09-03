"""Summarise what is in the database."""

from django.core.management.base import BaseCommand
from django.db.models import Count

from core.models import Binding, Collection
from core.services import collection_stats


class Command(BaseCommand):
    help = "Show per-collection counts of ARKs, bindings and redirects."

    def handle(self, *args, **options):
        header = (
            f"{'PREFIX':<12}{'NAAN':<8}{'TEMPLATE':<12}"
            f"{'ARKS':>10}{'BOUND':>10}{'ELEMENTS':>10}{'REDIRECTS':>12}"
        )
        self.stdout.write(header)
        self.stdout.write("-" * len(header))

        for collection in Collection.objects.all():
            stats = collection_stats(collection)
            self.stdout.write(
                f"{collection.prefix or '(none)':<12}{collection.naan:<8}"
                f"{collection.template:<12}{stats['total']:>10,}{stats['bound']:>10,}"
                f"{stats['elements']:>10,}{stats['redirects']:>12,}"
            )

        self.stdout.write("")
        top = Binding.objects.values("name").annotate(n=Count("id")).order_by("-n")[:10]
        if top:
            self.stdout.write("Most used elements:")
            for row in top:
                self.stdout.write(f"  {row['name']:<24}{row['n']:>10,}")
