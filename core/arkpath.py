"""
Parse an incoming ARK URL into the parts the resolver needs.

The shape follows the legacy resolver exactly, because ~100k production ARKs
depend on it: the ARK is the first two slash-separated components, and anything
after that is a qualifier. The qualifier splits into a hierarchy ('/page1') and
an optional variant ('.image.png') at the first dot after the last slash.

Legacy stored those two as separate tab-delimited key components; this system
stores the concatenation as a single ``qualifier``, which round-trips exactly.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass, replace
from enum import Enum
from urllib.parse import unquote

_ARK_RE = re.compile(r"^/?ark:/?(?P<rest>.*)$", re.IGNORECASE)

#: Why a hyphen may not be stored in a qualifier or a prefix. The ARK spec
#: makes hyphens insignificant (draft-kunze-ark-44 §3.2 step 6) and arks.org
#: removes them before forwarding to us, so a stored one could never be reached
#: through n2t.net or arks.org.
HYPHEN_REFUSED = (
    "may not contain a hyphen (-): N2T and arks.org remove hyphens before "
    "forwarding a request, so it could never be resolved through them."
)


class Inflection(Enum):
    """What metadata, if any, the caller asked for instead of a redirect."""

    NONE = ""
    #: '?' — the brief 'erc:' block.
    BRIEF = "?"
    #: '??' or '?info' — 'erc:' followed by 'erc-support:'.
    FULL = "??"


@dataclass(frozen=True)
class ArkPath:
    naan: str
    identifier: str
    qualifier: str
    inflection: Inflection
    naan_only: bool

    @property
    def name(self) -> str:
        """The bare ARK, e.g. ``61220/utsc1``."""
        return f"{self.naan}/{self.identifier}"

    @property
    def hierarchy(self) -> str:
        """The path portion of the qualifier, e.g. ``/page1``."""
        return _split_qualifier(self.qualifier)[0]

    @property
    def variant(self) -> str:
        """The variant portion of the qualifier, e.g. ``.image.png``."""
        return _split_qualifier(self.qualifier)[1]

    @property
    def last_segment(self) -> str:
        """The qualifier's last path segment, e.g. ``manifest`` for ``/page2/manifest``."""
        return last_segment(self.qualifier)

    @property
    def parent_qualifier(self) -> str:
        """The qualifier without its last segment, e.g. ``/page2`` for ``/page2/manifest``."""
        return parent_qualifier(self.qualifier)

    @property
    def redirects(self) -> bool:
        """True when this request should end in a 302 rather than a metadata page."""
        return self.inflection is Inflection.NONE

    def normalised(self) -> ArkPath | None:
        """
        This ARK as the spec compares it, or None when that changes nothing.

        draft-kunze-ark-44 §3.2: hyphens are insignificant (step 6) and trailing
        '/' and '.' are removed (step 8), so 'utsc-1', 'utsc1.' and 'utsc1' are
        one ARK. The resolver tries this only after the request as written has
        missed, so every stored ARK keeps exact matching. Case is kept: names
        and qualifiers are case-sensitive.
        """
        qualifier = self.qualifier.replace("-", "").rstrip("./")
        identifier = self.identifier.replace("-", "")
        if not qualifier:
            # The trailing characters belong to the last component, which is
            # the identifier itself when there is no qualifier left.
            identifier = identifier.rstrip("./")
        if not identifier or (identifier, qualifier) == (self.identifier, self.qualifier):
            return None
        return replace(self, identifier=identifier, qualifier=qualifier)

    def object_variant(self) -> ArkPath | None:
        """
        ``utsc1.image.png`` read as the variant ``.image.png`` of ``utsc1``, or None.

        The parse keeps a dot in the identifier component, as legacy's did, so
        a variant of the object itself (draft-kunze-ark-44 §2.5) is looked up
        as an ARK named ``utsc1.image.png``. This is the other reading, which
        matches how such a variant is stored: ARK ``utsc1``, qualifier
        ``.image.png``. Any qualifier after it is kept behind the variant, so
        ``utsc1.image.png/manifest`` asks for the variant's manifest
        (qualifier ``.image.png/manifest``). Only with something on both sides
        of the dot: ``utsc1.`` is a trailing full stop, which ``normalised()``
        handles.
        """
        base, dot, rest = self.identifier.partition(".")
        if not dot or not base or not rest:
            return None
        return replace(self, identifier=base, qualifier=dot + rest + self.qualifier)

    def alternatives(self) -> Iterator[ArkPath]:
        """
        Other readings of this request, in the order to try them after a miss.

        As written but read as a variant of the object, then the spec-normalised
        form, then that read as a variant. Each is yielded once, and never this
        form itself.
        """
        normalised = self.normalised()
        seen = {(self.identifier, self.qualifier)}
        for form in (
            self.object_variant(),
            normalised,
            normalised.object_variant() if normalised is not None else None,
        ):
            if form is not None and (form.identifier, form.qualifier) not in seen:
                seen.add((form.identifier, form.qualifier))
                yield form


