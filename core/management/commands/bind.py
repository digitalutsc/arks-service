"""Bind one element to an ARK."""

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from core.management.commands._common import get_ark
from core.services import bind_element


class Command(BaseCommand):
    help = "Bind an element to an ARK, replacing any existing value."

    def add_arguments(self, parser):
        parser.add_argument("ark", help="e.g. 61220/utsc1 or 61220/utsc1/page1")
        parser.add_argument("element", help="Element name, e.g. URL")
        parser.add_argument("value")

    def handle(self, *args, **options):
        ark, qualifier = get_ark(options["ark"])
        try:
            binding, created = bind_element(ark, options["element"], options["value"], qualifier)
        except ValidationError as exc:
            raise CommandError(" ".join(exc.messages)) from exc
        verb = "Bound" if created else "Rebound"
        self.stdout.write(self.style.SUCCESS(f"{verb} {binding.name} on {ark.name}{qualifier}"))
