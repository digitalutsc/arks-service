"""
Progress of a running bulk bind, read from the cache.

The whole upload is applied in one transaction, so a progress row in the
database would be invisible to the web process until commit. The worker writes
its phase and counts to a cache key instead, throttled, and the job page reads
that key while it polls. Nothing about the job model changes.
"""

import io

import pytest
from django.core.cache import cache
from django.core.files.base import ContentFile
from django.urls import reverse

from admin_ui.roles import EDITOR, ensure_groups, set_role
from core.models import Ark, Binding, Collection
from core.services import bulk_upsert_bindings
from jobs import progress
from jobs.bulkbind import apply_csv
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
def arks(collection):
    return [
        Ark.objects.create(collection=collection, identifier=f"utsc{n}", sequence=n)
        for n in range(3)
    ]


@pytest.fixture
def editor(django_user_model, client):
    ensure_groups()
    user = django_user_model.objects.create_user("ed", password="pw")
    set_role(user, EDITOR)
    client.force_login(user)
    return client


def recorder():
    calls = []
    return calls, lambda phase, done, total: calls.append((phase, done, total))


# --- the reporter ----------------------------------------------------------


def test_the_first_report_is_written_at_once():
    clock = iter([0.0, 0.0]).__next__
    report = progress.Reporter("bulkbind", 7, clock=clock)
    report("checking", 0, 100)
    assert progress.read("bulkbind", 7) == {"phase": "checking", "done": 0, "total": 100}


def test_reports_inside_the_interval_are_dropped():
    ticks = iter([0.0, 0.1, 0.2])
    report = progress.Reporter("bulkbind", 7, clock=lambda: next(ticks))
    report("checking", 0, 100)
    report("checking", 10, 100)
    assert progress.read("bulkbind", 7)["done"] == 0


def test_a_report_after_the_interval_is_written():
    ticks = iter([0.0, 0.1, 0.9])
    report = progress.Reporter("bulkbind", 7, clock=lambda: next(ticks))
    report("checking", 0, 100)
    report("checking", 10, 100)
    report("checking", 20, 100)
    assert progress.read("bulkbind", 7)["done"] == 20


def test_a_phase_change_is_always_written():
    ticks = iter([0.0, 0.1])
    report = progress.Reporter("bulkbind", 7, clock=lambda: next(ticks))
    report("checking", 0, 100)
    report("writing", 0, 300)
    assert progress.read("bulkbind", 7)["phase"] == "writing"


def test_the_end_of_a_phase_is_always_written():
    ticks = iter([0.0, 0.1])
    report = progress.Reporter("bulkbind", 7, clock=lambda: next(ticks))
    report("checking", 0, 100)
    report("checking", 100, 100)
    assert progress.read("bulkbind", 7)["done"] == 100


def test_finishing_clears_the_key():
    report = progress.Reporter("bulkbind", 7)
    report("checking", 0, 100)
    report.finish()
    assert progress.read("bulkbind", 7) is None


