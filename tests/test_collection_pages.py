"""
ARKs are browsed one collection at a time, under one shared collection header.

The cross-collection ARKs list confused people, so the sidebar no longer offers
it and the list requires a collection; the collection page, its ARK list, Mint
and Bulk bind are four tabs of one header. Export stays beside the thing it
exports. An activity strip on the list says when a bulk bind is changing the
rows underneath you.
"""

import pytest
from django.core.files.base import ContentFile
from django.urls import reverse

from admin_ui.roles import ADMIN, EDITOR, VIEWER, ensure_groups, set_role
from core.models import Ark, Binding, Collection
from jobs import progress
from jobs.models import BulkBindJob
from jobs.tasks import run_bulk_bind

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _media_in_a_temporary_directory(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path


@pytest.fixture
def collection():
    return Collection.objects.create(name="UTSC", prefix="utsc", naan="61220", template=".zd")


@pytest.fixture
def other_collection():
    return Collection.objects.create(name="Maps", prefix="maps", naan="61220", template=".zd")


@pytest.fixture
def ark(collection):
    ark = Ark.objects.create(collection=collection, identifier="utsc0", sequence=0)
    Binding.objects.create(ark=ark, name="URL", value="https://example.org/0")
    return ark


@pytest.fixture
def make_user(django_user_model):
    def _make(username, role):
        ensure_groups()
        user = django_user_model.objects.create_user(username, password="pw")
        set_role(user, role)
        return user

    return _make


@pytest.fixture
def viewer(client, make_user):
    client.force_login(make_user("vw", VIEWER))
    return client


@pytest.fixture
def editor(client, make_user):
    client.force_login(make_user("ed", EDITOR))
    return client


@pytest.fixture
def admin(client, make_user):
    client.force_login(make_user("adm", ADMIN))
    return client


LIST = reverse("admin_ui:ark_list")
EXPORT = reverse("admin_ui:export")
COLLECTIONS = reverse("admin_ui:collection_list")


def body_of(response):
    return response.content.decode()


# --- the ARKs menu is gone; browsing needs a collection ----------------------


def test_the_sidebar_no_longer_offers_every_ark(viewer, collection):
    body = body_of(viewer.get(COLLECTIONS))
    assert f'href="{LIST}"' not in body
    assert "Collections" in body


def test_browsing_without_a_collection_redirects_to_collections(viewer, collection):
    response = viewer.get(LIST)
    assert response.status_code == 302
    assert response["Location"] == COLLECTIONS


def test_the_redirect_explains_itself(viewer, collection):
    body = body_of(viewer.get(LIST, follow=True))
    assert "Choose a collection to browse its ARKs." in body


def test_an_unknown_collection_also_redirects(viewer, collection):
    assert viewer.get(LIST, {"collection": 99999}).status_code == 302
    assert viewer.get(LIST, {"collection": "abc"}).status_code == 302


def test_an_htmx_request_without_a_collection_is_sent_by_header(viewer, collection):
    response = viewer.get(LIST, HTTP_HX_REQUEST="true")
    assert response["HX-Redirect"] == COLLECTIONS


def test_exporting_without_a_collection_redirects(viewer, collection):
    response = viewer.get(EXPORT)
    assert response.status_code == 302
    assert response["Location"] == COLLECTIONS


def test_browsing_a_collection_still_works(viewer, collection, ark):
    response = viewer.get(LIST, {"collection": collection.pk})
    assert response.status_code == 200
    assert response.context["selected_collection"] == collection
    assert [a.pk for a in response.context["arks"]] == [ark.pk]


def test_the_filter_form_keeps_the_collection_without_offering_others(
    viewer, collection, other_collection
):
    body = body_of(viewer.get(LIST, {"collection": collection.pk}))
    assert f'name="collection" value="{collection.pk}"' in body
    assert '<select id="collection"' not in body
    assert "Maps" not in body.split("<form", 1)[1].split("</form>", 1)[0]


def test_ark_pages_light_the_collections_entry(viewer, collection, ark):
    response = viewer.get(LIST, {"collection": collection.pk})
    assert response.context["section"] == "collections"
    response = viewer.get(reverse("admin_ui:ark_detail", args=[ark.pk]))
    assert response.context["section"] == "collections"


# --- one header, four tabs ---------------------------------------------------


def current_tab(body):
    """The text of the tab marked current, or None."""
    import re

    match = re.search(r'<a class="tab"[^>]*aria-current="page"[^>]*>([^<]+)</a>', body)
    return match.group(1).strip() if match else None


def tabs(body):
    import re

    return re.findall(r'<a class="tab"[^>]*>([^<]+)</a>', body)


def test_the_collection_page_is_the_overview_tab(editor, collection):
    body = body_of(editor.get(reverse("admin_ui:collection_detail", args=[collection.pk])))
    assert current_tab(body) == "Overview"


def test_the_ark_list_is_the_browse_tab(editor, collection):
    body = body_of(editor.get(LIST, {"collection": collection.pk}))
    assert current_tab(body) == "Browse ARKs"


def test_the_mint_page_is_the_mint_tab(editor, collection):
    body = body_of(editor.get(reverse("admin_ui:mint", args=[collection.pk])))
    assert current_tab(body) == "Mint"


def test_the_bulk_bind_page_is_the_bulk_bind_tab(editor, collection):
    body = body_of(editor.get(reverse("admin_ui:bulk_bind", args=[collection.pk])))
    assert current_tab(body) == "Bulk bind"


def test_a_job_page_sits_under_the_bulk_bind_tab(editor, collection):
    job = BulkBindJob(collection=collection)
    job.upload.save("x.csv", ContentFile(b"Ark_ID\n"), save=False)
    job.save()
    body = body_of(editor.get(reverse("admin_ui:job_detail", args=[job.pk])))
    assert current_tab(body) == "Bulk bind"
    assert f"{LIST}?collection={collection.pk}" in body  # "Browse these ARKs"


def test_viewers_see_two_tabs_and_editors_four(viewer, collection, client, make_user):
    assert tabs(body_of(viewer.get(LIST, {"collection": collection.pk}))) == [
        "Overview",
        "Browse ARKs",
    ]
    client.force_login(make_user("ed2", EDITOR))
    assert tabs(body_of(client.get(LIST, {"collection": collection.pk}))) == [
        "Overview",
        "Browse ARKs",
        "Mint",
        "Bulk bind",
    ]


def test_the_header_names_the_collection_and_its_size(viewer, collection, ark):
    body = body_of(viewer.get(LIST, {"collection": collection.pk}))
    assert "<h1>UTSC</h1>" in body
    assert "61220/utsc" in body
    assert "1 ARK" in body


def test_the_old_action_bar_is_gone_from_the_collection_page(editor, collection):
    body = body_of(editor.get(reverse("admin_ui:collection_detail", args=[collection.pk])))
    assert ">Browse ARKs</a>" in body  # as a tab
    assert (
        'class="btn secondary" href="' + reverse("admin_ui:mint", args=[collection.pk]) not in body
    )


def test_the_htmx_table_swap_carries_no_header(viewer, collection, ark):
    body = body_of(viewer.get(LIST, {"collection": collection.pk}, HTTP_HX_REQUEST="true"))
    assert 'class="tab"' not in body
    assert "<table" in body


# --- export sits beside what it exports ----------------------------------------


def test_the_list_offers_to_export_the_filtered_rows_by_count(viewer, collection, ark):
    body = body_of(viewer.get(LIST, {"collection": collection.pk, "q": "utsc"}))
    assert "Export these 1 as CSV" in body
    assert f"{EXPORT}?" in body and "q=utsc" in body


def test_the_overview_offers_to_export_the_whole_collection(viewer, collection, ark):
    body = body_of(viewer.get(reverse("admin_ui:collection_detail", args=[collection.pk])))
    assert "Export all 1 as CSV" in body
    assert f"{EXPORT}?collection={collection.pk}" in body


# --- the activity strip ----------------------------------------------------------


def make_job(collection, body="Ark_ID,URL\n", **kwargs):
    job = BulkBindJob(collection=collection, **kwargs)
    job.upload.save("upload.csv", ContentFile(body.encode()), save=False)
    job.save()
    return job


def activity_url(collection):
    return reverse("admin_ui:collection_activity", args=[collection.pk])


def test_no_jobs_means_no_strip(viewer, collection):
    body = body_of(viewer.get(LIST, {"collection": collection.pk}))
    assert 'id="activity"' not in body


def test_a_finished_job_shows_a_quiet_line(viewer, collection, ark):
    job = make_job(collection, "Ark_ID,PID\n61220/utsc0,islandora:0\n")
    run_bulk_bind(job.pk)
    body = body_of(viewer.get(LIST, {"collection": collection.pk}))
    assert 'id="activity"' in body
    assert "Last bulk bind" in body and "finished" in body and "1 element added" in body
    assert reverse("admin_ui:job_detail", args=[job.pk]) in body
    assert "#recent-jobs" in body
    assert "hx-trigger" not in body.split('id="activity"', 1)[1].split("</div>", 1)[0]


def test_a_running_job_shows_live_progress_and_polls(viewer, collection):
    job = make_job(collection)
    job.mark_running("t")
    progress.Reporter("bulkbind", job.pk)("writing", 42000, 100000)
    body = body_of(viewer.get(LIST, {"collection": collection.pk}))
    strip = body.split('id="activity"', 1)[1].split("</div>", 1)[0]
    assert f"Bulk bind #{job.pk} running" in strip
    assert "Writing elements 42,000 of 100,000" in strip
    assert 'hx-trigger="every 3s"' in strip
    assert activity_url(collection) in strip


def test_a_job_that_only_updated_says_so(viewer, collection, ark):
    job = make_job(collection, "Ark_ID,URL\n61220/utsc0,https://example.org/new\n")
    run_bulk_bind(job.pk)
    strip = body_of(viewer.get(LIST, {"collection": collection.pk}))
    strip = strip.split('id="activity"', 1)[1].split("</div>", 1)[0]
    assert "1 element replaced" in strip and "added" not in strip


def test_a_minting_job_counts_arks_and_elements_separately(viewer, collection):
    job = make_job(
        collection, "Ark_ID,URL,PID\n,https://example.org/a,islandora:a\n", mint_missing=True
    )
    run_bulk_bind(job.pk)
    strip = body_of(viewer.get(LIST, {"collection": collection.pk}))
    strip = " ".join(strip.split('id="activity"', 1)[1].split("</div>", 1)[0].split())
    assert "1 ARK minted · 2 elements added" in strip


# --- the count labels say what they count -----------------------------------------

#: Old labels that read as ARKs while counting elements or rows.
OLD_COUNT_LABELS = (">Created<", ">Updated<", ">Minted<", ">Failed<")


def squashed(response):
    return " ".join(body_of(response).split())


def test_the_job_page_names_the_unit_of_each_count(editor, collection):
    job = make_job(collection, "Ark_ID,URL\n,https://example.org/a\n", mint_missing=True)
    run_bulk_bind(job.pk)
    body = squashed(editor.get(reverse("admin_ui:job_detail", args=[job.pk])))
    labels = ["ARKs minted", "Elements added", "Elements replaced", "Rows failed"]
    positions = [body.index(f'class="l">{label}<') for label in labels]
    assert positions == sorted(positions)
    assert not any(old in body for old in OLD_COUNT_LABELS)


@pytest.mark.parametrize("page", ["admin_ui:bulk_bind", "admin_ui:collection_detail"])
def test_job_tables_name_the_unit_of_each_count(editor, collection, page):
    job = make_job(collection, "Ark_ID,URL\n,https://example.org/a\n", mint_missing=True)
    run_bulk_bind(job.pk)
    body = squashed(editor.get(reverse(page, args=[collection.pk])))
    head = body.split("<thead>", 1)[1].split("</thead>", 1)[0]
    labels = ["ARKs minted", "Elements added", "Elements replaced", "Rows failed"]
    positions = [head.index(f">{label}<") for label in labels]
    assert positions == sorted(positions)
    assert not any(old in head for old in OLD_COUNT_LABELS)
    row = body.split("<tbody>", 1)[1].split("</tr>", 1)[0]
    cells = [cell.split("<", 1)[0] for cell in row.split('<td class="num">')[1:]]
    assert cells == ["1", "1", "0", "0"]


def test_a_job_that_changed_nothing_says_so(viewer, collection, ark):
    job = make_job(collection, "Ark_ID,URL\n61220/utsc0,https://example.org/0\n")
    run_bulk_bind(job.pk)
    strip = body_of(viewer.get(LIST, {"collection": collection.pk}))
    strip = strip.split('id="activity"', 1)[1].split("</div>", 1)[0]
    assert "no changes" in strip


def test_a_pending_job_waits_for_a_worker(viewer, collection):
    make_job(collection)
    body = body_of(viewer.get(LIST, {"collection": collection.pk}))
    assert "Waiting for a worker" in body


def test_a_failed_last_job_says_so(viewer, collection):
    job = make_job(collection, "nothing we recognise\n")
    run_bulk_bind(job.pk)
    body = body_of(viewer.get(LIST, {"collection": collection.pk}))
    assert "failed" in body.split('id="activity"', 1)[1].split("</div>", 1)[0]


def test_the_poll_endpoint_serves_the_strip_alone(viewer, collection):
    job = make_job(collection)
    job.mark_running("t")
    response = viewer.get(activity_url(collection))
    body = body_of(response)
    assert "<html" not in body
    assert f"Bulk bind #{job.pk}" in body


def test_the_poll_endpoint_needs_a_role(client, collection, django_user_model):
    client.force_login(django_user_model.objects.create_user("nobody", password="pw"))
    assert client.get(activity_url(collection)).status_code == 403


def test_the_poll_endpoint_404s_an_unknown_collection(viewer):
    assert viewer.get(reverse("admin_ui:collection_activity", args=[99999])).status_code == 404


def test_the_strip_belongs_to_its_own_collection(viewer, collection, other_collection):
    make_job(other_collection)
    body = body_of(viewer.get(LIST, {"collection": collection.pk}))
    assert 'id="activity"' not in body


def test_the_recent_jobs_table_has_its_anchor(editor, collection):
    make_job(collection)
    body = body_of(editor.get(reverse("admin_ui:collection_detail", args=[collection.pk])))
    assert 'id="recent-jobs"' in body
