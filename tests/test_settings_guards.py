"""
Production boot guards.

The legacy service failed loudly when its config was missing. This one has
sensible defaults for development, which is a hazard in production: without a
guard, an incomplete .env means gunicorn starts happily against an empty SQLite
file and every one of the ~100k ARKs 404s, with a well-known SECRET_KEY.
"""

import pytest

from arkservice.checks import ConfigurationError, check_production_settings


def test_a_development_configuration_is_left_alone():
    check_production_settings(
        debug=True, secret_key="dev-insecure-key-change-me", database_url=None
    )


def test_production_requires_a_real_secret_key():
    with pytest.raises(ConfigurationError, match="(?i)secret_key"):
        check_production_settings(
            debug=False, secret_key="dev-insecure-key-change-me", database_url="postgres://x/y"
        )


def test_production_requires_a_secret_key_at_all():
    with pytest.raises(ConfigurationError, match="(?i)secret_key"):
        check_production_settings(debug=False, secret_key="", database_url="postgres://x/y")


def test_production_requires_a_database_url():
    with pytest.raises(ConfigurationError, match="(?i)database_url"):
        check_production_settings(debug=False, secret_key="a" * 60, database_url=None)


def test_production_rejects_a_sqlite_database():
    # An unset DATABASE_URL used to fall back to SQLite silently.
    with pytest.raises(ConfigurationError, match="(?i)sqlite"):
        check_production_settings(
            debug=False, secret_key="a" * 60, database_url="sqlite:///db.sqlite3"
        )


def test_a_complete_production_configuration_passes():
    check_production_settings(
        debug=False, secret_key="a" * 60, database_url="mysql://user:pw@localhost/ark"
    )


def test_the_error_names_what_to_fix():
    with pytest.raises(ConfigurationError) as exc:
        check_production_settings(debug=False, secret_key="", database_url=None)
    assert "DJANGO_SECRET_KEY" in str(exc.value)
