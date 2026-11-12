import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def _plain_static_storage(settings):
    """
    Serve static files without the collectstatic manifest.

    With DEBUG off, settings use WhiteNoise's manifest storage, which raises
    "Missing staticfiles manifest entry" on every {% static %} unless
    collectstatic has filled STATIC_ROOT. A developer's checkout usually has a
    leftover (gitignored) staticfiles/ that hides this; CI's fresh checkout
    does not, so every rendered page failed there. Tests do not exercise the
    manifest, so they use Django's plain storage.
    """
    settings.STORAGES = {
        **settings.STORAGES,
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }


@pytest.fixture(autouse=True)
def _clear_caches():
    """
    Element names and statistics are cached.

    Without clearing, one test's data would answer another test's lookup.
    """
    from django.core.cache import caches

    for each in caches.all(initialized_only=False):
        each.clear()
    yield
    for each in caches.all(initialized_only=False):
        each.clear()


@pytest.fixture(autouse=True)
def counter_redis(monkeypatch):
    """
    A private in-memory Redis for the redirect-hit buffer.

    Production buffers hits in Redis/Valkey (core/counters.py); without one the
    buffer writes straight through to the database, which is not what most
    tests mean to exercise. Each test gets an empty server of its own.
    """
    import fakeredis

    import core.counters as counters

    server = fakeredis.FakeRedis(server=fakeredis.FakeServer())
    monkeypatch.setattr(counters, "_client", lambda: server)
    return server
