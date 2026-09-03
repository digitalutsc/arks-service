"""Remove elements from an ARK."""

from django.core.management.base import BaseCommand, CommandError

from core.management.commands._common import get_ark


class Command(BaseCommand):
    help = "Remove one element from an ARK, or all of them."

    def add_arguments(self, parser):
        parser.add_argument("ark")
        parser.add_argument("element", nargs="?", help="Element name; omit with --all")
        parser.add_argument("--all", action="store_true", help="Remove every element")

    def handle(self, *args, **options):
        ark, qualifier = get_ark(options["ark"])
        bindings = ark.bindings.filter(qualifier=qualifier)

        if options["all"]:
            removed, _ = bindings.delete()
        elif options["element"]:
            removed, _ = bindings.filter(name=options["element"].strip().upper()).delete()
        else:
            raise CommandError("Give an element name, or --all to remove every element.")

        self.stdout.write(
            self.style.SUCCESS(f"Removed {removed} element(s) from {ark.name}{qualifier}")
        )
