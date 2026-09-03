"""
Core data model.

Deliberately portable across PostgreSQL and MySQL/MariaDB: no JSON columns, no
database regex, no engine-specific full-text. The legacy service stored
everything as tab-separated keys in per-collection ``_key``/``_value`` tables;
here the same information is normalised into collections, ARKs and bindings.
"""

from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone

from minting.noid import TemplateError, TemplateSpec, parse_template

#: Element names the resolver and reports understand. Any other name may still
#: be bound — these are conventions, not a schema.
ELEMENT_URL = "URL"
ELEMENT_WHERE = "WHERE?"
ELEMENT_PID = "PID"
ELEMENT_LOCAL_ID = "LOCAL_ID"
CONVENTIONAL_ELEMENTS = (ELEMENT_URL, ELEMENT_PID, ELEMENT_LOCAL_ID, "COLLECTION")


class Collection(models.Model):
    """A minter: one noid template, one prefix, one namespace."""

    class Term(models.TextChoices):
        SHORT = "short", "Short"
        MEDIUM = "medium", "Medium"
        LONG = "long", "Long"

    name = models.CharField(max_length=255, unique=True)
    prefix = models.CharField(
        max_length=64,
        unique=True,
        blank=True,
        help_text="Constant string after the NAAN, e.g. 'utsc'. Must be unique.",
    )
    naan = models.CharField("NAAN", max_length=16, help_text="Name Assigning Authority Number.")
    naa = models.TextField(
        "NAA",
        blank=True,
        help_text="Name Assigning Authority, returned for /ark:/<naan>/ with no identifier.",
    )
    template = models.CharField(
        max_length=64,
        help_text="noid template, e.g. '.zd' for unlimited sequential digits.",
    )
    term = models.CharField(max_length=16, choices=Term.choices, default=Term.MEDIUM)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name

    @property
    def firstpart(self) -> str:
        """The constant leading part of every ARK in this collection."""
        return f"{self.naan}/{self.prefix}"

    @property
    def full_template(self) -> str:
        """Prefix and template joined, the form noid actually parses."""
        return f"{self.prefix}{self.template}"

    @property
    def spec(self) -> TemplateSpec:
        return parse_template(self.full_template)

    @property
    def is_random(self) -> bool:
        return self.spec.is_random

    def clean(self):
        try:
            parse_template(self.full_template)
        except TemplateError as exc:
            raise ValidationError({"template": str(exc)}) from exc


class Ark(models.Model):
    """A minted identifier. Qualifiers live on bindings, not here."""

    collection = models.ForeignKey(Collection, on_delete=models.CASCADE, related_name="arks")
    naan = models.CharField(max_length=16, blank=True)
    identifier = models.CharField(
        max_length=255, help_text="Everything after the NAAN, including the prefix."
    )
    minted_at = models.DateTimeField(default=timezone.now)
    minted_by = models.ForeignKey(
        "auth.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="minted_arks"
    )

    class Meta:
        constraints = [
            # The resolver's guarantee: an ARK identifies exactly one thing.
            models.UniqueConstraint(fields=["naan", "identifier"], name="unique_ark_per_naan"),
        ]
        indexes = [
            models.Index(fields=["collection", "identifier"], name="ark_collection_ident_idx"),
            models.Index(fields=["minted_at"], name="ark_minted_at_idx"),
        ]
        ordering = ["naan", "identifier"]

    def __str__(self) -> str:
        return self.name

    def save(self, *args, **kwargs):
        if not self.naan and self.collection_id:
            self.naan = self.collection.naan
        super().save(*args, **kwargs)

    @property
    def name(self) -> str:
        """The ARK itself, e.g. ``61220/utsc1``."""
        return f"{self.naan}/{self.identifier}"


class Binding(models.Model):
    """
    One element bound to an ARK, optionally under a qualifier.

    ``qualifier`` is '' for the ARK itself, '/page1' for a hierarchical part,
    '.image.png' for a variant, or '/page1.image.png' for both — exactly the
    shapes the legacy tab-separated keys encoded.
    """

    ark = models.ForeignKey(Ark, on_delete=models.CASCADE, related_name="bindings")
    qualifier = models.CharField(max_length=255, blank=True, default="")
    name = models.CharField(max_length=255)
    value = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["ark", "qualifier", "name"], name="unique_element_per_qualifier"
            ),
        ]
        indexes = [
            # `value` is unbounded TEXT, which MySQL cannot index without a
            # prefix length, so search filters on name and scans values (see
            # README: LIKE is the portable baseline).
            models.Index(fields=["name"], name="binding_name_idx"),
            models.Index(fields=["ark", "qualifier"], name="binding_ark_qualifier_idx"),
        ]
        ordering = ["name"]

    def __str__(self) -> str:
        return f"{self.ark.name}{self.qualifier} {self.name}"

    def save(self, *args, **kwargs):
        # Legacy upper-cased element names on bind; keep lookups predictable.
        self.name = (self.name or "").strip().upper()
        super().save(*args, **kwargs)


class Resolution(models.Model):
    """Redirect counter, one row per (ARK, qualifier) actually resolved."""

    ark = models.ForeignKey(Ark, on_delete=models.CASCADE, related_name="resolutions")
    qualifier = models.CharField(max_length=255, blank=True, default="")
    count = models.BigIntegerField(default=0)
    last_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["ark", "qualifier"], name="unique_resolution_per_qualifier"
            ),
        ]
        ordering = ["-count"]

    def __str__(self) -> str:
        return f"{self.ark.name}{self.qualifier}: {self.count}"

    @classmethod
    def record(cls, ark: Ark, qualifier: str = "") -> None:
        """Count one redirect, without reading the current value first."""
        with transaction.atomic():
            updated = cls.objects.filter(ark=ark, qualifier=qualifier).update(
                count=models.F("count") + 1, last_at=timezone.now()
            )
            if not updated:
                cls.objects.create(ark=ark, qualifier=qualifier, count=1, last_at=timezone.now())


class Organisation(models.Model):
    """Singleton replacing the legacy ``system`` table."""

    name = models.CharField(max_length=255, blank=True)
    website = models.URLField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "organisation"

    def __str__(self) -> str:
        return self.name or "Organisation"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls) -> Organisation:
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj
