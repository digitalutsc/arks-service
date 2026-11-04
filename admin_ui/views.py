"""
The staff interface.

Server-rendered with a little HTMX for the search table and job progress — no
build step, no API. Views talk to the ORM and the same services the management
commands use, so the two can never drift apart.
"""

from __future__ import annotations

import csv
import logging
import re
from datetime import datetime, time

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Count, Sum
from django.http import Http404, HttpResponse, QueryDict, StreamingHttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.utils.http import urlencode
from django.utils.text import slugify
from django.views.decorators.http import require_POST

from admin_ui.roles import (
    ADMIN,
    EDITOR,
    ROLES,
    VIEWER,
    can_administer,
    can_edit,
    clear_role,
    ensure_groups,
    is_last_administrator,
    require_role,
    role_of,
    set_role,
)
from core.models import Ark, Binding, Collection, Organisation, Resolution
from core.search import (
    DEFAULT_SORT,
    SORT_DESC_FIRST,
    counted,
    element_names,
    export_rows,
    parse_sort,
    search_arks,
    sort_arks,
)
from core.services import bind_element, collection_stats, unbind_elements
from jobs.bulkbind import STATUS_ERROR, STATUS_MINTED, STATUS_OK, TEMPLATE_COLUMNS, template_csv
from jobs.models import RESULT_COLUMNS, BulkBindJob
from jobs.tasks import run_bulk_bind
from minting.minter import MintError, mint
from minting.noid import TemplateError, template_choices

logger = logging.getLogger(__name__)

PAGE_SIZE = 50

#: Deep pages cost the database an ever larger OFFSET for no practical gain;
#: past this, filter instead.
MAX_PAGE = 1000


# --- collections ----------------------------------------------------------


@require_role(VIEWER)
def collection_list(request):
    collections = list(Collection.objects.annotate(ark_count=Count("arks")).order_by("name"))
    return render(
        request,
        "admin_ui/collection_list.html",
        {
            "collections": collections,
            "organisation": Organisation.load(),
            "collection_count": len(collections),
            # Summed from the per-collection counts already fetched rather than
            # a second COUNT(*) over the whole ARK table.
            "ark_total": sum(c.ark_count for c in collections),
            "running_jobs": BulkBindJob.objects.filter(
                status__in=(BulkBindJob.Status.PENDING, BulkBindJob.Status.RUNNING)
            ).count(),
        },
    )


@require_role(ADMIN)
def collection_create(request):
    errors: dict[str, str] = {}
    values = {"term": "medium"}
    if request.method == "POST":
        values = {
            key: request.POST.get(key, "").strip()
            for key in ("name", "prefix", "naan", "naa", "template", "term")
        }
        # The model allows a blank prefix so legacy minters import unchanged;
        # the form insists on one, as the legacy form did.
        if not values["prefix"]:
            errors["prefix"] = "A prefix or shoulder is required."
        elif Collection.objects.filter(naan=values["naan"], prefix=values["prefix"]).exists():
            errors["prefix"] = "The entered prefix has been used, please enter another prefix."
        if values["term"] == Collection.Term.LONG and not values["naa"]:
            errors["naa"] = "A long-term collection needs a Name Assigning Authority."

        if not errors:
            collection = Collection(**values)
            try:
                collection.full_clean()
                collection.save()
                messages.success(request, f"Created collection {collection.name}.")
                return redirect("admin_ui:collection_detail", pk=collection.pk)
            except ValidationError as exc:
                errors = {k: " ".join(v) for k, v in exc.message_dict.items()}

    return render(
        request,
        "admin_ui/collection_form.html",
        {
            "errors": errors,
            "error": "; ".join(f"{k}: {v}" for k, v in errors.items()) or None,
            "values": values,
            "terms": Collection.Term.choices,
            "templates": template_choices(),
        },
    )


