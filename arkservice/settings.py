"""
Django settings for the ARK service.

All deployment-specific values come from the environment (see .env.example), so the
project directory can be renamed freely without touching code.
"""

import os
from pathlib import Path

from environs import Env

from arkservice.checks import check_production_settings

BASE_DIR = Path(__file__).resolve().parent.parent

env = Env()
env.read_env(BASE_DIR / ".env", recurse=False)

SECRET_KEY = env.str("DJANGO_SECRET_KEY", default="dev-insecure-key-change-me")
DEBUG = env.bool("DJANGO_DEBUG", default=False)
_DATABASE_URL = env.str("DATABASE_URL", default="")

# Refuse to start on an incomplete production configuration rather than serving
# 404s from an empty SQLite file with a well-known secret key. Tests set
# PYTEST_VERSION, and run with DEBUG false, so they are exempt.
if not os.environ.get("PYTEST_VERSION") and not os.environ.get("ARKSERVICE_SKIP_CONFIG_CHECK"):
    check_production_settings(
        debug=DEBUG,
        secret_key=SECRET_KEY,
        database_url=_DATABASE_URL,
        redis_url=env.str("REDIS_URL", default=""),
    )
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])
CSRF_TRUSTED_ORIGINS = env.list("DJANGO_CSRF_TRUSTED_ORIGINS", default=[])

INSTALLED_APPS = [
    # django.contrib.admin is deliberately absent: it is never routed, and the
    # staff interface in admin_ui covers everything with its own role checks.
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "django_htmx",
    "core",
    "minting",
    "resolver",
    "admin_ui",
    "jobs",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "arkservice.middleware.SecurityHeadersMiddleware",
    # Serves static files straight from gunicorn, so the Docker image and a
    # bare gunicorn run need no separate web server. Apache can still take
    # over /static/ in production if preferred.
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django_htmx.middleware.HtmxMiddleware",
]

ROOT_URLCONF = "arkservice.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "admin_ui.context_processors.organisation",
                "admin_ui.context_processors.environment",
                "admin_ui.context_processors.navigation",
            ],
        },
    },
]

WSGI_APPLICATION = "arkservice.wsgi.application"

# --- Database -------------------------------------------------------------
# Postgres for dev/docker, MySQL/MariaDB in production. Both are first-class:
# the schema stays within the portable subset (no JSON columns, no SQL regex,
# no engine-specific full-text) and CI runs the suite against both.
DATABASES = {
    "default": env.dj_db_url(
        "DATABASE_URL",
        default="sqlite:///" + str(BASE_DIR / "db.sqlite3"),
        conn_max_age=env.int("DB_CONN_MAX_AGE", default=60),
        # A kept-open connection to a server across the network can be dropped
        # by the server or a firewall between requests; the next query then
        # fails with "MySQL server has gone away". Checking a reused connection
        # first costs one ping per request and reconnects instead.
        conn_health_checks=env.bool("DB_CONN_HEALTH_CHECKS", default=True),
    )
}

if DATABASES["default"]["ENGINE"] == "django.db.backends.mysql":
    # utf8mb4 + strict mode so silent truncation can never corrupt a binding.
    DATABASES["default"].setdefault("OPTIONS", {})
    DATABASES["default"]["OPTIONS"].update(
        {
            "charset": "utf8mb4",
            "init_command": "SET sql_mode='STRICT_TRANS_TABLES'",
            # Without these a MySQL server that stops answering (rather than
            # refusing) holds every request thread until the OS gives up on
            # the TCP connection, which can be many minutes.
            "connect_timeout": env.int("DB_CONNECT_TIMEOUT", default=5),
            "read_timeout": env.int("DB_READ_TIMEOUT", default=60),
            "write_timeout": env.int("DB_WRITE_TIMEOUT", default=60),
        }
    )

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-ca"
TIME_ZONE = env.str("DJANGO_TIME_ZONE", default="America/Toronto")
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"
        if not DEBUG
        else "django.contrib.staticfiles.storage.StaticFilesStorage"
    },
}

MEDIA_URL = "media/"
MEDIA_ROOT = env.path("MEDIA_ROOT", default=BASE_DIR / "media")

LOGIN_URL = "admin_ui:login"
LOGIN_REDIRECT_URL = "admin_ui:collection_list"
LOGOUT_REDIRECT_URL = "admin_ui:login"

SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
X_FRAME_OPTIONS = "DENY"

if not DEBUG:
    SESSION_COOKIE_SECURE = env.bool("SESSION_COOKIE_SECURE", default=True)
    CSRF_COOKIE_SECURE = env.bool("CSRF_COOKIE_SECURE", default=True)
    SECURE_CONTENT_TYPE_NOSNIFF = True
    # Apache sets this header itself (see deploy/apache-arkservice.conf); it is
    # only trustworthy because gunicorn listens on loopback and nothing else can
    # reach it directly.
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    # 0 by default so a first deployment cannot lock a domain into HTTPS before
    # the certificate is known good; set it once TLS is confirmed.
    SECURE_HSTS_SECONDS = env.int("SECURE_HSTS_SECONDS", default=0)
    SECURE_HSTS_INCLUDE_SUBDOMAINS = env.bool("SECURE_HSTS_INCLUDE_SUBDOMAINS", default=False)