def test_a_broken_cache_does_not_break_the_work(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("cache down")

    monkeypatch.setattr(progress.cache, "set", boom)
    monkeypatch.setattr(progress.cache, "delete", boom)
    report = progress.Reporter("bulkbind", 7)
    report("checking", 0, 100)  # must not raise
    report.finish()


# --- what the work reports -------------------------------------------------


def test_the_upsert_reports_how_much_it_has_written(arks):
    calls, report = recorder()
    wanted = {(ark.pk, "", "URL"): f"https://example.org/{ark.pk}" for ark in arks}
    bulk_upsert_bindings(wanted, progress=report)
    assert calls == [("writing", 3, 3)]


def test_the_upsert_reports_per_chunk(arks, monkeypatch):
    import core.services as services

    monkeypatch.setattr(services, "BATCH_SIZE", 1)
    calls, report = recorder()
    wanted = {(ark.pk, "", "URL"): "x" for ark in arks}
    bulk_upsert_bindings(wanted, progress=report)
    assert [done for _, done, _ in calls] == [1, 2, 3]
    assert {total for _, _, total in calls} == {3}


def test_apply_csv_reports_its_phases_in_order(collection, arks):
    calls, report = recorder()
    body = "Ark_ID,URL,PID\n" + "".join(
        f"61220/utsc{n},https://example.org/{n},islandora:{n}\n" for n in range(3)
    )
    apply_csv(collection, io.StringIO(body), progress=report)

    phases = [phase for phase, _, _ in calls]
    assert phases[0] == "reading"
    assert "checking" in phases and "writing" in phases
    assert phases.index("checking") < phases.index("writing")
    assert ("checking", 3, 3) in calls
    assert calls[-1] == ("writing", 6, 6)


def test_done_never_goes_backwards_within_a_phase(collection, arks):
    calls, report = recorder()
    body = "Ark_ID,URL\n" + "".join(f"61220/utsc{n},https://example.org/{n}\n" for n in range(3))
    apply_csv(collection, io.StringIO(body), progress=report)
    for phase in {p for p, _, _ in calls}:
        dones = [done for p, done, _ in calls if p == phase]
        assert dones == sorted(dones)


def test_minting_blank_rows_is_its_own_phase(collection):
    calls, report = recorder()
    apply_csv(
        collection,
        io.StringIO("Ark_ID,URL\n,https://example.org/a\n,https://example.org/b\n"),
        mint_missing=True,
        progress=report,
    )
    assert ("minting", 2, 2) in calls


def test_a_file_that_fails_validation_never_reports_writing(collection, arks):
    calls, report = recorder()
    apply_csv(
        collection,
        io.StringIO("Ark_ID,URL\n61220/utsc0,https://ok.example\n61220/nope,https://x\n"),
        progress=report,
    )
    assert "writing" not in {phase for phase, _, _ in calls}
    assert Binding.objects.count() == 0


def test_apply_csv_works_without_a_callback(collection, arks):
    result = apply_csv(collection, io.StringIO("Ark_ID,URL\n61220/utsc0,https://example.org/0\n"))
    assert result.ok and result.created == 1


# --- the task ---------------------------------------------------------------


def make_job(collection, body, **kwargs):
    job = BulkBindJob(collection=collection, **kwargs)
    job.upload.save("upload.csv", ContentFile(body.encode()), save=False)
    job.save()
    return job


def test_the_task_clears_its_progress_when_it_finishes(collection, arks):
    job = make_job(collection, "Ark_ID,URL\n61220/utsc0,https://example.org/0\n")
    run_bulk_bind(job.pk)
    assert progress.read("bulkbind", job.pk) is None
    job.refresh_from_db()
    assert job.status == BulkBindJob.Status.FINISHED


def test_the_task_clears_its_progress_when_it_fails(collection):
    job = make_job(collection, "nothing we recognise\n")
    run_bulk_bind(job.pk)
    assert progress.read("bulkbind", job.pk) is None
    job.refresh_from_db()
    assert job.status == BulkBindJob.Status.FAILED


# --- the label the page shows ---------------------------------------------


def test_a_pending_job_waits_for_a_worker():
    assert progress.describe(None, pending=True) == {
        "label": "Waiting for a worker",
        "done": None,
        "total": None,
    }


def test_no_progress_yet_is_simply_working():
    assert progress.describe(None)["label"] == "Working…"
    assert progress.describe(None)["total"] is None


def test_a_phase_with_a_total_is_counted_with_separators():
    shown = progress.describe({"phase": "writing", "done": 180000, "total": 412000})
    assert shown == {
        "label": "Writing elements 180,000 of 412,000",
        "done": 180000,
        "total": 412000,
    }


def test_a_phase_without_a_total_is_indeterminate():
    shown = progress.describe({"phase": "reading", "done": 0, "total": None})
    assert shown["label"] == "Reading the file"
    assert shown["total"] is None


def test_an_unknown_phase_is_not_an_error():
    assert progress.describe({"phase": "mystery", "done": 1, "total": 2})["label"].startswith(
        "Working"
    )


# --- the job page -----------------------------------------------------------


def body_of(client, job):
    return client.get(reverse("admin_ui:job_detail", args=[job.pk])).content.decode()


def test_a_pending_job_shows_an_indeterminate_bar(editor, collection):
    job = make_job(collection, "Ark_ID,URL\n")
    body = body_of(editor, job)
    assert "<progress" in body
    assert 'value="' not in body.split("<progress", 1)[1].split(">", 1)[0]
    assert "Waiting for a worker" in body
    assert 'hx-trigger="every 2s"' in body


def test_a_running_job_shows_its_progress(editor, collection):
    job = make_job(collection, "Ark_ID,URL\n")
    job.mark_running("task-1")
    progress.Reporter("bulkbind", job.pk)("checking", 42000, 100000)
    body = body_of(editor, job)
    assert 'value="42000"' in body and 'max="100000"' in body
    assert "Checking rows 42,000 of 100,000" in body


def test_a_running_job_with_no_report_yet_is_working(editor, collection):
    job = make_job(collection, "Ark_ID,URL\n")
    job.mark_running("task-1")
    body = body_of(editor, job)
    assert "<progress" in body
    assert "Working…" in body


def test_a_finished_job_shows_no_bar(editor, collection, arks):
    job = make_job(collection, "Ark_ID,URL\n61220/utsc0,https://example.org/0\n")
    run_bulk_bind(job.pk)
    assert "<progress" not in body_of(editor, job)


def test_the_bar_says_nothing_is_written_until_the_file_passes(editor, collection):
    job = make_job(collection, "Ark_ID,URL\n")
    assert "Nothing is written until the whole file passes" in body_of(editor, job)


def test_the_cache_key_is_namespaced_by_kind():
    assert progress.key("bulkbind", 3) == "job-progress:bulkbind:3"
    cache.set(progress.key("bulkbind", 3), {"phase": "x"})
    assert progress.read("other", 3) is None