@require_role(VIEWER)
def collection_detail(request, pk):
    collection = get_object_or_404(Collection, pk=pk)

    if request.method == "POST":
        if not can_administer(request.user):
            raise PermissionDenied("Editing a collection needs the Admin role.")
        collection.naa = request.POST.get("naa", "").strip()
        collection.name = request.POST.get("name", collection.name).strip()
        try:
            collection.full_clean()
            collection.save()
            messages.success(request, "Saved.")
        except ValidationError as exc:
            messages.error(
                request, "; ".join(f"{k}: {' '.join(v)}" for k, v in exc.message_dict.items())
            )
        return redirect("admin_ui:collection_detail", pk=pk)

    stats = collection_stats(collection)
    try:
        spec = collection.spec
        capacity = "unlimited" if spec.unlimited else f"{spec.total:,}"
    except TemplateError:
        spec, capacity = None, "unknown"

    return render(
        request,
        "admin_ui/collection_detail.html",
        {
            "collection": collection,
            "spec": spec,
            "capacity": capacity,
            **stats,
            "jobs": collection.bulk_bind_jobs.select_related("created_by")[:5],
        },
    )


# --- searching ------------------------------------------------------------


def as_int(value) -> int | None:
    """
    Parse a request parameter as an integer, or None.

    `str.isdigit()` is not enough: it is True for superscripts such as "²",
    which int() then refuses, so the caller would 500 on a crafted query string.
    """
    text = (value or "").strip()
    if not text.isascii() or not text.isdigit():
        return None
    try:
        return int(text)
    except ValueError:  # pragma: no cover - unreachable after the guard
        return None


def _search_from_request(request):
    collection = None
    collection_pk = as_int(request.GET.get("collection"))
    if collection_pk is not None:
        collection = Collection.objects.filter(pk=collection_pk).first()

    bound = None
    if request.GET.get("bound") == "yes":
        bound = True
    elif request.GET.get("bound") == "no":
        bound = False

    min_redirects = as_int(request.GET.get("min_redirects"))

    return collection, search_arks(
        collection=collection,
        text=request.GET.get("q", "").strip(),
        element=request.GET.get("element", "").strip(),
        value=request.GET.get("value", "").strip(),
        bound=bound,
        min_redirects=min_redirects,
        minted_after=_as_datetime(request.GET.get("minted_after")),
        minted_before=_as_datetime(request.GET.get("minted_before")),
    )


def _as_datetime(value):
    """Parse a YYYY-MM-DD filter value, ignoring anything unparseable."""
    parsed = parse_date(value) if value else None
    if parsed is None:
        return None
    return timezone.make_aware(datetime.combine(parsed, time.min))


#: Session key holding the Browse ARKs query string as the user last left it.
ARK_LIST_SESSION_KEY = "ark_list_query"


def _remember_list(request) -> None:
    """
    Keep this view of the ARK list, so an ARK opened from it can lead back.

    One value per parameter: the pager appends ``page`` to an address that may
    already carry one, and the last is the one that counts.
    """
    params = request.GET.copy()
    for key in list(params.keys()):
        params.setlist(key, [params[key]])
    request.session[ARK_LIST_SESSION_KEY] = params.urlencode()


def _back_to_list(request, ark) -> dict:
    """
    Where an ARK's page leads back to: the list as it was left, if it could
    have held this ARK; otherwise the ARKs of this ARK's own collection.
    """
    base = reverse("admin_ui:ark_list")
    left = request.session.get(ARK_LIST_SESSION_KEY)
    if left is not None:
        filtered_to = as_int(QueryDict(left).get("collection"))
        if filtered_to in (None, ark.collection_id):
            return {"url": f"{base}?{left}" if left else base, "label": "Back to ARKs"}
    return {
        "url": f"{base}?{urlencode({'collection': ark.collection_id})}",
        "label": f"Back to ARKs in {ark.collection.name}",
    }


#: Browse table headers: label, sort key, CSS class. The public URL is the base
#: URL plus the ARK, so it orders exactly as the ARK column does.
ARK_TABLE_HEADERS = (
    ("ARK", "ark", ""),
    ("Public URL", "ark", ""),
    ("Elements", "elements", "stretch"),
    ("Redirects", "redirects", "num"),
    ("Minted", "minted", ""),
)


def _sort_param(key: str, descending: bool) -> str:
    return f"-{key}" if descending else key