def last_segment(qualifier: str) -> str:
    """The text after the qualifier's last '/', or '' when there is no qualifier."""
    if not qualifier:
        return ""
    return qualifier.rpartition("/")[2]


def parent_qualifier(qualifier: str) -> str:
    """The qualifier without its last '/' segment ('' for a single segment)."""
    if not qualifier:
        return ""
    return qualifier.rpartition("/")[0]


def _split_qualifier(qualifier: str) -> tuple[str, str]:
    """Split '/vol1/page3.jpg' into ('/vol1/page3', '.jpg')."""
    if not qualifier:
        return "", ""
    last_slash = qualifier.rfind("/")
    dot = qualifier.find(".", last_slash + 1)
    if dot == -1:
        return qualifier, ""
    return qualifier[:dot], qualifier[dot:]


def _detect_inflection(raw: str) -> tuple[str, Inflection]:
    """
    Split ``raw`` at the first '?' and classify what followed it.

    A bare '?' asks for brief metadata, '??' and '?info' for the full record.
    Anything else is an ordinary query string and is discarded, exactly as the
    legacy rewrite did (it passed only the path through to the resolver).
    """
    index = raw.find("?")
    if index == -1:
        return raw, Inflection.NONE

    path, query = raw[:index], raw[index + 1 :]
    if query == "":
        return path, Inflection.BRIEF
    if query in ("?", "info"):
        return path, Inflection.FULL
    return path, Inflection.NONE


def parse_ark_path(path: str) -> ArkPath | None:
    """
    Parse ``path`` (with or without a leading slash, ``ark:/`` or ``ark:``).

    Returns ``None`` when the path is not an ARK at all.
    """
    if not path:
        return None

    raw = path.strip()
    match = _ARK_RE.match(raw)
    if not match:
        return None

    rest, inflection = _detect_inflection(match.group("rest").strip())

    # A service suffix such as '/manifest' stays part of the qualifier: which
    # suffixes are services is a setting of the ARK's collection, known only
    # once the ARK is found (resolver.views._resolution_target).
    trailing_slash = rest.endswith("/")
    # Split on the structural characters *before* decoding, so that an encoded
    # '/' (%2F) stays inside one component and an encoded '?' (%3F) is never
    # mistaken for an inflection. Legacy compared the decoded path (Apache
    # handed resolver.php a decoded $_GET['q']) and the import stores legacy
    # keys literally, so the comparison here has to be against decoded text.
    parts = [unquote(p) for p in rest.split("/") if p]

    if not parts:
        return None

    naan = parts[0]
    identifier = parts[1] if len(parts) > 1 else ""
    qualifier = "/" + "/".join(parts[2:]) if len(parts) > 2 else ""

    return ArkPath(
        naan=naan,
        identifier=identifier,
        qualifier=qualifier,
        inflection=inflection,
        naan_only=identifier == "" and (trailing_slash or len(parts) == 1),
    )
