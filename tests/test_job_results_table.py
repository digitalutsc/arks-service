"""
The per-row results table on a bulk-bind job's page.

The download was the only way to see what happened to each row. The page now
lists the same rows, read from the same file, so the two cannot disagree. An
upload can run to a hundred thousand rows with a handful that need fixing, so
the table is paged and the rows in error are one click away — and shown first
when there are any.
"""

import pytest
from django.core.files.base import ContentFile
from django.urls import reverse

from admin_ui import views
from admin_ui.roles import EDITOR, ensure_groups, set_role
from core.models import Ark, Collection
from jobs.models import BulkBindJob
from jobs.tasks import run_bulk_bind

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _media_in_a_temporary_directory(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path


@pytest.fixture
def editor(django_user_model, client):
    ensure_groups()
    user = django_user_model.objects.create_user("ed", password="pw")
    set_role(user, EDITOR)
    client.force_login(user)
    return client


@pytest.fixture
def collection():
    return Collection.objects.create(name="UTSC", prefix="utsc", naan="61220", template=".zd")


def finished_job(collection, body, **kwargs):
    job = BulkBindJob(collection=collection, **kwargs)
    job.upload.save("upload.csv", ContentFile(body.encode()), save=False)
    job.save()
    run_bulk_bind(job.pk)
    job.refresh_from_db()
    return job


@pytest.fixture
def clean_job(collection):
    for number in range(3):
        Ark.objects.create(collection=collection, identifier=f"utsc{number}", sequence=number)
    body = "Ark_ID,URL\n" + "".join(
        f"61220/utsc{number},https://example.org/{number}\n" for number in range(3)
    )
    return finished_job(collection, body)


@pytest.fixture
def job_with_a_bad_row(collection):
    Ark.objects.create(collection=collection, identifier="utsc0", sequence=0)
    return finished_job(
        collection,
        "Ark_ID,URL\n61220/utsc0,https://ok.example\n61220/nope,https://bad.example\n",
    )


def page(client, job, **params):
    return client.get(reverse("admin_ui:job_detail", args=[job.pk]), params)


def shown(response):
    rows = response.context["results"]["rows"]
    return [(number, ark_id, status) for number, ark_id, status, _ in rows]


# --- the table -------------------------------------------------------------


def test_a_finished_job_lists_every_row_under_the_csv_column_names(editor, clean_job):
    response = page(editor, clean_job)
    body = response.content.decode()

    assert shown(response) == [
        (2, "61220/utsc0", "bound"),
        (3, "61220/utsc1", "bound"),
        (4, "61220/utsc2", "bound"),
    ]
    for column in ("row", "ark_id", "status", "message"):
        assert f">{column}</th>" in body
    assert "<code>61220/utsc1</code>" in body
    # The download is still there for fixing rows in a spreadsheet.
    assert reverse("admin_ui:job_results", args=[clean_job.pk]) in body


def test_the_table_matches_the_download(editor, clean_job):
    downloaded = editor.get(reverse("admin_ui:job_results", args=[clean_job.pk])).content.decode()
    lines = downloaded.strip().splitlines()[1:]
    assert [line.split(",")[1] for line in lines] == [
        ark_id for _, ark_id, _ in shown(page(editor, clean_job))
    ]


def test_a_job_with_failures_opens_on_the_rows_in_error(editor, job_with_a_bad_row):
    response = page(editor, job_with_a_bad_row)
    assert response.context["result_status"] == "error"
    assert shown(response) == [(3, "61220/nope", "error")]
    message = response.context["results"]["rows"][0][3]
    assert message
    assert message in response.content.decode()


def test_every_row_is_one_click_away(editor, job_with_a_bad_row):
    response = page(editor, job_with_a_bad_row, status="all")
    assert shown(response) == [(2, "61220/utsc0", "ok"), (3, "61220/nope", "error")]


def test_each_filter_says_how_many_rows_it_holds(editor, job_with_a_bad_row):
    response = page(editor, job_with_a_bad_row)
    counts = {f["value"]: f["count"] for f in response.context["result_filters"]}
    assert counts == {"all": 2, "error": 1, "minted": 0, "bound": 0, "unchanged": 0, "ok": 1}
    assert "Errors (1)" in response.content.decode()
    assert [f["value"] for f in response.context["result_filters"] if f["active"]] == ["error"]


def test_minted_rows_are_their_own_filter(editor, collection):
    job = finished_job(collection, "Ark_ID,URL\n,https://example.org/new\n", mint_missing=True)
    response = page(editor, job, status="minted")
    assert [status for _, _, status in shown(response)] == ["minted"]
    assert response.context["results"]["counts"]["minted"] == 1


def test_a_filter_with_nothing_in_it_says_so(editor, clean_job):
    response = page(editor, clean_job, status="error")
    assert shown(response) == []
    assert "No rows with that status." in response.content.decode()


@pytest.mark.parametrize(
    "params",
    [{"status": "bogus"}, {"status": ""}, {"page": "²"}, {"page": "-1"}, {"page": "99999999"}],
)
def test_crafted_parameters_do_not_error(editor, clean_job, params):
    response = page(editor, clean_job, **params)
    assert response.status_code == 200
    assert response.context["result_status"] == "all"


def test_a_message_cannot_inject_markup(editor, collection):
    job = finished_job(collection, "Ark_ID,URL\n<script>alert(1)</script>,https://e.example\n")
    body = page(editor, job).content.decode()
    assert "<script>alert(1)</script>" not in body
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in body


# --- searching -------------------------------------------------------------


def test_search_finds_rows_by_ark(editor, clean_job):
    response = page(editor, clean_job, q="utsc1")
    assert shown(response) == [(3, "61220/utsc1", "bound")]
    assert response.context["result_query"] == "utsc1"


def test_search_ignores_case_and_surrounding_space(editor, clean_job):
    assert shown(page(editor, clean_job, q="  UTSC2 ")) == [(4, "61220/utsc2", "bound")]


def test_search_reaches_the_message(editor, job_with_a_bad_row):
    # "Mint it first" is in the error message, not the ARK.
    response = page(editor, job_with_a_bad_row, status="all", q="mint it first")
    assert shown(response) == [(3, "61220/nope", "error")]


def test_the_filter_counts_follow_the_search(editor, job_with_a_bad_row):
    response = page(editor, job_with_a_bad_row, status="all", q="utsc0")
    assert response.context["results"]["counts"] == {
        "all": 1,
        "error": 0,
        "minted": 0,
        "bound": 0,
        "unchanged": 0,
        "ok": 1,
    }


def test_search_and_filter_combine(editor, job_with_a_bad_row):
    # utsc0 was fine, so it is not among the rows in error.
    response = page(editor, job_with_a_bad_row, status="error", q="utsc0")
    assert shown(response) == []
    assert "No rows match" in response.content.decode()


def test_the_filters_and_the_pager_keep_the_search(editor, clean_job, monkeypatch):
    monkeypatch.setattr(views, "PAGE_SIZE", 1)
    response = page(editor, clean_job, status="all", q="61220/utsc")
    body = response.content.decode()
    assert 'href="?status=bound&amp;q=61220%2Futsc"' in body
    assert 'href="?status=all&amp;q=61220%2Futsc&amp;page=2"' in body
    second = page(editor, clean_job, status="all", q="61220/utsc", page="2")
    assert shown(second) == [(3, "61220/utsc1", "bound")]


def test_the_search_box_remembers_what_was_asked_and_keeps_the_filter(editor, job_with_a_bad_row):
    body = page(editor, job_with_a_bad_row, status="all", q="nope").content.decode()
    assert 'name="q" value="nope"' in body
    assert '<input type="hidden" name="status" value="all">' in body
    # A way back to everything, without the search but on the same filter.
    assert 'href="?status=all"' in body


def test_a_search_term_cannot_inject_markup(editor, clean_job):
    body = page(editor, clean_job, q='"><script>alert(1)</script>').content.decode()
    assert "<script>alert(1)</script>" not in body


def test_an_absurdly_long_search_is_cut_short(editor, clean_job):
    response = page(editor, clean_job, q="x" * 5000)
    assert response.status_code == 200
    assert len(response.context["result_query"]) == 200


# --- paging ----------------------------------------------------------------


def test_the_table_is_paged_and_the_pager_keeps_the_filter(editor, clean_job, monkeypatch):
    monkeypatch.setattr(views, "PAGE_SIZE", 2)

    first = page(editor, clean_job, status="bound")
    assert [number for number, _, _ in shown(first)] == [2, 3]
    assert first.context["results"]["has_next"] is True
    assert first.context["results"]["has_previous"] is False
    assert 'href="?status=bound&amp;page=2"' in first.content.decode()

    second = page(editor, clean_job, status="bound", page="2")
    assert [number for number, _, _ in shown(second)] == [4]
    assert second.context["results"]["has_next"] is False
    assert second.context["results"]["has_previous"] is True
    # Page 1 is left unsaid, so the way back is the plain filter address.
    assert second.context["result_links"]["previous"] == "status=bound"
    # Counts cover the whole file, not the page.
    assert second.context["results"]["counts"]["all"] == 3


def test_a_full_last_page_does_not_offer_a_next(editor, clean_job, monkeypatch):
    monkeypatch.setattr(views, "PAGE_SIZE", 3)
    assert page(editor, clean_job).context["results"]["has_next"] is False


# --- when there is nothing to show -----------------------------------------


def test_the_table_arrives_with_the_htmx_swap_that_ends_the_polling(editor, clean_job):
    response = editor.get(
        reverse("admin_ui:job_detail", args=[clean_job.pk]), HTTP_HX_REQUEST="true"
    )
    body = response.content.decode()
    assert "<table" in body
    assert "<html" not in body
    assert 'hx-trigger="every 2s"' not in body


def test_a_job_still_waiting_shows_no_table(editor, collection):
    job = BulkBindJob(collection=collection)
    job.upload.save("upload.csv", ContentFile(b"Ark_ID,URL\n"), save=False)
    job.save()
    response = page(editor, job)
    assert "results" not in response.context
    assert "<table" not in response.content.decode()


def test_a_file_that_could_not_be_read_shows_its_error_and_no_table(editor, collection):
    job = finished_job(collection, "no header that we recognise\n")
    response = page(editor, job)
    assert response.status_code == 200
    assert "results" not in response.context
    assert "<table" not in response.content.decode()


def test_a_results_file_gone_from_storage_does_not_break_the_page(editor, clean_job):
    clean_job.results.storage.delete(clean_job.results.name)
    response = page(editor, clean_job)
    assert response.status_code == 200
    assert shown(response) == []