def _sort_headers(request, current: str, descending: bool) -> list[dict]:
    """
    The browse table's headers, each with the query string its link leads to.

    Clicking the column already in use reverses it; clicking another starts
    from that column's natural direction. Either way the link drops ``page``,
    since page 7 of one ordering means nothing in another.
    """
    headers = []
    for label, key, css in ARK_TABLE_HEADERS:
        active = key == current
        params = request.GET.copy()
        params.pop("page", None)
        params["sort"] = _sort_param(key, not descending if active else key in SORT_DESC_FIRST)
        headers.append(
            {
                "label": label,
                "css": css,
                "query": params.urlencode(),
                "aria": ("descending" if descending else "ascending") if active else "",
            }
        )
    return headers


@require_role(VIEWER)
def ark_list(request):
    collection, queryset = _search_from_request(request)
    sort_key, descending = parse_sort(request.GET.get("sort"))
    is_htmx = bool(request.headers.get("HX-Request"))
    _remember_list(request)

    # Paginator would run COUNT(*) over the filtered set on every page view —
    # a full index scan on a large table, and with a free-text filter it runs
    # the whole LIKE plan a second time just to render a number.
    # Counted before sorting: the redirect and element sorts annotate a
    # subquery, and the capped count would evaluate it for every row it looks at.
    total, capped = counted(queryset)
    queryset = sort_arks(queryset, sort_key, descending)
    number = max(1, min(as_int(request.GET.get("page")) or 1, MAX_PAGE))
    offset = (number - 1) * PAGE_SIZE
    arks = list(queryset[offset : offset + PAGE_SIZE + 1])
    has_next = len(arks) > PAGE_SIZE
    arks = arks[:PAGE_SIZE]
    bindings: dict[int, list] = {}
    for binding in Binding.objects.filter(ark__in=arks).order_by("qualifier", "name"):
        bindings.setdefault(binding.ark_id, []).append(binding)
    counters = dict(
        Resolution.objects.filter(ark__in=arks).values_list("ark_id").annotate(total=Sum("count"))
    )
    for ark in arks:
        ark.loaded_bindings = bindings.get(ark.id, [])
        ark.redirect_count = counters.get(ark.id, 0)

    context = {
        "total": total,
        "capped": capped,
        "page_number": number,
        "has_next": has_next,
        "has_previous": number > 1,
        "arks": arks,
        "collections": Collection.objects.all(),
        "selected_collection": collection,
        "query": request.GET,
        # Cached and collection-scoped: an unscoped DISTINCT over every binding
        # name is a full index scan on each page view.
        "element_names": element_names(collection.pk if collection else None),
        "headers": _sort_headers(request, sort_key, descending),
        # Empty for the default order, so an untouched table keeps a clean URL.
        "sort_param": (
            ""
            if (sort_key, descending) == (DEFAULT_SORT, False)
            else _sort_param(sort_key, descending)
        ),
        "is_htmx": is_htmx,
    }
    template = "admin_ui/_ark_table.html" if is_htmx else "admin_ui/ark_list.html"
    return render(request, template, context)


#: Elements a variant's row shows before folding the rest under "+N more" —
#: the same four the Browse ARKs table shows for an ARK.
VARIANT_ELEMENTS_SHOWN = 4

#: Longest term looked for among an ARK's variants.
VARIANT_SEARCH_MAX = 200


_DIGITS = re.compile(r"(\d+)")


def _variant_order(qualifiers) -> list[str]:
    """Qualifiers as a person would count them: /p2 before /p10."""

    def key(qualifier: str):
        return [
            (0, int(part)) if part.isdigit() else (1, part) for part in _DIGITS.split(qualifier)
        ]

    return sorted({q for q in qualifiers if q}, key=key)


