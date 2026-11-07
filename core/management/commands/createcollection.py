"""Create a collection (a minter)."""

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import IntegrityError

from core.models import DEFAULT_PROXIED_SUFFIXES, DEFAULT_REDIRECT_ELEMENTS, Collection
from core.services import parse_proxied_suffixes, parse_redirect_elements, prefix_problem


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
        parser.add_argument(
            "--redirect-elements",
            default=DEFAULT_REDIRECT_ELEMENTS,
            help="Elements holding the redirect URL, in order (default: %(default)s)",
        )
        parser.add_argument(
            "--suffix-passthrough",
            action="store_true",
            help="Let a part with no URL of its own redirect to its nearest bound ancestor's "
            "URL plus the rest of the path (off by default, as in legacy)",
        )
        parser.add_argument(
            "--proxied-suffixes",
            default=DEFAULT_PROXIED_SUFFIXES,
            help="Final qualifier segments answered with the target's JSON instead of a "
            "redirect; '' for none (default: %(default)s)",
        )

    def handle(self, *args, **options):
        problem = prefix_problem(options["prefix"])
        if problem:
            raise CommandError(f"prefix: {problem}")
        try:
            elements = parse_redirect_elements(options["redirect_elements"])
            suffixes = parse_proxied_suffixes(options["proxied_suffixes"])
        except ValidationError as exc:
            raise CommandError(
                "; ".join(f"{k}: {' '.join(v)}" for k, v in exc.message_dict.items())
            ) from exc
        collection = Collection(
            redirect_elements=",".join(elements),
            proxied_suffixes=",".join(suffixes),
            suffix_passthrough=options["suffix_passthrough"],
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
        self.stdout.write(f"  redirects from {', '.join(collection.redirect_element_list)}")
        suffixes = ", ".join(collection.proxied_suffix_list) or "(none)"
        self.stdout.write(f"  proxied suffixes {suffixes}")
        self.stdout.write(
            f"  suffix passthrough {'on' if collection.suffix_passthrough else 'off'}"
        )
