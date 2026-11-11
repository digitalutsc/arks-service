"""
Core data model.

Deliberately portable across PostgreSQL and MySQL/MariaDB: no JSON columns, no
database regex, no engine-specific full-text. The legacy service stored
everything as tab-separated keys in per-collection ``_key``/``_value`` tables;
here the same information is normalised into collections, ARKs and bindings.
"""

from __future__ import annotations

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import IntegrityError, models, transaction
from django.db.models.functions import Lower, Substr
from django.utils import timezone

from minting.noid import TemplateError, TemplateSpec, parse_template

#: How much of a value is copied into the indexed prefix column. 191 keeps the
#: (name, value_prefix) index inside MySQL's 3072-byte utf8mb4 limit alongside
#: a 255-character name.
VALUE_PREFIX_LENGTH = 191


def value_prefix(value: str | None) -> str:
    """The indexed, case-folded leading part of a bound value."""
    return (value or "")[:VALUE_PREFIX_LENGTH].lower()


#: The two elements the legacy resolver looked for, in order. They are the
#: default of Collection.redirect_elements, which each collection may change.
#: Any other name may still be bound: these are conventions, not a schema. The
#: columns offered in the fill-in template live in jobs.bulkbind.TEMPLATE_COLUMNS.
ELEMENT_URL = "URL"
ELEMENT_WHERE = "WHERE?"

#: Collection.redirect_elements for a new collection: exactly the legacy order.
DEFAULT_REDIRECT_ELEMENTS = f"{ELEMENT_URL},{ELEMENT_WHERE}"

#: Collection.proxied_suffixes for a new collection: legacy's /manifest.
DEFAULT_PROXIED_SUFFIXES = "manifest"


def split_setting(text: str | None) -> list[str]:
    """A stored comma-separated setting as a list (no JSON columns: see above)."""
    return [part for part in (text or "").split(",") if part]


class Collection(models.Model):
    """A minter: one noid template, one prefix, one namespace."""

    class Term(models.TextChoices):
        SHORT = "short", "Short"
        MEDIUM = "medium", "Medium"
        LONG = "long", "Long"

    name = models.CharField(max_length=255, unique=True)
    prefix = models.CharField(
        max_length=64,
        blank=True,
        help_text="Constant string after the NAAN, e.g. 'utsc'. Must be unique within its NAAN.",
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
    # Every collection is long-term: Short and Medium change nothing here, so the
    # form, createcollection and import_legacy all set Long, and so does the default.
    term = models.CharField(max_length=16, choices=Term.choices, default=Term.LONG)
    created_at = models.DateTimeField(auto_now_add=True)

    # Resolution settings (INTENTS_collection_resolution_settings.md). Both are
    # comma-separated and already validated (core.services.parse_redirect_elements,
    # parse_proxied_suffixes); the defaults reproduce the legacy resolver.
    redirect_elements = models.CharField(
        max_length=255,
        default=DEFAULT_REDIRECT_ELEMENTS,
        help_text="Elements holding the redirect URL, in order; the first bound wins.",
    )
    proxied_suffixes = models.CharField(
        max_length=255,
        blank=True,
        default=DEFAULT_PROXIED_SUFFIXES,
        help_text="Final qualifier segments answered by proxying JSON instead of redirecting.",
    )
    # Suffix passthrough (R6, INTENTS_suffix_passthrough.md): a part with no URL
    # of its own redirects to its nearest bound ancestor's URL plus the rest of
    # the path. Off by default: the legacy contract is "no fallback up the
    # hierarchy", and the imported collection keeps it until an admin opts in.
    suffix_passthrough = models.BooleanField(
        default=False,
        help_text="Unbound parts redirect to the nearest bound ancestor's URL plus the rest of the path.",
    )
    resolution_changed_at = models.DateTimeField(null=True, blank=True)
    resolution_changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    # Statistics, refreshed by the scheduler (core.services.refresh_collection_stats).
    # Counting a large collection on every page view is a full index scan:
    # about 8 s at 4M ARKs. Small collections are still counted live.
    ark_count = models.BigIntegerField(default=0)
    bound_count = models.BigIntegerField(default=0)
    binding_count = models.BigIntegerField(default=0)
    redirect_total = models.BigIntegerField(default=0)
    stats_refreshed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            # Unique within a NAAN, not across the service: two naming
            # authorities may each have a "utsc" prefix, and their ARKs are
            # still told apart by the NAAN.
            models.UniqueConstraint(fields=["naan", "prefix"], name="unique_prefix_per_naan"),
        ]

    def __str__(self) -> str:
        return self.name

    @property
    def redirect_element_list(self) -> list[str]:
        """The elements the resolver reads a redirect URL from, in order."""
        return split_setting(self.redirect_elements)

    @property
    def proxied_suffix_list(self) -> list[str]:
        """Final qualifier segments that ask for the target's JSON instead of a redirect."""
        return split_setting(self.proxied_suffixes)

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
    sequence = models.BigIntegerField(
        null=True,
        blank=True,
        help_text="Counter value this identifier was generated from; lets minting "
        "continue where a previous run (or an import) left off.",
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
            models.Index(fields=["collection", "sequence"], name="ark_collection_seq_idx"),
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

    @property
    def path(self) -> str:
        """The resolver path for this ARK, e.g. ``ark:61220/utsc1``.

        Relative on purpose: the host belongs to the environment, not to the
        identifier (see ``admin_ui.context_processors.environment``).
        """
        return f"ark:{self.name}"


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
    #: Maintained by the database, not by application code. TEXT cannot be
    #: indexed on MySQL without a prefix length, so exact and starts-with
    #: lookups go through this column and then re-check `value`. Making it
    #: generated means no bulk writer can forget it and quietly create rows
    #: that search cannot find.
    value_prefix = models.GeneratedField(
        expression=Lower(Substr("value", 1, VALUE_PREFIX_LENGTH)),
        output_field=models.CharField(max_length=VALUE_PREFIX_LENGTH),
        db_persist=True,
    )
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
            models.Index(fields=["name", "value_prefix"], name="binding_name_value_idx"),
            # No separate (ark, qualifier) index: the unique (ark, qualifier,
            # name) above starts with the same columns and serves those lookups
            # and the ark_id foreign key. A second copy cost every write.
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
        """
        Count one redirect, without reading the current value first.

        The row usually exists, so try the update first. When it does not, two
        callers can both find nothing and both try to insert; the loser catches
        the unique-constraint violation and increments instead. Getting this
        wrong turns the first hit on a freshly imported ARK — exactly what a
        crawler produces after a cutover — into a 500.
        """
        now = timezone.now()
        if cls._increment(ark, qualifier, now):
            return

        try:
            with transaction.atomic():
                cls.objects.create(ark=ark, qualifier=qualifier, count=1, last_at=now)
        except IntegrityError:
            # Someone else created it between our update and our insert.
            cls._increment(ark, qualifier, now)

    @classmethod
    def _increment(cls, ark: Ark, qualifier: str, now) -> int:
        return cls.objects.filter(ark=ark, qualifier=qualifier).update(
            count=models.F("count") + 1, last_at=now
        )


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
