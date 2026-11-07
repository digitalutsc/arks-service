"""
Check every manifest the resolver would proxy, before users find a broken one.

Read-only. For each binding at a proxied suffix (``…/manifest`` by default; the
collection's ``proxied_suffixes``) it takes the URL the resolver would use (the
collection's ``redirect_elements``, in order) and fetches it exactly as the
resolver does: the same guarded ``fetch_json``, the same size and time limits,
no redirects. It reports what came back.

    manage.py check_manifests --collection utsc --out manifests.csv
    manage.py check_manifests --sample 200 --workers 4

Every row is one GET to the target's site, so keep ``--workers`` low against
servers that build manifests on demand. Only explicitly bound suffix targets
are checked: an ARK with nothing at ``/manifest`` falls back to its own URL,
which is usually a web page and not meant to be a manifest.
"""

from __future__ import annotations

import csv
import json
import time
import urllib.error
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from django.core.management.base import BaseCommand

from core.management.commands._common import get_collection
from core.models import Binding, Collection
from resolver.services import TargetTooLarge, TargetTooSlow, UnsafeTarget, fetch_json

#: Outcomes, in the order the summary lists them.
OUTCOMES = (
    "ok",
    "empty",
    "not-json",
    "too-large",
    "too-slow",
    "redirect",
    "http-error",
    "refused",
    "failed",
)

#: Problems listed on screen after the summary; the CSV has every row.
SHOW_PROBLEMS = 20


@dataclass(frozen=True)
class Target:
    ark: str
    qualifier: str
    url: str


@dataclass(frozen=True)
class Result:
    target: Target
    outcome: str
    status: str
    size: int
    seconds: float
    detail: str

    def as_row(self) -> list[str]:
        return [
            self.target.ark,
            self.target.qualifier,
            self.target.url,
            self.outcome,
            self.status,
            str(self.size),
            f"{self.seconds:.2f}",
            self.detail,
        ]


def iter_targets(collection: Collection):
    """
    The URL the resolver would proxy for each bound suffix qualifier in ``collection``.

    Ordered by ARK and qualifier; the first of the collection's redirect
    elements with a value wins, as in ``resolver.views._target_url``.
    """
    elements = collection.redirect_element_list
    for suffix in collection.proxied_suffix_list:
        rows = (
            Binding.objects.filter(
                ark__collection=collection,
                qualifier__endswith=f"/{suffix}",
                name__in=elements,
            )
            .exclude(value="")
            .order_by("ark__naan", "ark__identifier", "qualifier")
            .values_list("ark__naan", "ark__identifier", "qualifier", "name", "value")
        )
        current, found = None, {}
        for naan, identifier, qualifier, name, value in rows.iterator(chunk_size=2000):
            key = (f"{naan}/{identifier}", qualifier)
            if key != current:
                if current is not None:
                    yield _pick(current, found, elements)
                current, found = key, {}
            found[name] = value
        if current is not None:
            yield _pick(current, found, elements)


def _pick(key, found: dict[str, str], elements: list[str]) -> Target:
    url = next(found[name] for name in elements if found.get(name))
    return Target(ark=key[0], qualifier=key[1], url=url)


def check(target: Target) -> Result:
    """Fetch one target the way the resolver would, and classify the answer."""
    started = time.monotonic()

    def result(outcome, status="", size=0, detail=""):
        return Result(target, outcome, status, size, time.monotonic() - started, detail)

    try:
        body = fetch_json(target.url)
    except UnsafeTarget as exc:
        return result("refused", detail=str(exc))
    except TargetTooLarge as exc:
        return result("too-large", detail=str(exc))
    except (TargetTooSlow, TimeoutError) as exc:
        return result("too-slow", detail=str(exc) or "timed out")
    except urllib.error.HTTPError as exc:
        if 300 <= exc.code < 400:
            location = exc.headers.get("Location", "") if exc.headers else ""
            return result("redirect", str(exc.code), detail=location)
        return result("http-error", str(exc.code), detail=str(exc.reason))
    except Exception as exc:  # DNS, TLS, connection reset: worth a row, not a crash
        return result("failed", detail=f"{type(exc).__name__}: {exc}")

    try:
        data = json.loads(body)
    except (ValueError, TypeError):
        return result("not-json", "200", len(body), body[:80].decode("utf-8", "replace"))
    if data in ({}, [], None, ""):
        return result("empty", "200", len(body), body[:80].decode("utf-8", "replace"))
    return result("ok", "200", len(body))


class Command(BaseCommand):
    help = "Fetch every proxied-suffix target (e.g. /manifest) as the resolver would, and report."

    def add_arguments(self, parser):
        parser.add_argument("--collection", help="Only check this collection")
        parser.add_argument("--out", help="Write every result to this CSV")
        parser.add_argument(
            "--workers",
            type=int,
            default=4,
            help="Fetches at once (default %(default)s); keep it low for on-demand manifests",
        )
        parser.add_argument("--sample", type=int, help="Only check the first N targets")

    def handle(self, *args, **options):
        collections = (
            [get_collection(options["collection"])]
            if options["collection"]
            else list(Collection.objects.all())
        )
        targets = [target for each in collections for target in iter_targets(each)]
        if options["sample"]:
            targets = targets[: options["sample"]]
        self.stdout.write(f"Checking {len(targets):,} manifest target(s) ...")

        results: list[Result] = []
        with ThreadPoolExecutor(max_workers=max(1, options["workers"])) as pool:
            for done, each in enumerate(pool.map(check, targets), start=1):
                results.append(each)
                if done % 500 == 0:
                    self.stdout.write(f"  {done:,} checked")

        if options["out"]:
            with open(options["out"], "w", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(
                    ["ark", "qualifier", "url", "outcome", "status", "bytes", "seconds", "detail"]
                )
                writer.writerows(each.as_row() for each in results)
            self.stdout.write(f"Wrote {len(results):,} row(s) to {options['out']}")

        counts = Counter(each.outcome for each in results)
        summary = " · ".join(f"{name} {counts[name]:,}" for name in OUTCOMES if counts[name])
        self.stdout.write(f"{len(results):,} manifest(s): {summary or 'none'}")
        if results:
            slowest = max(results, key=lambda each: each.seconds)
            self.stdout.write(
                f"Slowest {slowest.seconds:.2f}s: {slowest.target.ark}{slowest.target.qualifier}"
            )

        problems = [each for each in results if each.outcome != "ok"]
        for each in problems[:SHOW_PROBLEMS]:
            self.stdout.write(
                f"  {each.outcome:10} {each.target.ark}{each.target.qualifier} -> "
                f"{each.target.url} {each.status} {each.detail}".rstrip()
            )
        if len(problems) > SHOW_PROBLEMS:
            self.stdout.write(f"  … and {len(problems) - SHOW_PROBLEMS:,} more (see --out)")