# --- Cache ----------------------------------------------------------------
# Redis or Valkey in production (any server speaking the Redis protocol; the
# URL scheme stays redis:// or rediss:// for either). The Django cache holds the
# login lockout counter, the element-name list and the collection statistics,
# which are only shared between gunicorn workers if the cache is. The public
# resolver does not read it: its only use of the server is the redirect-hit
# buffer in core/counters.py, which talks to REDIS_URL directly and falls back to
# writing the database. Falls back to per-process memory so development needs
# no server; production refuses to start without REDIS_URL (arkservice/checks.py).
REDIS_URL = env.str("REDIS_URL", default="")
# Seconds to wait on the cache server before giving up. A hung or unreachable
# server must not hold a request thread: callers fall back or fail fast.
CACHE_SOCKET_TIMEOUT = env.float("CACHE_SOCKET_TIMEOUT", default=0.5)
if REDIS_URL:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": REDIS_URL,
            "OPTIONS": {
                "socket_connect_timeout": CACHE_SOCKET_TIMEOUT,
                "socket_timeout": CACHE_SOCKET_TIMEOUT,
            },
        },
    }
else:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "arkservice",
            "OPTIONS": {"MAX_ENTRIES": 10_000},
        },
    }

# --- Sign-in --------------------------------------------------------------
LOGIN_MAX_ATTEMPTS = env.int("LOGIN_MAX_ATTEMPTS", default=5)
LOGIN_LOCKOUT_SECONDS = env.int("LOGIN_LOCKOUT_SECONDS", default=15 * 60)
# Only true when a reverse proxy sets X-Forwarded-For and nothing else can
# reach gunicorn directly; otherwise the header is attacker-controlled.
TRUST_FORWARDED_FOR = env.bool("TRUST_FORWARDED_FOR", default=False)

SESSION_COOKIE_AGE = env.int("SESSION_COOKIE_AGE", default=8 * 60 * 60)
SESSION_SAVE_EVERY_REQUEST = True

# --- Celery ---------------------------------------------------------------
# The broker is Redis or Valkey; both use redis:// URLs and Celery's Redis
# transport. There is no valkey:// scheme.
CELERY_BROKER_URL = env.str("CELERY_BROKER_URL", default="redis://localhost:6379/0")
CELERY_RESULT_BACKEND = env.str("CELERY_RESULT_BACKEND", default=CELERY_BROKER_URL)
CELERY_TASK_ALWAYS_EAGER = env.bool("CELERY_TASK_ALWAYS_EAGER", default=False)
CELERY_TASK_EAGER_PROPAGATES = True
CELERY_TASK_TIME_LIMIT = env.int("CELERY_TASK_TIME_LIMIT", default=3600)
CELERY_WORKER_HIJACK_ROOT_LOGGER = False
# Nothing reads task results, so don't store them in the broker.
CELERY_TASK_IGNORE_RESULT = True
# Bulk binds are long; a worker should not reserve jobs it cannot start yet.
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
# Redis redelivers an unacknowledged task after visibility_timeout. It must be
# longer than the longest task, or a running bulk bind is handed out again.
CELERY_BROKER_TRANSPORT_OPTIONS = {"visibility_timeout": CELERY_TASK_TIME_LIMIT + 600}
# Beat's state file. /tmp because the systemd units make the working directory
# read-only (ProtectSystem=strict, with PrivateTmp) and the container's /app
# belongs to the image. The schedules are plain intervals, so losing the file on
# restart only means the first run happens one interval after start.
CELERY_BEAT_SCHEDULE_FILENAME = env.str(
    "CELERY_BEAT_SCHEDULE_FILENAME", default="/tmp/celerybeat-schedule"
)

