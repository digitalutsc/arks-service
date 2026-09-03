# ARK Service

Minting, binding and resolution of [ARK identifiers](https://arks.org/), replacing the
legacy PHP service (see `../legacy/`). Django 5.2 LTS on Python 3.12+.

## Quick start (dev)

```bash
uv venv --python 3.13
uv sync --extra postgres
cp .env.example .env          # then edit
./.venv/bin/python manage.py migrate
./.venv/bin/python manage.py createsuperuser
./.venv/bin/python manage.py runserver
```

## Tests

```bash
./.venv/bin/python -m pytest              # whole suite
./.venv/bin/python -m pytest tests/test_noid.py   # noid conformance only
./.venv/bin/ruff check . && ./.venv/bin/ruff format --check .
```

The noid port is pinned to the legacy PHP implementation by golden vectors. To
regenerate them (requires `php` and the legacy checkout alongside):

```bash
php tests/fixtures/generate_vectors.php > tests/fixtures/noid_vectors.json
```

## Databases

PostgreSQL and MySQL/MariaDB are both first-class: production runs on the existing
MySQL server, Docker/dev uses PostgreSQL. The schema stays inside the portable
subset — no JSON columns, no SQL regex, no engine-specific full-text — and CI runs
the suite against both. Select the engine with `DATABASE_URL`.
