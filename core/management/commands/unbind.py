"""Remove elements from an ARK."""

from django.core.management.base import BaseCommand, CommandError

from core.management.commands._common import get_ark
from core.services import unbind_elements


class Command(BaseCommand):
    help = "Remove one element from an ARK, or all of them."

    def add_arguments(self, parser):
        parser.add_argument("ark")
        parser.add_argument("element", nargs="?", help="Element name; omit with --all")
        parser.add_argument(
            "--all",
            action="store_true",
            help="Remove every element. On a bare ARK that means every qualifier too, "
            "so the ARK stops resolving entirely; name a qualifier to scope it.",
        )

    def handle(self, *args, **options):
        ark, qualifier = get_ark(options["ark"])

        if options["all"]:
            # A bare ARK means the whole ARK, parts included — otherwise
            # "retire this ARK" would leave its parts resolving, and the command
            # would disagree with the UI's "Purge all elements".
            removed = unbind_elements(ark, qualifier=qualifier or None)
        elif options["element"]:
            removed = unbind_elements(ark, name=options["element"], qualifier=qualifier)
        else:
            raise CommandError("Give an element name, or --all to remove every element.")

        self.stdout.write(
            self.style.SUCCESS(f"Removed {removed} element(s) from {ark.name}{qualifier}")
        )