def _variants(bindings, resolutions, text: str = "") -> tuple[list[dict], int]:
    """
    The qualified forms of an ARK, each with its own elements, and how many
    there are in all.

    The ARK's own elements (no qualifier) are not among them; the page lists
    those first, apart from these. ``text`` keeps only the variants whose
    qualifier, or any element name or value, contains it. A variant that
    matches keeps all of its elements: the point is to find the page, then
    read it.
    """
    grouped: dict[str, list] = {}
    for binding in bindings:
        if binding.qualifier:
            grouped.setdefault(binding.qualifier, []).append(binding)
    redirects = {resolution.qualifier: resolution.count for resolution in resolutions}
    needle = text.casefold()

    variants = []

    # Numbered before filtering, so a row's anchor is the same whether or not
    # a search is hiding its neighbours.
    def matches(binding) -> bool:
        return needle in binding.name.casefold() or needle in binding.value.casefold()

    for number, qualifier in enumerate(_variant_order(grouped), start=1):
        found = grouped[qualifier]
        if needle and not (needle in qualifier.casefold() or any(map(matches, found))):
            continue
        more = found[VARIANT_ELEMENTS_SHOWN:]
        variants.append(
            {
                "number": number,
                "qualifier": qualifier,
                "bindings": found,
                "shown": found[:VARIANT_ELEMENTS_SHOWN],
                "more": more,
                # A search that matched only a folded element would otherwise
                # show a row with no visible reason for being there.
                "more_open": bool(needle)
                and not any(map(matches, found[:VARIANT_ELEMENTS_SHOWN]))
                and any(map(matches, more)),
                "redirects": redirects.get(qualifier, 0),
            }
        )
    return variants, len(grouped)


#: Variants table headers: label, sort key, CSS class. A variant's public URL is
#: the ARK's plus the qualifier, so it orders exactly as the Variant column does.
VARIANT_TABLE_HEADERS = (
    ("Variant", "variant", ""),
    ("Public URL", "variant", ""),
    ("Elements", "elements", "stretch"),
    ("Redirects", "redirects", "num"),
)
VARIANT_DEFAULT_SORT = "variant"
#: Columns whose first click should show the largest first.
VARIANT_DESC_FIRST = frozenset({"elements", "redirects"})


def _parse_variant_sort(raw: str | None) -> tuple[str, bool]:
    """``(key, descending)`` from a ``sort`` parameter; counting order if unknown."""
    text = (raw or "").strip()
    descending = text.startswith("-")
    key = text[1:] if descending else text
    if key not in {key for _, key, _ in VARIANT_TABLE_HEADERS}:
        return VARIANT_DEFAULT_SORT, False
    return key, descending


def _sort_variants(variants: list[dict], key: str, descending: bool) -> list[dict]:
    """
    Order the variants table. They arrive in counting order, and Python's sort
    is stable in both directions, so ties stay in counting order either way.
    """
    if key == "elements":
        return sorted(variants, key=lambda v: len(v["bindings"]), reverse=descending)
    if key == "redirects":
        return sorted(variants, key=lambda v: v["redirects"], reverse=descending)
    return variants[::-1] if descending else variants


def _variant_query(text: str, sort: str) -> str:
    """Query string for the variants table; the default order is left unsaid."""
    params = {}
    if text:
        params["q"] = text
    if sort:
        params["sort"] = sort
    return urlencode(params)


def _variant_headers(text: str, current: str, descending: bool) -> list[dict]:
    """The variants table's headers, as ``_sort_headers`` builds the browse table's."""
    headers = []
    for label, key, css in VARIANT_TABLE_HEADERS:
        active = key == current
        to = _sort_param(key, not descending if active else key in VARIANT_DESC_FIRST)
        headers.append(
            {
                "label": label,
                "css": css,
                "query": _variant_query(text, to),
                "aria": ("descending" if descending else "ascending") if active else "",
            }
        )
    return headers


