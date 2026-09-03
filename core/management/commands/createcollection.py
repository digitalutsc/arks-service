"""Create a collection (a minter)."""

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import IntegrityError

from core.models import Collection


class Command(BaseCommand):
    help = "Create a collection with its own prefix, NAAN and noid template."

    def add_arguments(self, parser):
        parser.add_argument("name", help="Human-readable name, e.g. 'UTSC Digital Collections'")
        parser.add_argument("--prefix", default="", help="Constant after the NAAN, e.g. 'utsc'")
        parser.add_argument("--naan", required=True, help="Name Assigning Authority Number")
        parser.add_argument(
            "--naa", default="", help="Name Assigning Authority (shown for /ark:/<naan>/)"
        )
        parser.add_argument("--template", required=True, help="noid template, e.g. '.zd'")
        parser.add_argument("--term", default="medium", choices=["short", "medium", "long"])

    def handle(self, *args, **options):
        collection = Collection(
            name=options["name"],
            prefix=options["prefix"],
            naan=options["naan"],
            naa=options["naa"],
            template=options["template"],
            term=options["term"],
        )
        try:
            collection.full_clean()
            collection.save()
        except ValidationError as exc:
            raise CommandError(
                "; ".join(f"{k}: {' '.join(v)}" for k, v in exc.message_dict.items())
            ) from exc
        except IntegrityError as exc:
            raise CommandError(
                f"Could not create the collection (prefix or name already used): {exc}"
            ) from exc

        spec = collection.spec
        self.stdout.write(self.style.SUCCESS(f"Created collection {collection.name!r}"))
        self.stdout.write(f"  prefix   {collection.prefix or '(none)'}")
        self.stdout.write(f"  firstpart {collection.firstpart}")
        self.stdout.write(f"  template {collection.template} (mask {spec.mask}, {spec.gen_type})")
        capacity = "unlimited" if spec.unlimited else f"{spec.total:,} identifiers"
        self.stdout.write(f"  capacity {capacity}")
