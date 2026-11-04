"""
Scheduled housekeeping runs on its own queue.

The Docker "scheduler" service and deploy/arkservice-beat.service consume only
the periodic queue; the bulk-bind worker consumes only the default one. A
scheduled task left unrouted would sit on the default queue behind long bulk
binds, which is exactly what the split exists to prevent.
"""

from django.conf import settings

from arkservice.celery import app


def test_every_scheduled_task_is_routed_to_the_periodic_queue():
    for name, entry in settings.CELERY_BEAT_SCHEDULE.items():
        route = settings.CELERY_TASK_ROUTES.get(entry["task"])
        assert route == {"queue": settings.PERIODIC_QUEUE}, f"{name} is not on the periodic queue"


def test_every_scheduled_task_exists():
    app.loader.import_default_modules()
    for entry in settings.CELERY_BEAT_SCHEDULE.values():
        assert entry["task"] in app.tasks, entry["task"]


def test_results_are_not_stored_and_redelivery_outlasts_the_time_limit():
    assert settings.CELERY_TASK_IGNORE_RESULT is True
    assert settings.CELERY_WORKER_PREFETCH_MULTIPLIER == 1
    timeout = settings.CELERY_BROKER_TRANSPORT_OPTIONS["visibility_timeout"]
    assert timeout > settings.CELERY_TASK_TIME_LIMIT


def test_beat_keeps_its_state_somewhere_writable():
    # The systemd units make the working directory read-only; beat writing its
    # schedule file there meant the counter flush never ran.
    assert settings.CELERY_BEAT_SCHEDULE_FILENAME.startswith("/tmp/")
