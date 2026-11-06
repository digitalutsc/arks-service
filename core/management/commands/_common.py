"""Shared helpers for the ARK management commands."""

from django.core.management.base import CommandError

from core.arkpath import parse_ark_path
from core.models import Ark, Collection


def get_collection(reference: str) -> Collection:
    """
    Find a collection by name, or by prefix when that is unambiguous.

    A prefix is only unique within a NAAN, so "61220/utsc" also works when two
    naming authorities share one.
    """
    collection = Collection.objects.filter(name=reference).first()
    if collection is not None:
        return collection

    if "/" in reference:
        naan, _, prefix = reference.partition("/")
        collection = Collection.objects.filter(naan=naan, prefix=prefix).first()
        if collection is not None:
            return collection

    matches = list(Collection.objects.filter(prefix=reference)[:2])
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise CommandError(
            f"More than one collection uses the prefix {reference!r}. "
            "Name it as <naan>/<prefix>, e.g. 61220/utsc."
        )

    known = ", ".join(f"{c.naan}/{c.prefix}" for c in Collection.objects.all()) or "none"
    raise CommandError(f"No collection with prefix or name {reference!r}. Known: {known}")


def get_ark(reference: str):
    """
    Resolve 'naan/identifier[/qualifier]' to an ARK and its qualifier.

    Accepts the same spellings the resolver does, so an ARK copied out of a URL
    or an export works unchanged.
    """
    parsed = parse_ark_path(f"ark:/{reference.lstrip('/')}")
    if parsed is None or not parsed.identifier:
        raise CommandError(f"{reference!r} is not a valid ARK.")
    ark = Ark.objects.filter(naan=parsed.naan, identifier=parsed.identifier).first()
    if ark is None and (variant := parsed.object_variant()) is not None:
        # 'utsc1.pdf' with no ARK of that name: the variant '.pdf' of utsc1,
        # which is how export and the ARK page write it.
        ark = Ark.objects.filter(naan=variant.naan, identifier=variant.identifier).first()
        if ark is not None:
            parsed = variant
    if ark is None:
        raise CommandError(f"No such ARK: {parsed.name}")
    return ark, parsed.qualifier
