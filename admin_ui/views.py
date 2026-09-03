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
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Count, Sum
from django.http import Http404, HttpResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_date
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
from core.search import counted, element_names, export_rows, search_arks
from core.services import bind_element, collection_stats, unbind_elements
from jobs.bulkbind import TEMPLATE_COLUMNS, template_csv
from jobs.models import BulkBindJob
from jobs.tasks import run_bulk_bind
from minting.minter import MintError, mint
from minting.noid import TemplateError

logger = logging.getLogger(__name__)

PAGE_SIZE = 50

#: Deep pages cost the database an ever larger OFFSET for no practical gain;
#: past this, filter instead.
MAX_PAGE = 1000


# --- collections ----------------------------------------------------------


@require_role(VIEWER)
def collection_list(request):
    collections = Collection.objects.annotate(ark_count=Count("arks")).order_by("name")
    return render(
        request,
        "admin_ui/collection_list.html",
        {"collections": collections, "organisation": Organisation.load()},
    )


@require_role(ADMIN)
def collection_create(request):
    error = None
    values = {"term": "medium"}
    if request.method == "POST":
        values = {
            key: request.POST.get(key, "").strip()
            for key in ("name", "prefix", "naan", "naa", "template", "term")
        }
        collection = Collection(**values)
        try:
            collection.full_clean()
            collection.save()
            messages.success(request, f"Created collection {collection.name}.")
            return redirect("admin_ui:collection_detail", pk=collection.pk)
        except ValidationError as exc:
            error = "; ".join(f"{k}: {' '.join(v)}" for k, v in exc.message_dict.items())

    return render(
        request,
        "admin_ui/collection_form.html",
        {"error": error, "values": values, "terms": Collection.Term.choices},
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
            "jobs": collection.bulk_bind_jobs.all()[:5],
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


@require_role(VIEWER)
def ark_list(request):
    collection, queryset = _search_from_request(request)

    # Paginator would run COUNT(*) over the filtered set on every page view —
    # a full index scan on a large table, and with a free-text filter it runs
    # the whole LIKE plan a second time just to render a number.
    total, capped = counted(queryset)
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
    }
    template = (
        "admin_ui/_ark_table.html"
        if request.headers.get("HX-Request")
        else "admin_ui/ark_list.html"
    )
    return render(request, template, context)


@require_role(VIEWER)
def ark_detail(request, pk):
    ark = get_object_or_404(Ark.objects.select_related("collection"), pk=pk)

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
        return redirect("admin_ui:ark_detail", pk=pk)

    return render(
        request,
        "admin_ui/ark_detail.html",
        {
            "ark": ark,
            "bindings": ark.bindings.order_by("qualifier", "name"),
            "resolutions": ark.resolutions.order_by("qualifier"),
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
                request.session["last_minted"] = [a.pk for a in minted]
            except (MintError, TemplateError, ValueError) as exc:
                messages.error(request, str(exc))

    return render(
        request,
        "admin_ui/mint.html",
        {"collection": collection, "minted": minted, "columns": TEMPLATE_COLUMNS},
    )


@require_role(EDITOR)
def mint_template(request, pk):
    """Download the fill-in CSV for the ARKs just minted."""
    collection = get_object_or_404(Collection, pk=pk)
    ark_ids = request.session.get("last_minted") or []
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
                # Redis unreachable: say so and mark the job, rather than
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
        {"collection": collection, "jobs": collection.bulk_bind_jobs.all()[:10]},
    )


@require_role(EDITOR)
def job_detail(request, pk):
    job = get_object_or_404(BulkBindJob.objects.select_related("collection"), pk=pk)
    template = (
        "admin_ui/_job_status.html" if request.headers.get("HX-Request") else "admin_ui/job.html"
    )
    return render(request, template, {"job": job})


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
