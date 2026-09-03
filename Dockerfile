# Dev and prototype image. Production runs bare on the LAMP VM (see deploy/),
# so nothing here is required for the real deployment — it exists so the whole
# stack can be brought up on any machine with one command, and so the codebase
# can be shared with a runnable environment attached.
FROM python:3.13-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_PROJECT_ENVIRONMENT=/usr/local

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential default-libmysqlclient-dev pkg-config curl \
    && rm -rf /var/lib/apt/lists/*

# Pinned: :latest would change the build from under us.
COPY --from=ghcr.io/astral-sh/uv:0.9.18 /uv /usr/local/bin/uv

WORKDIR /app

# Dependencies first so they cache independently of the source.
COPY pyproject.toml uv.lock* ./
RUN uv sync --no-install-project --extra postgres --extra mysql --frozen 2>/dev/null \
    || uv sync --no-install-project --extra postgres --extra mysql

COPY . .

# The image carries no data and no secrets. collectstatic runs with
# DJANGO_DEBUG=false so the hashed-manifest storage is used; the boot guard is
# skipped explicitly because there is no database or secret at build time and
# none is needed to collect static files.
RUN DJANGO_DEBUG=false ARKSERVICE_SKIP_CONFIG_CHECK=1 \
    python manage.py collectstatic --no-input

# Run as an unprivileged user: a container process that does not need root
# should not have it, and MEDIA_ROOT is the only thing it writes.
RUN useradd --system --uid 10001 --home /app --shell /usr/sbin/nologin app \
    && mkdir -p /data/media \
    && chown -R app:app /app /data
USER app

EXPOSE 8000
# Threads rather than more processes: a /manifest fetch parks a worker on I/O,
# and 3 sync workers meant three slow targets could stall the whole service.
CMD ["gunicorn", "arkservice.wsgi:application", "--bind", "0.0.0.0:8000", \
     "--workers", "3", "--threads", "8", "--worker-class", "gthread", \
     "--timeout", "60", "--access-logfile", "-"]
