"""Bind one element to an ARK."""

from django.core.management.base import BaseCommand

from core.management.commands._common import get_ark
from core.models import Binding


class Command(BaseCommand):
    help = "Bind an element to an ARK, replacing any existing value."

    def add_arguments(self, parser):
        parser.add_argument("ark", help="e.g. 61220/utsc1 or 61220/utsc1/page1")
        parser.add_argument("element", help="Element name, e.g. URL")
        parser.add_argument("value")

    def handle(self, *args, **options):
        ark, qualifier = get_ark(options["ark"])
        binding, created = Binding.objects.update_or_create(
            ark=ark,
            qualifier=qualifier,
            name=options["element"].strip().upper(),
            defaults={"value": options["value"]},
        )
        verb = "Bound" if created else "Rebound"
        self.stdout.write(self.style.SUCCESS(f"{verb} {binding.name} on {ark.name}{qualifier}"))
