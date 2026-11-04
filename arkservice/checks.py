"""
Boot-time configuration guards.

Development defaults are a convenience; in production they are a hazard. A
missing ``DATABASE_URL`` would otherwise fall through to a local SQLite file and
every ARK would 404 with nothing in the log to say why, a missing
``DJANGO_SECRET_KEY`` would leave sessions forgeable, and a missing ``REDIS_URL``
would give each gunicorn process its own private cache, so the login lockout and
the redirect-hit buffer would not be shared. All three are refused outright.

Kept out of ``settings.py`` so it can be tested without importing Django
settings under a dozen different environments.
"""

from __future__ import annotations

#: The value settings.py falls back to when nothing is configured.
INSECURE_SECRET_KEY = "dev-insecure-key-change-me"

#: A secret shorter than this is treated as unset rather than merely weak.
MINIMUM_SECRET_KEY_LENGTH = 32


class ConfigurationError(Exception):
    """The service is not safe to start with this configuration."""


def check_production_settings(
    *,
    debug: bool,
    secret_key: str | None,
    database_url: str | None,
    redis_url: str | None = "",
) -> None:
    """
    Raise :class:`ConfigurationError` if this configuration must not run in production.

    No-op when ``debug`` is true.
    """
    if debug:
        return

    problems = []

    if not secret_key or secret_key == INSECURE_SECRET_KEY:
        problems.append(
            "DJANGO_SECRET_KEY is unset or still the development default. "
            'Generate one, e.g. python -c "import secrets; print(secrets.token_urlsafe(64))".'
        )
    elif len(secret_key) < MINIMUM_SECRET_KEY_LENGTH:
        problems.append(
            f"DJANGO_SECRET_KEY is shorter than {MINIMUM_SECRET_KEY_LENGTH} characters."
        )

    if not database_url:
        problems.append(
            "DATABASE_URL is unset. Without it the service would start against an empty "
            "local SQLite file and every ARK would return 404."
        )
    elif database_url.startswith("sqlite"):
        problems.append(
            f"DATABASE_URL points at SQLite ({database_url!r}), which is not supported in "
            "production. Use the MySQL/MariaDB server, e.g. mysql://user:pw@localhost/ark."
        )

    if not redis_url:
        problems.append(
            "REDIS_URL is unset. Production needs the Redis/Valkey server for the shared "
            "cache and the redirect-hit buffer, e.g. redis://:password@localhost:6379/1."
        )

    if problems:
        raise ConfigurationError(
            "Refusing to start: the production configuration is incomplete.\n  - "
            + "\n  - ".join(problems)
            + "\n(Set DJANGO_DEBUG=true for local development.)"
        )