@require_role(VIEWER)
def ark_detail(request, pk):
    ark = get_object_or_404(Ark.objects.select_related("collection", "minted_by"), pk=pk)

    if request.method == "POST":
        if not can_edit(request.user):
            raise PermissionDenied("Binding needs the Editor role.")
        action = request.POST.get("action")
        qualifier = request.POST.get("qualifier", "").strip()

        if action == "bind":
            try:
                binding, _ = bind_element(
                    ark,
                    request.POST.get("name", ""),
                    request.POST.get("value", "").strip(),
                    qualifier,
                )
                messages.success(request, f"Bound {binding.name}.")
            except ValidationError:
                messages.error(request, "An element name is required.")
        elif action == "unbind":
            removed = unbind_elements(ark, name=request.POST.get("name", ""), qualifier=qualifier)
            messages.success(request, f"Removed {removed} element(s).")

        url = reverse("admin_ui:ark_detail", args=[pk])
        if qualifier:
            # Back to the row that was just edited, rather than to the top of
            # a table that may run to hundreds of them — and to the same view
            # of it: the forms post to the address they were drawn at, so the
            # search and sort in force are still in the query string.
            sort_key, descending = _parse_variant_sort(request.GET.get("sort"))
            query = _variant_query(
                request.GET.get("q", "").strip()[:VARIANT_SEARCH_MAX],
                ""
                if (sort_key, descending) == (VARIANT_DEFAULT_SORT, False)
                else _sort_param(sort_key, descending),
            )
            if query:
                url = f"{url}?{query}"
            order = _variant_order(ark.bindings.values_list("qualifier", flat=True).distinct())
            if qualifier in order:
                url = f"{url}#variant-{order.index(qualifier) + 1}"
        return redirect(url)

    bindings = list(ark.bindings.order_by("qualifier", "name"))
    resolutions = list(ark.resolutions.order_by("qualifier"))
    variant_query = request.GET.get("q", "").strip()[:VARIANT_SEARCH_MAX]
    variants, variant_total = _variants(bindings, resolutions, variant_query)
    sort_key, descending = _parse_variant_sort(request.GET.get("sort"))
    # Empty for the default order, so an untouched table keeps a clean address.
    variant_sort = (
        ""
        if (sort_key, descending) == (VARIANT_DEFAULT_SORT, False)
        else _sort_param(sort_key, descending)
    )
    return render(
        request,
        "admin_ui/ark_detail.html",
        {
            "ark": ark,
            "bindings": bindings,
            "back": _back_to_list(request, ark),
            "own_bindings": [binding for binding in bindings if not binding.qualifier],
            "variants": _sort_variants(variants, sort_key, descending),
            "variant_total": variant_total,
            "variant_query": variant_query,
            "variant_sort": variant_sort,
            "variant_headers": _variant_headers(variant_query, sort_key, descending),
            "variant_clear_query": _variant_query("", variant_sort),
            "resolutions": resolutions,
            "suggested": TEMPLATE_COLUMNS,
        },
    )


@require_POST
@require_role(ADMIN)
def ark_purge(request, pk):
    ark = get_object_or_404(Ark, pk=pk)
    removed = unbind_elements(ark)
    messages.success(request, f"Purged {removed} element(s) from {ark.name}.")
    return redirect("admin_ui:ark_detail", pk=pk)


# --- minting --------------------------------------------------------------


#: How long the "download the fill-in template" link keeps working after a mint.
LAST_MINTED_SECONDS = 60 * 60


def _last_minted_key(request) -> str:
    return f"last-minted:{request.session.session_key}"


def _remember_minted(request, minted) -> None:
    """
    Keep the ids just minted for the template download.

    In the cache, not the session: up to MINT_MAX_PER_REQUEST ids in the session
    were re-serialised and rewritten on every later request by the same person,
    because sessions are saved on every request.
    """
    if not request.session.session_key:
        request.session.save()
    cache.set(_last_minted_key(request), [a.pk for a in minted], LAST_MINTED_SECONDS)


def _last_minted(request) -> list[int]:
    if not request.session.session_key:
        return []
    return cache.get(_last_minted_key(request)) or []


@require_role(EDITOR)
def mint_view(request, pk):
    collection = get_object_or_404(Collection, pk=pk)
    minted = []

    if request.method == "POST":
        try:
            count = int(request.POST.get("count", "1"))
        except ValueError:
            count = 0
        if count < 1:
            messages.error(request, "Enter how many ARKs to mint.")
        else:
            try:
                minted = mint(collection, count=count, user=request.user)
                messages.success(request, f"Minted {len(minted)} ARK(s).")
                _remember_minted(request, minted)
            except (MintError, TemplateError, ValueError) as exc:
                messages.error(request, str(exc))

    return render(
        request,
        "admin_ui/mint.html",
        {
            "collection": collection,
            "minted": minted,
            "columns": TEMPLATE_COLUMNS,
            "mint_limit": settings.MINT_MAX_PER_REQUEST,
        },
    )


