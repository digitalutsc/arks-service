"""Summarise what is in the database."""

from django.core.management.base import BaseCommand
from django.db.models import Count, Exists, OuterRef, Sum

from core.models import Ark, Binding, Collection, Resolution


class Command(BaseCommand):
    help = "Show per-collection counts of ARKs, bindings and redirects."

    def handle(self, *args, **options):
        header = f"{'PREFIX':<12}{'NAAN':<8}{'TEMPLATE':<12}{'ARKS':>10}{'BOUND':>10}{'ELEMENTS':>10}{'REDIRECTS':>12}"
        self.stdout.write(header)
        self.stdout.write("-" * len(header))

        for collection in Collection.objects.all():
            arks = Ark.objects.filter(collection=collection)
            bound = arks.filter(Exists(Binding.objects.filter(ark=OuterRef("pk")))).count()
            elements = Binding.objects.filter(ark__collection=collection).count()
            redirects = (
                Resolution.objects.filter(ark__collection=collection).aggregate(total=Sum("count"))[
                    "total"
                ]
                or 0
            )
            self.stdout.write(
                f"{collection.prefix or '(none)':<12}{collection.naan:<8}"
                f"{collection.template:<12}{arks.count():>10,}{bound:>10,}"
                f"{elements:>10,}{redirects:>12,}"
            )

        self.stdout.write("")
        top = Binding.objects.values("name").annotate(n=Count("id")).order_by("-n")[:10]
        if top:
            self.stdout.write("Most used elements:")
            for row in top:
                self.stdout.write(f"  {row['name']:<24}{row['n']:>10,}")
