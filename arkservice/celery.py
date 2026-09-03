import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "arkservice.settings")

app = Celery("arkservice")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