@require_role(EDITOR)
def mint_template(request, pk):
    """Download the fill-in CSV for the ARKs just minted."""
    collection = get_object_or_404(Collection, pk=pk)
    ark_ids = _last_minted(request)
    arks = Ark.objects.filter(pk__in=ark_ids, collection=collection).order_by("sequence")
    if not arks:
        raise Http404("Nothing was minted in this session.")

    stamp = timezone.now().strftime("%Y%m%d-%H%M")
    return _csv_response(
        template_csv(arks), f"{slugify(collection.prefix) or 'ark'}-bind-template-{stamp}.csv"
    )


# --- export ---------------------------------------------------------------


@require_role(VIEWER)
def export(request):
    collection, queryset = _search_from_request(request)
    stamp = timezone.now().strftime("%Y%m%d-%H%M")
    return _csv_response(export_rows(queryset, collection), f"arks-{stamp}.csv")


class _Echo:
    def write(self, value):
        return value


def _csv_response(rows, filename: str) -> StreamingHttpResponse:
    writer = csv.writer(_Echo())
    response = StreamingHttpResponse(
        (writer.writerow(row) for row in rows), content_type="text/csv"
    )
    # Filenames are built from user-editable text (a collection prefix), so keep
    # quotes and newlines out of the header.
    safe = re.sub(r"[^A-Za-z0-9._-]", "-", filename) or "export.csv"
    response["Content-Disposition"] = f'attachment; filename="{safe}"'
    return response


# --- bulk bind ------------------------------------------------------------


def _upload_problem(upload) -> str | None:
    """Why this upload cannot be accepted, or None. Checked before any work."""
    if not upload:
        return "Choose a CSV file to upload."
    limit = getattr(settings, "BULK_BIND_MAX_BYTES", 50 * 1024 * 1024)
    if upload.size > limit:
        return (
            f"That file is {upload.size / 1e6:.1f} MB; the limit is {limit / 1e6:.0f} MB. "
            "Split it into smaller uploads."
        )
    if not (upload.name or "").lower().endswith(".csv"):
        return "Only .csv files can be uploaded."
    return None


@require_role(EDITOR)
def bulk_bind(request, pk):
    collection = get_object_or_404(Collection, pk=pk)

    if request.method == "POST":
        upload = request.FILES.get("file")
        problem = _upload_problem(upload)
        if problem:
            messages.error(request, problem)
        else:
            job = BulkBindJob.objects.create(
                collection=collection,
                upload=upload,
                mint_missing=bool(request.POST.get("mint_missing")),
                purge_first=bool(request.POST.get("purge_first")),
                created_by=request.user,
            )
            try:
                run_bulk_bind.delay(job.pk)
            except Exception:
                # Broker (Redis or Valkey) unreachable: say so and mark the job, rather than
                # leaving it pending forever behind a 500.
                logger.exception("could not queue bulk bind job %s", job.pk)
                job.mark_failed(
                    "Could not be queued — the job runner is unreachable. "
                    "Ask an administrator to check the worker, then upload again."
                )
                messages.error(request, "The job runner is unavailable; nothing was applied.")
            return redirect("admin_ui:job_detail", pk=job.pk)

    return render(
        request,
        "admin_ui/bulk_bind.html",
        {
            "collection": collection,
            "jobs": collection.bulk_bind_jobs.select_related("created_by")[:10],
        },
    )


#: Filters over a job's per-row results: query value, label. "all" is every row;
#: the rest are the statuses bulk bind writes.
RESULT_FILTERS = (
    ("all", "All"),
    (STATUS_ERROR, "Errors"),
    (STATUS_MINTED, "Minted"),
    (STATUS_OK, "OK"),
)


#: Longest search term looked for in a job's results. It is compared against
#: every row of the file, so a pasted novel should not be.
RESULT_SEARCH_MAX = 200


