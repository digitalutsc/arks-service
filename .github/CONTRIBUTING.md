# Contributing to arks-service

Thank you for your interest in arks-service. It is the ARK identifier service: minting, binding and resolving Archival Resource Keys, with a staff interface. It is maintained by the Digital Scholarship Unit (DSU) at the University of Toronto Scarborough Library for the library's own use, and published as open source so that others can use it and improve it.

## How we work

- **Pull requests are welcome.** We review every pull request and merge the ones that fit the project.
- **We don't take feature requests,** and we can't offer support or help with your installation. If you need a feature, you're welcome to build it and open a pull request, or to keep it in your own fork.
- **Bug reports are welcome** as issues, but we can't promise when, or whether, a bug will be fixed. A pull request with the fix is the fastest way to get one in.

## Reporting a bug

Search the existing issues first. Then open an issue that includes:

- what you did (the commands, URLs or steps),
- what you expected to happen, and what happened instead (the error message, traceback or log lines),
- the versions involved: the commit or release, Python, the database engine and version, and whether you run it bare or in Docker.

**Never attach database exports, `.env` files, passwords, keys or production data** to an issue or pull request. Reduce the problem to an example with made-up data.

## Reporting a security vulnerability

Please don't open a public issue. Report it privately with **Report a vulnerability** on the repository's **Security** tab.

## Submitting a pull request

1. Fork the repository and create a branch from `main`.
2. Keep each pull request to one change. Describe what it changes and why, and link the issue it fixes, if there is one.
3. Add or update tests that cover the change.
4. Update the documentation if behaviour, settings or commands change.
5. Run the checks below before you push. CI runs them on every pull request, and a pull request is reviewed once they pass.
6. A maintainer reviews the pull request. We may ask for changes, or decline a change that is outside what the project needs; if we do, we'll say why.

## Setting up a development environment

You need Python 3.12 or later and [uv](https://docs.astral.sh/uv/).

```bash
uv venv --python 3.13 && uv sync --extra postgres --extra mysql
cp .env.example .env
./.venv/bin/python manage.py migrate
./.venv/bin/python manage.py runserver
```

`CELERY_TASK_ALWAYS_EAGER=true` in `.env` runs bulk binds without a broker or worker. To run the whole stack in Docker instead, use the companion repository [docker-arks-service](https://github.com/digitalutsc/docker-arks-service).

## Checks

```bash
./.venv/bin/ruff check . && ./.venv/bin/ruff format --check .
./.venv/bin/python -m pytest

# CI also runs the suite on both production engines:
DATABASE_URL=postgres://ark:ark@127.0.0.1:5432/ark ./.venv/bin/python -m pytest -q
DATABASE_URL=mysql://root:root@127.0.0.1:3306/ark ./.venv/bin/python -m pytest -q
```

CI (`.github/workflows/ci.yml`) runs the linter, the test suite on PostgreSQL and MySQL, and a conformance check that compares the identifier algorithms with the legacy PHP implementation.

## Conventions

- **Style:** ruff, with a line length of 100. `ruff format` settles formatting.
- **One place for writes:** binding, unbinding and bulk changes go through `core/services.py`, which the staff interface, the management commands and bulk bind all call. Don't add write logic to a view or a command.
- **Portable database code:** production runs MySQL and development PostgreSQL, and CI tests both. Use the ORM only: no JSON columns, no database regular expressions, no engine-specific full-text search, and don't rely on `bulk_create` returning primary keys.
- **No inline styles or scripts:** the Content Security Policy is `script-src 'self'; style-src 'self'`, and a test fails on any inline `style=` or event handler. Put CSS in `static/css` and JavaScript in `static/js`.
- **The identifier algorithms are pinned:** `minting/noid.py` must produce exactly what the legacy PHP produces, checked by `tests/fixtures/noid_vectors.json`. Don't change its output.
- **Configuration comes from the environment:** add every new setting to `.env.example`, with a comment.
- **A new top-level Django app** also needs a `COPY` line in docker-arks-service's `Dockerfile`.

## Licensing

This project is licensed under the [BSD 2-Clause License](../LICENSE). By submitting a pull request, you agree that your contribution is licensed under the same terms.
