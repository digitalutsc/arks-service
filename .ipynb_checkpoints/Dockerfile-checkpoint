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

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Dependencies first so they cache independently of the source.
COPY pyproject.toml uv.lock* ./
RUN uv sync --no-install-project --extra postgres --extra mysql --frozen 2>/dev/null \
    || uv sync --no-install-project --extra postgres --extra mysql

COPY . .

# The image carries no data and no secrets; a throwaway key is enough to let
# collectstatic run at build time.
RUN DJANGO_SECRET_KEY=build-only DJANGO_DEBUG=false \
    python manage.py collectstatic --no-input

EXPOSE 8000
CMD ["gunicorn", "arkservice.wsgi:application", "--bind", "0.0.0.0:8000", \
     "--workers", "3", "--access-logfile", "-"]