def _job_results_page(job, status: str, number: int, text: str = "") -> dict:
    """
    One page of a job's per-row results, and how many rows each filter holds.

    A single pass over the results file does both. An upload may run to
    BULK_BIND_MAX_ROWS rows, so only the page being shown is kept; the rest is
    counted and let go. ``text`` narrows everything, counts included, to rows
    whose ARK or message contains it — the counts then say where the matches
    are, so a search made under one filter shows when to look under another.
    """
    counts = dict.fromkeys((value for value, _ in RESULT_FILTERS), 0)
    first = (number - 1) * PAGE_SIZE
    needle = text.casefold()
    rows = []
    matched = 0
    for row in job.iter_results():
        if needle and needle not in row[1].casefold() and needle not in row[3].casefold():
            continue
        counts["all"] += 1
        if row[2] in counts:
            counts[row[2]] += 1
        if status == "all" or row[2] == status:
            if first <= matched < first + PAGE_SIZE:
                rows.append(row)
            matched += 1
    return {
        "rows": rows,
        "counts": counts,
        "page_number": number,
        "has_previous": number > 1,
        "has_next": matched > first + PAGE_SIZE,
    }


@require_role(EDITOR)
def job_detail(request, pk):
    job = get_object_or_404(BulkBindJob.objects.select_related("collection"), pk=pk)
    context = {"job": job}

    if job.status == BulkBindJob.Status.FINISHED and job.results:
        status = request.GET.get("status")
        if status not in dict(RESULT_FILTERS):
            # Rows that need fixing are why anyone opens a job that failed;
            # they should not have to be found among thousands that were fine.
            status = STATUS_ERROR if job.failed else "all"
        number = max(1, min(as_int(request.GET.get("page")) or 1, MAX_PAGE))
        text = request.GET.get("q", "").strip()[:RESULT_SEARCH_MAX]
        results = _job_results_page(job, status, number, text)

        def link(to_status: str, to_page: int = 1, keep_search: bool = True) -> str:
            """Query string for another view of this table; page 1 is left unsaid."""
            params = {"status": to_status}
            if keep_search and text:
                params["q"] = text
            if to_page > 1:
                params["page"] = to_page
            return urlencode(params)

        context.update(
            results=results,
            result_columns=RESULT_COLUMNS,
            result_status=status,
            result_query=text,
            result_filters=[
                {
                    "label": label,
                    "value": value,
                    "count": results["counts"][value],
                    "active": value == status,
                    "query": link(value),
                }
                for value, label in RESULT_FILTERS
            ],
            result_links={
                "previous": link(status, number - 1),
                "next": link(status, number + 1),
                "clear": link(status, keep_search=False),
            },
        )

    template = (
        "admin_ui/_job_status.html" if request.headers.get("HX-Request") else "admin_ui/job.html"
    )
    return render(request, template, context)


@require_role(EDITOR)
def job_results(request, pk):
    job = get_object_or_404(BulkBindJob, pk=pk)
    if not job.results:
        raise Http404("This job has no results file.")
    return HttpResponse(
        job.results.read(),
        content_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="job-{job.pk}-results.csv"'},
    )


# --- users ----------------------------------------------------------------


@require_role(ADMIN)
def user_list(request):
    ensure_groups()

    if request.method == "POST":
        target_pk = as_int(request.POST.get("user"))
        target = User.objects.filter(pk=target_pk).first() if target_pk else None
        role = request.POST.get("role")
        if target is None:
            messages.error(request, "No such user.")
            return redirect("admin_ui:user_list")
        if role != ADMIN and role_of(target) == ADMIN and is_last_administrator(target):
            messages.error(
                request,
                f"{target.username} is the only Admin. Give someone else the Admin role first, "
                "or nobody will be able to manage this service.",
            )
        elif role in ROLES:
            set_role(target, role)
            messages.success(request, f"{target.username} is now {role}.")
        elif role == "none":
            clear_role(target)
            messages.success(request, f"{target.username} has no role.")
        return redirect("admin_ui:user_list")

    people = [{"user": user, "role": role_of(user)} for user in User.objects.order_by("username")]
    return render(request, "admin_ui/user_list.html", {"people": people, "roles": ROLES})
