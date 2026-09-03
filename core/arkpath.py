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
from dataclasses import dataclass
from enum import Enum

#: Trailing path segment that asks the resolver to proxy the target's JSON.
MANIFEST_SUFFIX = "manifest"

_ARK_RE = re.compile(r"^/?ark:/?(?P<rest>.*)$", re.IGNORECASE)


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
    manifest: bool
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
    def redirects(self) -> bool:
        """True when this request should end in a 302 rather than a metadata page."""
        return self.inflection is Inflection.NONE


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

    manifest = False
    if rest.endswith("/" + MANIFEST_SUFFIX):
        manifest = True
        rest = rest[: -(len(MANIFEST_SUFFIX) + 1)]

    trailing_slash = rest.endswith("/")
    parts = [p for p in rest.split("/") if p]

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
        manifest=manifest,
        naan_only=identifier == "" and (trailing_slash or len(parts) == 1),
    )
