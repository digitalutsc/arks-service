"""
Progress of a running job, kept in the cache.

A bulk bind applies the whole file and records its outcome in one transaction,
so a progress column on the job row would be invisible to the web process until
commit. The worker writes its phase and counts to one cache key instead; the
job page reads that key each time it polls. The key is throttled so a 100k-row
file does not cost 100k cache writes, and it expires on its own, so a worker
that dies mid-job leaves nothing behind that needs cleaning up.

Nothing here is load-bearing: a cache that is down loses the bar, not the job.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable

from django.core.cache import cache

logger = logging.getLogger(__name__)

#: Seconds a progress key lives without being refreshed.
LIFETIME = 60 * 60

#: Least time between two writes within the same phase.
MIN_INTERVAL = 0.5

#: Human labels for the phases the work reports. Unknown phases fall back to
#: "Working…", so a new phase never breaks the page before it has a label.
PHASES = {
    "reading": "Reading the file",
    "checking": "Checking rows",
    "minting": "Minting new ARKs",
    "purging": "Removing previous elements",
    "writing": "Writing bindings",
}

WORKING = "Working…"
WAITING = "Waiting for a worker"

#: The callback shape the work accepts: ``progress(phase, done, total)``.
#: ``total`` is None while it is not yet known.
Progress = Callable[[str, int, "int | None"], None]


def key(kind: str, ident) -> str:
    return f"job-progress:{kind}:{ident}"


def read(kind: str, ident) -> dict | None:
    """The last reported state, or None when nothing has been reported."""
    try:
        return cache.get(key(kind, ident))
    except Exception:  # noqa: BLE001 - the bar is cosmetic
        logger.warning("could not read progress for %s %s", kind, ident, exc_info=True)
        return None


def clear(kind: str, ident) -> None:
    try:
        cache.delete(key(kind, ident))
    except Exception:  # noqa: BLE001
        logger.warning("could not clear progress for %s %s", kind, ident, exc_info=True)


class Reporter:
    """
    A ``progress`` callback that writes to the cache, throttled.

    A phase change and the end of a phase are always written; within a phase,
    at most one write per ``interval`` seconds. ``finish()`` removes the key once
    the job row holds the final counts.
    """

    def __init__(
        self,
        kind: str,
        ident,
        *,
        interval: float = MIN_INTERVAL,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.key = key(kind, ident)
        self.interval = interval
        self.clock = clock
        self._phase: str | None = None
        self._last = float("-inf")

    def __call__(self, phase: str, done: int, total: int | None) -> None:
        now = self.clock()
        if (
            phase == self._phase
            and not (total is not None and done >= total)
            and now - self._last < self.interval
        ):
            return
        self._phase, self._last = phase, now
        try:
            cache.set(self.key, {"phase": phase, "done": done, "total": total}, LIFETIME)
        except Exception:  # noqa: BLE001 - the bar is cosmetic
            logger.warning("could not write progress to %s", self.key, exc_info=True)

    def finish(self) -> None:
        try:
            cache.delete(self.key)
        except Exception:  # noqa: BLE001
            logger.warning("could not clear progress at %s", self.key, exc_info=True)


def describe(state: dict | None, *, pending: bool = False) -> dict:
    """
    What the page shows for a job that has not finished.

    Returns ``{"label", "done", "total"}``; ``total`` is None when the bar should
    be indeterminate (no worker yet, nothing reported, or a phase whose size is
    not known).
    """
    if pending:
        return {"label": WAITING, "done": None, "total": None}
    if not state:
        return {"label": WORKING, "done": None, "total": None}
    label = PHASES.get(state.get("phase"), WORKING)
    done, total = state.get("done") or 0, state.get("total")
    if total:
        return {"label": f"{label} {done:,} of {total:,}", "done": done, "total": total}
    return {"label": label, "done": None, "total": None}
