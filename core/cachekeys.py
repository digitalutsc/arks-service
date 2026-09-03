"""
Cache keys shared between the resolver and the write paths.

Kept in their own module so a writer cannot invalidate a key the reader does not
use: both sides import the same function.
"""

from __future__ import annotations

#: How long a resolved target may be reused. Short even though every write path
#: invalidates explicitly — a cache that outlived an invalidation it missed
#: would redirect people to the wrong place.
TARGET_CACHE_SECONDS = 300


def target_cache_key(ark_id: int, qualifier: str) -> str:
    return f"ark-target:{ark_id}:{qualifier}"
