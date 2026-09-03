"""
The staff interface.

Server-rendered with a little HTMX for the search table and job progress — no
build step, no API. Views talk to the ORM and the same services the management
commands use, so the two can never drift apart.
"""

from __future__ import annotations

import csv
import re

from django.contrib import messages
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db.models import Count, Sum
from django.http import Http404, HttpResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.text import slugify
from django.views.decorators.http import require_POST

from admin_ui.roles import (
    ADMIN,
    EDITOR,
    ROLES,
    VIEWER,
    can_administer,
    can_edit,
    ensure_groups,
    require_role,
    role_of,
    set_role,
)
from core.models import Ark, Binding, Collection, Organisation, Resolution
from core.search import export_rows, search_arks
from core.services import bind_element, collection_stats, unbind_elements
from jobs.bulkbind import TEMPLATE_COLUMNS, template_csv
from jobs.models import BulkBindJob
from jobs.tasks import run_bulk_bind
from minting.minter import MintError, mint
from minting.noid import TemplateError

PAGE_SIZE = 50


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


def _search_from_request(request):
    collection = None
    if request.GET.get("collection"):
        collection = Collection.objects.filter(pk=request.GET["collection"]).first()

    bound = None
    if request.GET.get("bound") == "yes":
        bound = True
    elif request.GET.get("bound") == "no":
        bound = False

    min_redirects = None
    if (request.GET.get("min_redirects") or "").isdigit():
        min_redirects = int(request.GET["min_redirects"])

    return collection, search_arks(
        collection=collection,
        text=request.GET.get("q", "").strip(),
        element=request.GET.get("element", "").strip(),
        value=request.GET.get("value", "").strip(),
        bound=bound,
        min_redirects=min_redirects,
    )


@require_role(VIEWER)
def ark_list(request):
    collection, queryset = _search_from_request(request)
    page = Paginator(queryset, PAGE_SIZE).get_page(request.GET.get("page"))

    arks = list(page.object_list)
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
        "page": page,
        "arks": arks,
        "collections": Collection.objects.all(),
        "selected_collection": collection,
        "query": request.GET,
        "element_names": Binding.objects.values_list("name", flat=True).distinct().order_by("name"),
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
            except (MintError, TemplateError) as exc:
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
    _, queryset = _search_from_request(request)
    stamp = timezone.now().strftime("%Y%m%d-%H%M")
    return _csv_response(export_rows(queryset), f"arks-{stamp}.csv")


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


@require_role(EDITOR)
def bulk_bind(request, pk):
    collection = get_object_or_404(Collection, pk=pk)

    if request.method == "POST":
        upload = request.FILES.get("file")
        if not upload:
            messages.error(request, "Choose a CSV file to upload.")
        else:
            job = BulkBindJob.objects.create(
                collection=collection,
                upload=upload,
                mint_missing=bool(request.POST.get("mint_missing")),
                purge_first=bool(request.POST.get("purge_first")),
                created_by=request.user,
            )
            run_bulk_bind.delay(job.pk)
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
        target = User.objects.filter(pk=request.POST.get("user")).first()
        role = request.POST.get("role")
        if target and role in ROLES:
            set_role(target, role)
            messages.success(request, f"{target.username} is now {role}.")
        elif target and role == "none":
            from django.contrib.auth.models import Group

            target.groups.remove(*Group.objects.filter(name__in=ROLES))
            messages.success(request, f"{target.username} has no role.")
        return redirect("admin_ui:user_list")

    people = [{"user": user, "role": role_of(user)} for user in User.objects.order_by("username")]
    return render(request, "admin_ui/user_list.html", {"people": people, "roles": ROLES})
