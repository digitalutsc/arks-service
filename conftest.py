import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def _clear_caches():
    """
    Element names and resolver targets are cached.

    Without clearing, one test's data would answer another test's lookup.
    """
    from django.core.cache import caches

    for each in caches.all(initialized_only=False):
        each.clear()
    yield
    for each in caches.all(initialized_only=False):
        each.clear()