# Redirect counts are buffered in the cache and written periodically, so that
# resolving stays a pure read. This is how often they land.
RESOLUTION_FLUSH_SECONDS = env.int("RESOLUTION_FLUSH_SECONDS", default=60)
# How often collection statistics and element-name lists are recounted in the
# background. Large collections show these stored figures ("as of HH:MM").
COLLECTION_STATS_SECONDS = env.int("COLLECTION_STATS_SECONDS", default=300)
CELERY_BEAT_SCHEDULE = {
    "flush-resolution-counters": {
        "task": "jobs.tasks.flush_resolution_counters",
        "schedule": RESOLUTION_FLUSH_SECONDS,
    },
    "reap-stale-jobs": {
        "task": "jobs.tasks.reap_stale_jobs",
        "schedule": 600,
    },
    "clear-expired-sessions": {
        "task": "jobs.tasks.clear_expired_sessions",
        "schedule": 24 * 60 * 60,
    },
    "prune-bulk-jobs": {
        "task": "jobs.tasks.prune_bulk_jobs",
        "schedule": 24 * 60 * 60,
    },
    "refresh-collection-stats": {
        "task": "jobs.tasks.refresh_collection_stats",
        "schedule": COLLECTION_STATS_SECONDS,
    },
}
# Scheduled housekeeping runs on its own queue, consumed by a small dedicated
# process (the Docker "scheduler" service, deploy/arkservice-beat.service), so
# long bulk binds on the default queue can never delay the counter flush.
PERIODIC_QUEUE = "periodic"
CELERY_TASK_ROUTES = {
    "jobs.tasks.flush_resolution_counters": {"queue": PERIODIC_QUEUE},
    "jobs.tasks.reap_stale_jobs": {"queue": PERIODIC_QUEUE},
    "jobs.tasks.clear_expired_sessions": {"queue": PERIODIC_QUEUE},
    "jobs.tasks.prune_bulk_jobs": {"queue": PERIODIC_QUEUE},
    "jobs.tasks.refresh_collection_stats": {"queue": PERIODIC_QUEUE},
}

# --- Resolver -------------------------------------------------------------
# Public base URL the admin UI uses when it shows an ARK's resolvable address.
# Empty means "derive it from the request", which is right whenever staff reach
# the admin on the same hostname the resolver answers on: Apache preserves the
# Host header and sets X-Forwarded-Proto, so the request already knows. Set it
# only when the two differ (an admin-only hostname, or a staging box whose ARKs
# should still be advertised under the production domain).
ARK_PUBLIC_BASE_URL = env.str("ARK_PUBLIC_BASE_URL", default="")

# Timeout (seconds) for the server-side fetch behind /manifest.
# Short by design: a /manifest request parks a worker on someone else's server,
# and the endpoint is public and unauthenticated. 30s meant a handful of slow
# targets could occupy every worker at once.
MANIFEST_FETCH_TIMEOUT = env.int("MANIFEST_FETCH_TIMEOUT", default=5)
# The fetch timeout above bounds each socket read; this bounds the whole fetch,
# so a server trickling bytes cannot hold a thread for minutes.
MANIFEST_TOTAL_TIMEOUT = env.float("MANIFEST_TOTAL_TIMEOUT", default=10)
MANIFEST_MAX_BYTES = env.int("MANIFEST_MAX_BYTES", default=10 * 1024 * 1024)
# Concurrent /manifest fetches per gunicorn process (each has 8 threads). Past
# this, callers get 503 + Retry-After instead of taking every thread.
MANIFEST_MAX_CONCURRENT = env.int("MANIFEST_MAX_CONCURRENT", default=4)

# Largest batch a single mint request may create; 0 means no cap. Bigger
# batches hold the collection lock and build every identifier inside one
# transaction. The mint form also runs inside the web request, so a batch that
# outlasts the gunicorn timeout is rolled back and the user sees an error page;
# bulk bind mints in the worker and has no such ceiling.
MINT_MAX_PER_REQUEST = env.int("MINT_MAX_PER_REQUEST", default=10_000)

# Staff-side limits that keep whole-collection work out of web requests.
# Sorting by redirects or elements evaluates a subquery for every matching ARK,
# so it is only offered on result sets up to this size.
SORT_SUBQUERY_MAX_ROWS = env.int("SORT_SUBQUERY_MAX_ROWS", default=50_000)
# Exports from the staff UI larger than this point to the export_arks command
# instead of holding a web thread for minutes.
EXPORT_SYNC_MAX_ROWS = env.int("EXPORT_SYNC_MAX_ROWS", default=100_000)

# Upload guardrails for bulk bind. DATA_UPLOAD_MAX_MEMORY_SIZE does NOT cover
# multipart file parts, so an explicit byte ceiling is needed as well as a row
# ceiling — without it a multi-gigabyte upload fills the disk and then the
# worker's memory before the row check is ever reached.
BULK_BIND_MAX_ROWS = env.int("BULK_BIND_MAX_ROWS", default=100_000)
BULK_BIND_MAX_BYTES = env.int("BULK_BIND_MAX_BYTES", default=50 * 1024 * 1024)
# Days to keep finished bulk-bind jobs and their files; 0 keeps them forever.
# Pruned daily by the scheduler, or by hand with `manage.py prune_bulk_jobs`.
BULK_BIND_RETENTION_DAYS = env.int("BULK_BIND_RETENTION_DAYS", default=0)
DATA_UPLOAD_MAX_MEMORY_SIZE = env.int("DATA_UPLOAD_MAX_MEMORY_SIZE", default=20 * 1024 * 1024)
FILE_UPLOAD_MAX_MEMORY_SIZE = env.int("FILE_UPLOAD_MAX_MEMORY_SIZE", default=5 * 1024 * 1024)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"simple": {"format": "{levelname} {asctime} {name} {message}", "style": "{"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "simple"}},
    "root": {"handlers": ["console"], "level": env.str("DJANGO_LOG_LEVEL", default="INFO")},
}
