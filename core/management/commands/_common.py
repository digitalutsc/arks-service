"""Shared helpers for the ARK management commands."""

from django.core.management.base import CommandError

from core.arkpath import parse_ark_path
from core.models import Ark, Collection


def get_collection(reference: str) -> Collection:
    """Find a collection by prefix, then by name."""
    collection = Collection.objects.filter(prefix=reference).first()
    if collection is None:
        collection = Collection.objects.filter(name=reference).first()
    if collection is None:
        known = ", ".join(Collection.objects.values_list("prefix", flat=True)) or "none"
        raise CommandError(f"No collection with prefix or name {reference!r}. Known: {known}")
    return collection


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
    if ark is None:
        raise CommandError(f"No such ARK: {parsed.name}")
    return ark, parsed.qualifier
