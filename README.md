# ARK Service

Minting, binding and resolution of [ARK identifiers](https://arks.org/),
replacing the legacy PHP service in `../legacy/`. Django 5.2 LTS on Python 3.12+.

Every ARK already in circulation keeps resolving; the cutover is verified before
anything is switched over.

## Documentation

| | |
|---|---|
| [docs/DEPLOY.md](docs/DEPLOY.md) | Local, Docker, CI and production deployment; environment variables; troubleshooting |
| [docs/MIGRATION.md](docs/MIGRATION.md) | Moving the legacy service's data here: what maps to what, the review report, the cutover runbook |
| [docs/USAGES.md](docs/USAGES.md) | Every task, in the staff interface and on the command line (staff commands need the optional `arks-cli` plugin) |
| [docs/README_EXTENDED.md](docs/README_EXTENDED.md) | Architecture, components, data model and diagrams of every request path |
| [docs/GUIDES.md](docs/GUIDES.md) | The code study guide: every package, model, flow and setting, with diagrams |
| [docs/fallback-example/](docs/fallback-example/) | Starting kit for operator-supplied landing and error pages (`FALLBACK_PAGES_DIR`) |
| [docs/SCALE.md](docs/SCALE.md) | Measured performance and capacity, what grows and what does not |
| [deploy/](deploy/) | systemd units and the Apache vhost |
| [../docker-arks-service/](../docker-arks-service/) | The Docker stack for development and demos, driven by `make` |

## Quick start

```bash
uv venv --python 3.13
uv sync --extra postgres --extra mysql
cp .env.example .env                  # then edit
./.venv/bin/python manage.py migrate
./.venv/bin/python manage.py createsuperuser
./.venv/bin/python manage.py runserver
```

Or bring the whole stack up — app, worker, Valkey (or Redis), PostgreSQL — from the
deployment repository,
[`docker-arks-service`](https://github.com/digitalutsc/docker-arks-service):

```bash
cd ../docker-arks-service && make up
# http://localhost:8000, with the login it prints
```

`make up` does everything, from nothing, and is safe to repeat. With that
repository beside this one it builds from this checkout; cloned on its own, it
fetches a copy of this repository for itself. After changing code here,
`make install` there rebuilds the image — the source is baked in, not mounted.

That repository holds every Docker file; this one holds none. In production
the same stack can run against an existing MySQL server instead of its own
database container, or the service can run bare on the VM without Docker
([docs/DEPLOY.md](docs/DEPLOY.md)). Either way the broker and cache is Valkey by default, or Redis.

## How it fits together

```
resolver/     the public /ark:... endpoint — the only thing the world touches
core/         collections, ARKs, bindings, search, legacy import, verification
minting/      the noid port and the minter
admin_ui/     staff interface (Django templates + HTMX) and roles
jobs/         bulk-bind uploads, run on Celery
```

**Data model.** Legacy packed everything into per-collection `_key`/`_value`
tables with tab-separated keys. Here that is normalised into `Collection →
Ark → Binding`, where a binding is `(qualifier, name, value)`. Any element name
may be bound — `URL`, `PID` and `LOCAL_ID` are conventions the resolver and
reports look for, not schema. Two constraints the legacy system lacked:
`(naan, identifier)` is unique, and so is `(ark, qualifier, name)`.

**Minting.** Identifiers are built by the same base conversion as legacy, so new
ARKs are indistinguishable from the ~100k already in production and old ones
still pass check-character validation. What changed is that *which* number comes
next is decided against the database rather than by replaying Perl's `rand()`.
Eight concurrent minters cannot produce a duplicate — that is a test, not a hope.

**Resolver.** The whole legacy contract: exact-qualifier redirect with a
`WHERE?` fallback, no ancestor fallback, the `?` / `??` / `?info` metadata
inflections, `/manifest` JSON proxying, per-qualifier redirect counters, and the
NAA response for a bare NAAN.

**Staff interface.** A sidebar console: dashboard, collections (each with its own ARK
browser), users. Every ARK is shown with the URL it actually resolves at *in the
environment you are looking at* — derived from the request, so Docker shows
`http://localhost:8000/ark:/…` and production shows the real domain. Override
with `ARK_PUBLIC_BASE_URL` only when staff reach the admin on a different
hostname than the resolver. The sidebar names the environment for the same
reason: nobody should paste a localhost URL into a catalogue record. There is no
inline CSS or JavaScript anywhere in the templates — the CSP forbids both, and a
test enforces it.

**No HTTP API.** The admin UI talks to the ORM directly; scripts use management
commands. Legacy `admin/rest.php` goes away at cutover — check your access logs
for callers first ([docs/DEPLOY.md](docs/DEPLOY.md#step-0--find-out-who-calls-the-old-rest-endpoint)).

## Command line

The operator commands ship with the service:

```bash
manage.py export_arks --collection utsc --out /tmp/utsc.csv
manage.py refresh_collection_stats [utsc]
manage.py prune_bulk_jobs --older-than 180 [--dry-run]
manage.py flush_counters
manage.py import_legacy --legacy-dump /srv/ARK_CORE.sql --report review.csv
manage.py resolve_diff --legacy-base https://old --new-base http://127.0.0.1:8000 \
    --known review.csv
manage.py check_manifests --collection utsc --out manifests.csv
```

The staff commands are the optional **[arks-cli](https://github.com/digitalutsc/arks-cli)** plugin (a sibling checkout, not on PyPI): `createcollection`, `mint`, `bind`, `unbind`, `bulk_bind` and `ark_stats`. Everything they do can be done in the staff interface. To enable them, install the plugin and add `ARKS_PLUGINS=arks_cli` to `.env`:

```bash
uv pip install -e ../arks-cli --python .venv/bin/python
manage.py mint utsc 500 --template /tmp/batch.csv
```

## Tests

```bash
./.venv/bin/python -m pytest                    # whole suite
./.venv/bin/python -m pytest tests/test_noid.py # noid conformance only
./.venv/bin/ruff check . && ./.venv/bin/ruff format --check .
```

The noid port is pinned to the legacy PHP by 1,469 golden vectors. Regenerate
them (needs `php` and the legacy checkout alongside):

```bash
php tests/fixtures/generate_vectors.php > tests/fixtures/noid_vectors.json
```

Run against a real engine by setting `DATABASE_URL`; CI runs both:

```bash
DATABASE_URL=postgres://ark:ark@127.0.0.1:5432/ark ./.venv/bin/python -m pytest -q
DATABASE_URL=mysql://root:root@127.0.0.1:3306/ark ./.venv/bin/python -m pytest -q
```

## Databases

PostgreSQL and MySQL/MariaDB are both first-class: production runs MySQL, dev
and Docker run PostgreSQL. The schema stays inside the portable subset — no JSON
columns, no SQL regex, no engine-specific full-text — and CI runs the suite
against both to keep it that way. Free-text search is therefore a `LIKE` scan;
measured over 418k bindings it answers in about a quarter of a second, and an
engine-specific index can be added later without a schema change.

## Renaming this directory

Nothing inside refers to the directory name. The Django package is `arkservice`,
the Compose project name is set explicitly, and every path is relative or comes
from the environment. `mv` it wherever you like.

## Credits

The identifier algorithms in `minting/noid.py` (templates, character
repertoires, `n2xdig` and the check character) are a port of:

- **[Noid](https://metacpan.org/dist/Noid)** (Nice Opaque Identifiers), the
  Perl minter by John A. Kunze at the California Digital Library.
  Copyright 2002–2006 UC Regents, released under a BSD-type licence.
- **[Noid4Php](https://github.com/Daniel-KM/Noid4Php)**, the PHP port by
  Daniel Berthereau, released under the CeCILL-B licence.

Their licence notices are reproduced in `minting/noid.py`. This project is not
endorsed by the UC Regents, the University of California or the authors of
either library.

It replaces the earlier PHP ARK service, built by the Digital Scholarship Unit
on Noid4Php and kept at
[digitalutsc/arks-service-archived](https://github.com/digitalutsc/arks-service-archived);
the identifiers it minted remain valid here.

The staff interface bundles [htmx](https://htmx.org/) (Zero-Clause BSD) and the
IBM Plex fonts (SIL Open Font License 1.1, see `static/fonts/LICENSE.txt`).

## License

BSD 2-Clause; see [LICENSE](LICENSE). To contribute, see
[CONTRIBUTING](.github/CONTRIBUTING.md).
