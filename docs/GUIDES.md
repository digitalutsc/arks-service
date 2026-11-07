# arks-service — code study guide

A complete walk through the Django application: every package, every model, every flow, and the reasons behind the shape. Written from the code as it stands on 2026-11-05. `README_EXTENDED.md` is the shorter architecture overview; this guide is the superset and quotes real identifiers so you can jump straight into the source.

Diagrams are Mermaid; GitHub renders them inline.

---

## Contents

1. [What this service is](#1-what-this-service-is)
2. [Repository map](#2-repository-map)
3. [Runtime architecture](#3-runtime-architecture)
4. [Request routing](#4-request-routing)
5. [Data model](#5-data-model)
6. [ARK path parsing](#6-ark-path-parsing)
7. [The public resolver](#7-the-public-resolver)
8. [Minting](#8-minting)
9. [Services layer](#9-services-layer)
10. [Search and export](#10-search-and-export)
11. [Redirect counting](#11-redirect-counting)
12. [Staff interface](#12-staff-interface)
13. [Bulk bind](#13-bulk-bind)
14. [Celery and scheduling](#14-celery-and-scheduling)
15. [Management commands](#15-management-commands)
16. [Legacy import and cutover verification](#16-legacy-import-and-cutover-verification)
17. [Settings and configuration](#17-settings-and-configuration)
18. [Testing](#18-testing)
19. [Conventions and gotchas](#19-conventions-and-gotchas)
20. [Glossary](#20-glossary)

---

## 1. What this service is

An **ARK identifier service**: it mints persistent identifiers of the form `ark:/61220/utsc1`, lets staff bind metadata elements to them (most importantly a `URL`), and resolves public requests for them with an HTTP redirect. It replaces the UTSC Digital Scholarship Unit's PHP service (a ~1,900-line `admin.php`, a flat `rest.php`, a `resolver.php`, all over a vendored fork of Noid4Php that stored everything as tab-separated keys in one MySQL table per collection).

### The contract that must not change

About 100,000 ARKs are in circulation in catalogue records, papers and crawler indexes. Everything the outside world can observe about them is fixed:

| Fixed by the legacy service | Where it is honoured here |
|---|---|
| Identifier shape (`utsc` + noid digits, check characters) | `minting/noid.py`, pinned by 1,469 golden vectors generated from the PHP |
| Redirect at the exact qualifier, `URL` then `WHERE?`, **no fallback up the hierarchy** (unless a collection turns on suffix passthrough, off by default) | `resolver/views.py::_target_url` |
| `?`, `??`, `?info` inflections return `erc:` metadata without counting a hit | `core/arkpath.py`, `resolver/services.py::render_erc` |
| `/manifest` proxies JSON: the URL bound at `/manifest`, else the object's (configurable per collection since 2026-11-06; R0) | `resolver/views.py::_resolution_target`, `_manifest` |
| A bare NAAN returns the Name Assigning Authority | `resolver/views.py::_naa_response` |
| Split the path on `/` and `?` *before* percent-decoding | `core/arkpath.py::parse_ark_path` |
| Element names stored upper-case | `Binding.save`, `core/services.py::normalise_element_name` |

`resolve_diff` (section 16) exists to prove all of this against the live legacy service before the vhost is flipped.

### Deliberate departures

| Legacy had | Here | Why |
|---|---|---|
| Perl `rand()` replay for random minters | CSPRNG + database uniqueness | Ordering was never observable; the emulation was the riskiest code in the port |
| `:/oacounter`, `:/h` holds, queues | `Ark.sequence` + `select_for_update` | The database decides the next number; a unique constraint makes a duplicate impossible |
| HTTP Digest with reversibly-encrypted passwords | Django sessions, hashed passwords, three roles | Legacy accounts are **not** migrated |
| Browser-driven one-row-per-POST bulk bind | Whole-file validation on a Celery worker; nothing written if any row fails | The old way left half-updated collections |
| `admin/rest.php` | **No HTTP API** | Scripts use management commands on the host; one fewer authenticated surface, and no second implementation to keep in step with the UI |
| Whole-database dump before every write | Transactions + ordinary scheduled backups | A mint can no longer corrupt anything it did not touch |

---

## 2. Repository map

```
arks-service/
├── manage.py
├── pyproject.toml            Django 5.2, Celery 5.5, redis, environs, gunicorn, whitenoise, django-htmx;
│                             extras: postgres (psycopg), mysql (mysqlclient); dev group: pytest, ruff, fakeredis
├── uv.lock                   the Docker image is built with `uv sync --frozen` from this
├── conftest.py               autouse fixtures: cache clearing, fakeredis for the counters
├── .env.example              every environment variable with a comment
│
├── arkservice/               the Django project
│   ├── settings.py           reads .env, calls the boot guard, every setting from the environment
│   ├── checks.py             boot guard: refuses DEBUG=false without secret, DB and REDIS_URL
│   ├── middleware.py         SecurityHeadersMiddleware: CSP, Referrer-Policy, Permissions-Policy
│   ├── urls.py               /ark:…  /healthz  /admin/  /
│   ├── celery.py             the Celery app (config from settings, namespace CELERY_)
│   ├── wsgi.py, asgi.py
│
├── core/                     domain model and everything shared
│   ├── models.py             Collection, Ark, Binding, Resolution, Organisation
│   ├── arkpath.py            parse_ark_path(): the legacy URL grammar
│   ├── services.py           bind/unbind/bulk upsert/stats — used by UI, CLI and import
│   ├── search.py             search_arks(), sort_arks(), export_rows(), element_names(), csv_safe()
│   ├── counters.py           buffered redirect counting (redis-py, not the Django cache)
│   ├── legacy.py             read-only readers for a legacy DB or a mysqldump file
│   ├── verify.py             what resolve_diff compares and how it normalises
│   ├── migrations/0001…0006
│   └── management/commands/  the operator commands (section 15); the staff ones are the arks-cli plugin
│
├── minting/
│   ├── noid.py               pure port of noid: alphabets, n2xdig, check_char, parse_template, make_id, xdig2n
│   └── minter.py             mint(): the stateful, DB-locked part
│
├── resolver/                 the only unauthenticated surface
│   ├── views.py              resolve(), landing(), the manifest proxy
│   ├── services.py           raw_request_uri(), render_erc(), safe_target(), fetch_json()
│   ├── health.py             /healthz
│   └── fallback.py           operator-supplied landing and error pages from FALLBACK_PAGES_DIR; handler403/404/500, /fallback/<name> assets, superuser preview
│
├── admin_ui/                 staff interface
│   ├── urls.py               15 routes under /admin/
│   ├── views.py              every staff view
│   ├── roles.py              Admin / Editor / Viewer as Django groups; require_role
│   ├── throttle.py           login lockout per (username, address)
│   ├── auth_views.py         ThrottledLoginView
│   └── context_processors.py organisation/role, sidebar section, environment + public base URL
│
├── jobs/                     bulk bind
│   ├── models.py             BulkBindJob (+ claim/mark_* state transitions, results file)
│   ├── bulkbind.py           apply_csv(): validate everything, then write
│   ├── tasks.py              run_bulk_bind, flush_resolution_counters, reap_stale_jobs, prune_bulk_jobs,
│   │                         clear_expired_sessions, refresh_collection_stats
│   ├── retention.py          prune_jobs()
│   └── progress.py           Reporter / read / describe: a running job's phase and counts, in the cache
│
├── templates/                base.html, admin_ui/*.html (16 files), resolver/landing.html
├── static/                   css/app.css, js/app.js, js/collection_form.js, js/htmx.min.js (vendored)
├── deploy/                   systemd units (3), Apache vhost, logrotate — bare-VM production
├── docs/                     every document but README.md: README_EXTENDED, GUIDES (this), DEPLOY, MIGRATION, USAGES, SCALE
│   └── fallback-example/     starting kit for FALLBACK_PAGES_DIR: index.html (3 placeholders), 403/404/500.html, style.css, README
├── scripts/bench/            seed.py / measure.py, the source of every number in SCALE.md
└── tests/                    43 files, ~908 test functions, 3,817 collected (parametrised vectors)
```

### Which document is authoritative for what

| Document | Authoritative for |
|---|---|
| `README.md` | Quick start and the one-screen summary |
| `docs/README_EXTENDED.md` | Architecture overview with the original diagrams and the design-decisions table |
| `docs/DEPLOY.md` | Every environment (local, Docker, CI, bare VM), every environment variable, cutover steps, troubleshooting |
| `docs/MIGRATION.md` | What the legacy data was, how it maps, the importer's rules, the review report, the runbook |
| `docs/USAGES.md` | Every staff task in both the UI and the CLI; template and CSV reference |
| `docs/SCALE.md` | Measured performance at 1M and 4M ARKs; what grows with the collection |
| `deploy/README.md` | One paragraph per deployment file |
| `../docker-arks-service/` | Everything Docker: this repo has no Docker files by design |
| `../TEST_CASES.md` | 552 reproducible test cases across deployment and application |

---

## 3. Runtime architecture

Three application processes share one image/checkout and one `.env`. Only `web` is reachable from outside.

```mermaid
flowchart TB
    subgraph Internet
        PUB["Public: browsers, crawlers,<br/>citations"]
        STAFF["Staff browsers"]
    end

    AP["Apache :443 (production)<br/>TLS · ProxyPass nocanon · X-Forwarded-Proto<br/>Docker dev: no Apache, port 8000 direct"]

    subgraph App["Application processes (same code, same .env)"]
        WEB["<b>web</b> · gunicorn<br/>3 procs × 8 gthread threads<br/>migrate on start (Docker)<br/>WhiteNoise serves /static/"]
        WRK["<b>worker</b> · celery -Q celery<br/>concurrency 2, prefork<br/>bulk binds only"]
        SCH["<b>scheduler</b> · celery -Q periodic<br/>--pool solo --beat<br/>exactly one instance"]
    end

    DB[("MySQL (prod) / PostgreSQL (dev)<br/>the only durable state")]
    V0[("Valkey DB 0<br/>Celery queues:<br/>celery, periodic")]
    V1[("Valkey DB 1<br/>Django cache: login throttle,<br/>element names, mint template ids<br/>+ hash arks:hits (counters)")]
    MEDIA[("MEDIA_ROOT<br/>bulk-bind results<br/>+ uploads until the job ends")]

    PUB -->|"GET /ark:/…"| AP
    STAFF -->|"/admin/…"| AP
    AP --> WEB
    WEB -->|"ORM"| DB
    WEB -->|"HINCRBY per redirect<br/>cache get/set"| V1
    WEB -->|"run_bulk_bind.delay"| V0
    WEB --> MEDIA
    V0 --> WRK
    V0 --> SCH
    WRK -->|"apply_csv in one txn"| DB
    WRK --> MEDIA
    SCH -->|"flush counters, recount stats,<br/>reap jobs, clear sessions, prune"| DB
    SCH -->|"RENAME/HGETALL/HDEL arks:hits"| V1
    SCH --> MEDIA
```

### What each process needs, and what it survives without

| Process | Needs to start | Survives without | Degrades how |
|---|---|---|---|
| `web` | DB reachable, `DJANGO_SECRET_KEY`, `DATABASE_URL`, `REDIS_URL` set (boot guard) | Valkey **down** at runtime | Redirects keep working (two indexed reads, hit written straight to DB); `/healthz` returns 503; staff login throttle and cached lists fall back per-process; bulk-bind upload fails visibly |
| `worker` | DB + broker | nothing else | Without it jobs stay PENDING; the reaper re-queues after 15 min once it is back |
| `scheduler` | DB + broker | nothing else | Without it counters never flush (`counters_flushed_ago` grows), stored stats go stale, sessions/jobs are not pruned; the resolver is unaffected |

The resolver's independence from Valkey is deliberate (2026-11-04): the redirect target used to be cached and the cache server became a single point of failure for the public surface. Now the only thing the resolver asks Valkey for is `HINCRBY`, and any exception there means "write the hit to MySQL instead".

---

## 4. Request routing

> Error handlers: `handler403`, `handler404` and `handler500` point at `resolver/fallback.py` (section 12, *Fallback pages*): operator files when `FALLBACK_PAGES_DIR` is set, Django's defaults otherwise.

`arkservice/urls.py`, in order:

| Pattern | View | Notes |
|---|---|---|
| `re_path(r"^ark:.*$")` | `resolver.views.resolve` | Catches every `/ark:…` path. The view re-reads the raw URI, so Django's query-string handling never sees a bare `?` |
| `healthz` | `resolver.health.healthz` | Public, JSON, 200/503 |
| `admin/` → `admin_ui.urls` | 15 staff routes | Namespace `admin_ui` |
| `""` | `resolver.views.landing` | Public landing page |

`django.contrib.admin` is **not installed**; there is no `/django-admin/`.

### Middleware stack (`settings.MIDDLEWARE`, in order)

| # | Middleware | Role here |
|---|---|---|
| 1 | `SecurityMiddleware` | HSTS (when `SECURE_HSTS_SECONDS` > 0), `X-Content-Type-Options`, SSL redirect handling via `SECURE_PROXY_SSL_HEADER` |
| 2 | `arkservice.middleware.SecurityHeadersMiddleware` | Adds `Content-Security-Policy`, `Referrer-Policy`, `Permissions-Policy` to **every** response (uses `setdefault`, so a view could override) |
| 3 | `WhiteNoiseMiddleware` | Serves `/static/` straight from gunicorn; Docker relies on it, the bare vhost aliases `/static/` to disk instead |
| 4 | `SessionMiddleware` | DB-backed sessions, 8 h, saved every request |
| 5 | `CommonMiddleware` | |
| 6 | `CsrfViewMiddleware` | Every staff POST carries a token |
| 7 | `AuthenticationMiddleware` | |
| 8 | `MessageMiddleware` | Flash messages shown by `base.html` |
| 9 | `XFrameOptionsMiddleware` | `X-Frame-Options: DENY` |
| 10 | `django_htmx.middleware.HtmxMiddleware` | `request.htmx`; views actually test the `HX-Request` header directly |

The CSP is the reason there is no inline `style=` or `onclick=` anywhere in a template (`tests/test_admin_ui_shell.py` fails on either):

```
default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self';
connect-src 'self'; form-action 'self'; base-uri 'self'; object-src 'none'; frame-ancestors 'none'
```

`Referrer-Policy: strict-origin-when-cross-origin` matters specifically for the resolver: a 302 to someone else's site must not tell them which ARK was looked up.

---

## 5. Data model

### Entity relationship

```mermaid
erDiagram
    COLLECTION ||--o{ ARK : "mints"
    ARK ||--o{ BINDING : "has elements"
    ARK ||--o{ RESOLUTION : "redirect counts"
    COLLECTION ||--o{ BULKBINDJOB : "uploads into"
    USER ||--o{ ARK : "minted_by"
    USER ||--o{ BULKBINDJOB : "created_by"
    USER }o--o{ GROUP : "Admin | Editor | Viewer"

    COLLECTION {
        bigint id PK
        varchar255 name UK
        varchar64 prefix "blank allowed; UK with naan"
        varchar16 naan
        text naa "returned for /ark:/naan/"
        varchar64 template "e.g. .zd"
        varchar16 term "short|medium|long"
        datetime created_at
        bigint ark_count "stored stats"
        bigint bound_count
        bigint binding_count
        bigint redirect_total
        datetime stats_refreshed_at
    }
    ARK {
        bigint id PK
        bigint collection_id FK
        varchar16 naan "copied from collection on save"
        varchar255 identifier "includes prefix; UK with naan"
        bigint sequence "nullable; counter that produced it"
        datetime minted_at
        bigint minted_by_id FK "nullable"
    }
    BINDING {
        bigint id PK
        bigint ark_id FK
        varchar255 qualifier "'' | /page1 | .png | /page1.png"
        varchar255 name "upper-cased; UK with ark+qualifier"
        text value
        varchar191 value_prefix "GENERATED lower(substr(value,1,191))"
        datetime created_at
        datetime updated_at
    }
    RESOLUTION {
        bigint id PK
        bigint ark_id FK
        varchar255 qualifier "UK with ark"
        bigint count
        datetime last_at
    }
    ORGANISATION {
        int id PK "always 1"
        varchar255 name
        url website
        datetime updated_at
    }
    BULKBINDJOB {
        bigint id PK
        bigint collection_id FK
        file upload
        file results
        bool mint_missing
        bool purge_first
        varchar16 status "pending|running|finished|failed"
        varchar255 task_id
        text error
        int created
        int updated
        int minted
        int failed
        bigint created_by_id FK
        datetime created_at
        datetime started_at
        datetime finished_at
    }
```

### Constraints and indexes, and why each exists

| Table | Constraint / index | Reason |
|---|---|---|
| `core_collection` | `name` unique | Collections are named by staff; the CLI accepts a name as a collection reference |
| | `unique_prefix_per_naan (naan, prefix)` | Two naming authorities may both use `utsc`; their ARKs are told apart by NAAN. Was service-wide unique until migration `0004` |
| `core_ark` | `unique_ark_per_naan (naan, identifier)` | **The resolver's guarantee**: one ARK means one thing. Also the backstop under concurrent minting |
| | `ark_collection_ident_idx (collection, identifier)` | Minting probes and bulk-bind lookups ask "which of these identifiers exist in this collection" |
| | `ark_minted_at_idx` | Minted-after/before filters and the Minted sort |
| | `ark_collection_seq_idx (collection, sequence)` | Sequential minting reads `MAX(sequence)` for a collection as an index-only lookup |
| `core_binding` | `unique_element_per_qualifier (ark, qualifier, name)` | An element cannot exist twice; also serves every `(ark)` and `(ark, qualifier)` lookup, which is why there is no separate `(ark, qualifier)` index (dropped in `0005`) |
| | `binding_name_value_idx (name, value_prefix)` | Exact-value and starts-with search. `value` is unbounded `TEXT`, which MySQL cannot index, so the first 191 lower-cased characters are copied into a **generated, persisted** column (`0003`). 191 keeps the composite index inside MySQL's 3072-byte utf8mb4 limit beside a 255-char name |
| `core_resolution` | `unique_resolution_per_qualifier (ark, qualifier)` | One counter row per resolvable path; `Resolution.record` relies on the IntegrityError to resolve a create race |
| `jobs_bulkbindjob` | `ordering = ["-created_at"]` | Recent uploads first on collection pages |

### Field semantics worth knowing

- **`Ark.naan`** is denormalised from the collection in `Ark.save()` so the unique constraint and the resolver lookup never need a join.
- **`Ark.sequence`** is `NULL` for imported identifiers that do not fit the template. `minter._next_sequential` reads the highest non-null sequence; gaps below it are never refilled.
- **`Ark.path`** is `ark:61220/utsc1` (relative, slashless). The host is an environment concern (`context_processors.environment`), not an identifier concern.
- **`Binding.qualifier`** is one string: hierarchy and variant concatenated (`/page1.image.png`). `core/arkpath._split_qualifier` splits it back at the first dot after the last slash, and `core/legacy.parse_legacy_key` joins legacy's tab components into it. The round trip is exact.
- **`Binding.save()`** upper-cases `name`. Every bulk writer bypasses `save()`, so `core/services.normalise_element_name` has to be applied explicitly there too.
- **`ELEMENT_URL = "URL"`, `ELEMENT_WHERE = "WHERE?"`** are the only names the resolver knows. `PID`, `LOCAL_ID`, `COLLECTION` are just the columns the fill-in template offers (`jobs.bulkbind.TEMPLATE_COLUMNS`).
- **`Collection` stored stats** (`0006`) exist because `COUNT(*)` over 4M ARKs took 6.6 s per page view. `core/services.current_stats` uses them only when `ark_count >= 50_000` and `stats_refreshed_at` is set; smaller collections are counted live.
- **`Resolution.record`** is the write-through path (used only when the counter buffer is unavailable): `UPDATE … count = count + 1`; if no row, `INSERT` inside `transaction.atomic()`, and on `IntegrityError` retry the update. Getting this wrong turned the first crawler hit after cutover into a 500.
- **`Organisation`** is a singleton: `save()` forces `pk = 1`, `load()` is `get_or_create(pk=1)`. It replaces legacy's `system` table (name, website).

### Legacy ↔ new mapping

| Legacy (one `_key`/`_value` table per collection) | Here |
|---|---|
| the table | one `Collection`, named after the table unless `--collection-name` |
| `:/naan`, `:/prefix`, `:/template`, `:/naa` | `naan`, `prefix`, `template`, `naa` |
| `:/longterm` → long; `:/wrap` → short; else medium | `term` |
| `61220/utsc1<TAB>URL` | `Binding(ark, qualifier="", name="URL")` |
| `61220/utsc1<TAB>/page1<TAB>.png<TAB>URL` | `Binding(qualifier="/page1.png")` |
| `61220/utsc1<TAB>REDIRECT` = 37 | `Resolution(count=37)` |
| `61220/utsc1<TAB>:/c` = `i\|20201022094659\|1603374419\|1` | `Ark.minted_at` (field 3 is a Unix timestamp) |
| `:/h`, `:/oacounter`, `:/saclist`, `:/erc`, `:/q/…` | dropped |
| `system` table | `Organisation` |
| `user` table | **not migrated** |

---

## 6. ARK path parsing

`core/arkpath.py` is the grammar every entry point shares: the resolver, the CLI (`_common.get_ark`), bulk bind (`_ark_name`) and the verifier all call `parse_ark_path`.

### Grammar

```
/ark:/<naan>/<identifier>[<qualifier>][?|??|?info]      (a service suffix such as /manifest is just the qualifier's last segment)
  qualifier  := ('/' segment)* ['.' variant]      e.g. /page1   .image.png   /page1.image.png
  hierarchy  := everything up to the first '.' after the last '/'
  variant    := from that '.' to the end
```

`_ARK_RE = ^/?ark:/?(?P<rest>.*)$`, case-insensitive, so `ark:61220/utsc1` (the slashless form the staff UI links to) and `/ARK:/…` both parse.

### Flow

```mermaid
flowchart TD
    A["raw path"] --> B{"matches ^/?ark:/?"}
    B -->|no| N0["None (404)"]
    B -->|yes| C["_detect_inflection: split at FIRST '?'"]
    C --> C1{"text after '?'"}
    C1 -->|"nothing"| I1["BRIEF (?)"]
    C1 -->|"'?' or 'info'"| I2["FULL (?? / ?info)"]
    C1 -->|"anything else"| I3["NONE — ordinary query string, discarded"]
    C1 -->|"no '?' at all"| I3
    I1 --> D
    I2 --> D
    I3 --> D
    D["(a service suffix such as /manifest stays in the qualifier)"] --> E["trailing_slash = rest.endswith('/')"]
    E --> F["parts = [unquote(p) for p in rest.split('/') if p]<br/><i>split first, decode each part second</i>"]
    F --> G{"parts empty?"}
    G -->|yes| N0
    G -->|no| H["naan = parts[0]<br/>identifier = parts[1] or ''<br/>qualifier = '/' + '/'.join(parts[2:]) or ''"]
    H --> J["naan_only = identifier == '' and (trailing_slash or len(parts)==1)"]
    J --> K["ArkPath(naan, identifier, qualifier, inflection, naan_only)<br/>+ last_segment, parent_qualifier"]
```

### Why split before decoding

Legacy's Apache rewrite handed `resolver.php` a decoded `$_GET['q']`, and the import stores legacy keys literally. So the *comparison* must be against decoded text, but the *structure* must be decided on the encoded text. Otherwise `%2F` inside an identifier would become a qualifier separator and `%3F` would become an inflection. `resolver/services.raw_request_uri` re-encodes `request.path` on the fallback route so both routes decode exactly once (`test_decoding_is_the_same_with_and_without_a_raw_uri`).

### Examples

| URI | naan | identifier | qualifier | inflection | last_segment | naan_only |
|---|---|---|---|---|---|---|
| `/ark:/61220/utsc1` | 61220 | utsc1 | `""` | NONE | `""` | no |
| `/ark:61220/utsc1` | 61220 | utsc1 | `""` | NONE | `""` | no |
| `/ark:/61220/utsc1/page1` | 61220 | utsc1 | `/page1` | NONE | `page1` | no |
| `/ark:/61220/utsc1.image.png` | 61220 | `utsc1.image.png` | `""` | NONE | `""` | no |
| `/ark:/61220/utsc1/page1.image.png` | 61220 | utsc1 | `/page1.image.png` | NONE | `page1.image.png` | no |
| `/ark:/61220/utsc1?` | 61220 | utsc1 | `""` | BRIEF | `""` | no |
| `/ark:/61220/utsc1??` | 61220 | utsc1 | `""` | FULL | `""` | no |
| `/ark:/61220/utsc1?info` | 61220 | utsc1 | `""` | FULL | `""` | no |
| `/ark:/61220/utsc1?utm=x` | 61220 | utsc1 | `""` | NONE | `""` | no |
| `/ark:/61220/utsc1/manifest` | 61220 | utsc1 | `/manifest` | NONE | `manifest` | no |
| `/ark:/61220/utsc1/manifest?` | 61220 | utsc1 | `/manifest` | BRIEF | `manifest` | no (inflection wins in the view: metadata of `/manifest`) |
| `/ark:/61220/` and `/ark:/61220` | 61220 | `""` | `""` | NONE | `""` | **yes** |
| `/ark:/61220/utsc1%2Fpage1` | 61220 | `utsc1/page1` | `""` | NONE | `""` | no |
| `/ark:/61220/utsc1%3F` | 61220 | `utsc1?` | `""` | NONE | `""` | no |

Note the fourth row. A **variant on the bare ARK** (`utsc1.image.png`) parses the dot into the *identifier*, because the identifier is simply `parts[1]`, as in legacy. That parse is kept, so an identifier that really contains a dot still matches exactly. The variant is reached by a second reading, tried only after that lookup misses: `ArkPath.object_variant()` splits at the first dot into identifier `utsc1` and qualifier `.image.png`, which is how such a binding is stored (a legacy key `61220/utsc1<TAB>.png<TAB>URL` imports as `Binding(qualifier=".png")`). The resolver (`_locate`), `get_ark` (so `manage.py bind 61220/utsc1.image.png …` works) and bulk bind all use it, so an export of such a variant uploads back unchanged. It applies only with no qualifier and something on both sides of the dot. Until 2026-11-06 this was an open item (`INTENTS_object_variants.md`; `CLI_TEST_RUNBOOK.md` Suspect 18).

---

## 7. The public resolver

`resolver/views.py::resolve` — the decision order is the legacy order and tests pin it.

```mermaid
flowchart TD
    A["GET /ark:…"] --> B["parse_ark_path(raw_request_uri(request))"]
    B -->|None| X404a["404 Not an ARK"]
    B --> C{"naan_only?"}
    C -->|yes| D["Collection.filter(naan).exclude(naa='') first → 200 text/plain NAA<br/>else 404"]
    C -->|no| E["_locate: Ark.select_related('collection').filter(naan, identifier).first()"]
    E -->|None| X404b["404 Unknown ARK"]
    E --> F{"inflection != NONE?"}
    F -->|yes| G["render_erc(_metadata_bindings(ark, qualifier), include_support=FULL)<br/>200 text/plain — NOT counted"]
    F -->|no| I["_resolution_target: _target_url at EXACT qualifier<br/>first of collection.redirect_elements bound (default URL, WHERE?)<br/>for a proxied suffix, else at the parent qualifier"]
    I -->|None| SPT{"collection.suffix_passthrough?<br/>(only after every reading missed)"}
    SPT -->|"on, hierarchy part,<br/>no . or .. segment"| P["_passthrough: nearest bound ancestor's URL<br/>+ '/' + rest of the path (re-encoded)<br/>counted against the ancestor"]
    P --> J
    SPT -->|off / nothing above| X404c["404 Nothing bound<br/><i>no fallback to parent unless passthrough is on</i>"]
    I -->|target| H{"last segment in<br/>collection.proxied_suffixes?"}
    H -->|yes| M["_manifest(ark, target)<br/>JSON, NOT counted"]
    H -->|no| J["record_resolution(ark.pk, qualifier)<br/>HINCRBY, else write-through"]
    J --> K["302 Location: target"]
```

Every lookup above goes through `_locate(parsed, probe)`: the request **as written** first, then, only if that misses, each of `parsed.alternatives()` in turn: the object-variant reading (`utsc1.pdf` as ARK `utsc1`, qualifier `.pdf`; `ArkPath.object_variant()`), the spec-normalised form (`parsed.normalised()`, draft-kunze-ark-44 §3.2: hyphens removed, trailing `.` and `/` removed, case kept), and the normalised form's object-variant reading. ARK lookups are shared between readings with the same identifier. A miss is no such ARK, or nothing for the probe (`_resolution_target` for redirects and proxied suffixes, `_has_metadata` for inflections). So `utsc-1`, `utsc1.` and `utsc1/page-2` reach `utsc1` and `utsc1/page2`, an exact match always wins, a redirect that hits keeps its two reads, and the hit is counted against the qualifier that resolved. The route matches `ark:` in any case (`ARK:` too). Normalising never walks up the hierarchy: `/page-3` becomes `/page3`, not the parent. See `INTENTS_identifier_normalisation.md` and `INTENTS_object_variants.md`.

**Per-collection resolution settings** (`INTENTS_collection_resolution_settings.md`). `Collection.redirect_elements` is the ordered list of elements a redirect URL is read from (default `URL,WHERE?`, legacy's order); the first bound with a non-empty value wins. `Collection.proxied_suffixes` (default `manifest`) lists the final qualifier segments answered by proxying JSON instead of redirecting: `…/<q>/manifest` fetches the URL bound at `<q>/manifest` (legacy's pre-generated IIIF manifests), else the URL at `<q>`. The parser no longer strips `/manifest`; which segments are services is only known once the ARK, and so its collection, is found. Both are comma-separated `CharField`s (no JSON columns), validated by `core/services.py::parse_redirect_elements` / `parse_proxied_suffixes`, set at creation (form, `createcollection --redirect-elements/--proxied-suffixes`) and changed only by an Admin on the collection page after a preview (`resolution_impact`) and a confirm (`update_resolution_settings`, which stamps `resolution_changed_at/_by` and logs a WARNING with old → new).

**Suffix passthrough** (R6, `INTENTS_suffix_passthrough.md`), `Collection.suffix_passthrough`, off by default. When on, `_locate` runs `_passthrough` as a last resort: only after the request *and* every `alternatives()` reading missed exactly, over the same readings in the same order.
- **The target:** a hierarchy part with nothing bound (`/page7`) redirects to the **nearest bound ancestor's** URL (one query over every level above it, using the collection's redirect elements), plus `/` and the rest of the path, each segment re-encoded (`quote`, RFC 3986 pchar safe set).
- **Refused:** `.` and `..` segments (404); object-level variants (`.png`) and proxied suffixes are not passed through, and metadata is unchanged.
- **Counting:** the hit counts against the ancestor that supplied the URL (`Target.counted`), so made-up paths never create `Resolution` rows.
- **Cost:** an exact redirect stays at two reads, a passthrough one costs three.
- **Cutover:** `resolve_diff` only checks bound paths, so the gate holds with it on or off.

### Metadata selection

`_metadata_bindings(ark, qualifier)`:

- qualified request → bindings with exactly that qualifier;
- bare request → `qualifier == ""` **or** `qualifier.startswith(".")`. Legacy matched `<ark>\t[^/]`, so variant-only qualifiers were listed with the object's own elements while hierarchical parts were not.

### `render_erc(bindings, include_support)` (`resolver/services.py`)

1. Drop `INTERNAL_ELEMENTS = {"REDIRECT", ":/C", ":/H"}`.
2. Brief block: `erc:` then one `Label: value` per element whose name does **not** contain `??`.
3. If `include_support` and any element name contains `??`: blank line, `erc-support:`, those elements. If none, **no header at all** (legacy printed nothing, and `resolve_diff` would otherwise differ on every `??` path).
4. `format_label("WHERE?") == "Where"`, `format_label("LOCAL_ID") == "Local_id"`, `format_label("NODE ID") == "Node Id"`: legacy's `ucwords(strtolower(...))` after removing every `?`, so every space-separated word is capitalised but `_` and `-` are not word breaks; ASCII letters only, as in PHP 8. Values are emitted verbatim (legacy replaced `_` with space, corrupting URLs).

### The manifest proxy

```mermaid
sequenceDiagram
    participant C as Client
    participant V as _manifest
    participant S as safe_target
    participant DNS
    participant T as Target server
    C->>V: GET /ark:/n/id/manifest
    V->>V: _target_url → else 404
    V->>V: BoundedSemaphore(MANIFEST_MAX_CONCURRENT=4).acquire(blocking=False)
    alt no slot
        V-->>C: 503 {"error": …} Retry-After: 5
    end
    V->>S: fetch_json(target)
    S->>S: scheme in (http, https)? hostname present?
    S->>DNS: getaddrinfo(host, port)
    DNS-->>S: every address
    S->>S: _unwrap() IPv4-mapped and NAT64, then is_global for EACH address; any non-global → UnsafeTarget
    S-->>V: FetchTarget(url, host, address=first, port)
    V->>T: connect to the PINNED address, Host header = real host, TLS SNI = real host, no redirects
    T-->>V: headers (+ Content-Length) then body in 64 KiB read1() chunks
    V->>V: Content-Length over 10 MB → TargetTooLarge before reading; deadline MANIFEST_TOTAL_TIMEOUT=30 s checked per chunk (each read waits up to MANIFEST_FETCH_TIMEOUT=30 s) → TargetTooSlow; received over max → TargetTooLarge
    V->>V: json.loads(body) must parse
    V-->>C: 200 application/json, body passed through byte-for-byte, Access-Control-Allow-Origin: *
```

Error mapping: `UnsafeTarget` → 502 "may not be fetched" (warning logged: this is a bad binding, not a down server); `TargetTooLarge` → 502; `TargetTooSlow` → 504; any other exception → 502; non-JSON → 502. The semaphore is per gunicorn process and is rebuilt if the setting changes (`_manifest_slots_for`). Pinning the connection to the vetted address is what closes DNS rebinding. Every manifest response, errors and 503 included, carries `Access-Control-Allow-Origin: *` so a IIIF viewer on another site can read it; nothing else from the resolver does (`INTENTS_manifest_hardening.md`). `manage.py check_manifests` fetches every bound suffix target the same way and reports ok / empty / not-json / too-large / too-slow / redirect / http-error / refused / failed, and `core/verify.py::compare` treats legacy 500 vs our 502/503/504 on a proxied path as agreement.

### `raw_request_uri` and why gunicorn is required

Django drops a `?` with nothing after it before `QUERY_STRING` is populated. Gunicorn exposes the original request line as `RAW_URI` (other servers may set `REQUEST_URI`); the view reads that first. The fallback (`request.path` re-quoted + `QUERY_STRING`) cannot recover a bare `?`, which is why `runserver` cannot be used for the cutover diff and why Apache must proxy with `nocanon`.

### `/healthz` (`resolver/health.py`)

Three checks, each caught independently: `SELECT 1`; `cache.set/get("healthz")`; `counters.ping()` (true when no `REDIS_URL`). Returns `{"status": "ok"|"degraded", "checks": {...}, "counters_flushed_ago": N|null}` with 200 or 503. Failure detail goes to the log only, because the endpoint is public. `counters_flushed_ago` never fails the check: a stalled scheduler is not a reason to pull the resolver.

### Landing page

`landing()` renders `resolver/landing.html` with `Organisation.load()` and every collection with a non-blank NAAN, as a NAAN → authority table (`collection.naa|default:collection.name`).

---

## 8. Minting

### 8.1 `minting/noid.py`: the pure port

No Django, no database. Everything here is pinned to the legacy PHP by `tests/fixtures/noid_vectors.json` (1,328 `n2xdig` cases, 42 templates, 25 check-character cases, 5 sequences, the alphabet tables).

**Template grammar.** `<prefix>.<mask>`, mask `= [rsz][dixevElwc]+k?`:

| Mask letter | Meaning |
|---|---|
| `r` | random order |
| `s` | sequential, fixed width |
| `z` | sequential, unlimited: the most significant repertoire repeats as the number grows |
| `d` | digits `0-9` |
| `e` | extended digits `0123456789bcdfghjkmnpqrstvwxz` (29, no vowels, no `l`) |
| `i x v E w c l` | other repertoires in `ALPHABETS` (proposed/compat; `c` is not ARK-safe) |
| `k` | trailing check character |

`parse_template("utsc.zd")` → `TemplateSpec(template, prefix="utsc", mask="zd", gen_type="sequential", total=NOLIMIT, synonym="utsc1+")`. It rejects `""` and `"-"` (legacy accepted them as "no minting"), a missing `.`, a mask not starting with `r/s/z`, more than one `k` or a `k` not at the end, letters outside the repertoires, and a prefix with characters outside the check repertoire for `[de]+k` masks.

**Capacity** = product of the repertoire sizes over the mask letters, `NOLIMIT` (-1) for `z`:

| Template | Computation | Capacity |
|---|---|---|
| `.zd`, `.zeee`, `.zdeek` | unlimited | ∞ |
| `.sdd` | 10 × 10 | 100 |
| `.rddd` | 10³ | 1,000 |
| `.rdddd` | 10⁴ | 10,000 |
| `.sdddddd` | 10⁶ | 1,000,000 |
| `.rdedk` | 10 × 29 × 10 | **2,900** (`USAGES.md` said 8,410 until 2026-11-05; the code was right) |
| `.reedeedk` | 29 × 29 × 10 × 29 × 29 × 10 | 70,728,100 |

`template_choices()` computes these for the UI from `TEMPLATE_CATALOGUE`, so the form can never disagree with the minter.

**`n2xdig(num, mask)`** walks the mask right-to-left, dividing `num` by each repertoire's size and prepending the digit. `r`/`s` terminate even if `num` is not used up (fixed width truncates). `z` sets `var_width` and keeps the last repertoire until `num` is exhausted. A trailing `k` appends a literal `+` placeholder.

**`check_char(identifier, alphabet="e")`** takes the *whole* ARK (`61220/utsc1+`): `total = Σ position × index(char)` over every character but the last (characters outside the alphabet count 0, including `/`), `computed = chars[total % len]`. A trailing `+` means compute; anything else is verified and `None` returned on mismatch. `check_repertoire(template)` picks `e` for `[de]+k` masks (Perl compatibility) else the shortest repertoire covering every possible character.

**`make_id(firstpart, mask, num)`** = `firstpart + n2xdig(num, mask)`, then `check_char` if the mask ends in `k`.

**`xdig2n(variable_part, mask)`** is the inverse, used by the importer to recover `Ark.sequence` from a legacy identifier (`_decode_sequence`), which is what lets minting resume at `utsc97640` after importing up to `utsc97639`.

### 8.2 `minting/minter.py`: the stateful part

```mermaid
sequenceDiagram
    participant Caller as UI / CLI / bulk bind
    participant M as mint()
    participant DB
    Caller->>M: mint(collection, count, user, enforce_cap)
    M->>M: count < 1 → ValueError
    M->>M: enforce_cap and count > MINT_MAX_PER_REQUEST (10,000; 0 = off) → ValueError
    M->>DB: SELECT … FROM core_collection WHERE id=? FOR UPDATE
    Note over M,DB: every other minter of this collection now waits
    M->>M: spec = parse_template(prefix + template)
    alt sequential (s/z)
        M->>DB: MAX(sequence) via ark_collection_seq_idx
        loop until count chosen
            M->>M: candidates = next up-to-`wanted` counter values (stop at capacity)
            M->>DB: WHERE identifier IN (≤1000 candidates) — _taken_identifiers
            M->>M: keep the free ones
        end
        M->>M: capacity exhausted before count → TemplateExhausted (nothing created)
    else random (r)
        M->>DB: count() of the collection; capacity-used < count → TemplateExhausted
        loop up to 8 rounds
            M->>M: draw min(4×wanted, 1000) distinct secrets.randbelow(capacity)
            M->>DB: WHERE identifier IN (candidates)
        end
        M->>M: still short → _sweep_for_free: scan 0..capacity in 1000-chunks
    end
    M->>DB: bulk_create(Ark × count, batch_size=1000)
    alt MySQL left pk None
        M->>DB: SELECT id, identifier WHERE identifier IN (…) and copy pks back
    end
    M-->>Caller: list[Ark] with pks, in order
```

Design points:

- The lock on the collection row is the ordering mechanism; `unique_ark_per_naan` is the backstop. `test_concurrent_minters_never_produce_the_same_ark` runs eight threads and skips on SQLite.
- Cost does not grow with the collection: candidates are probed in `_PROBE_CHUNK = 1000` IN-lists, never by loading existing identifiers (the earlier version loaded all of them: 116 MB at 1M ARKs, inside the lock).
- Random minting never materialises `range(capacity)` (2.8 GB for `.reedeedk`); after 8 rounds it sweeps in chunks.
- `enforce_cap=False` is passed only by bulk bind's `mint_missing`, which runs on the worker and is bounded by `BULK_BIND_MAX_ROWS` instead.
- All-or-nothing: `@transaction.atomic` on `mint()`.

**Not ported from Perl noid / Noid4Php:** `rand()` replay, the `:/oacounter` position, `:/saclist`/`:/q` queues, `:/h` holds, per-minter log files, whole-database backups before each mint.

---

## 9. Services layer

`core/services.py` exists because the staff UI and the management commands once each had their own bind/unbind logic, and they drifted (over whether a rebind touched `updated_at`). Now `admin_ui/views.py`, every command, `jobs/bulkbind.py` and `import_legacy` call the same functions.

| Function | Does | Used by |
|---|---|---|
| `normalise_element_name(name)` | `strip().upper()` | every bulk writer (they bypass `Binding.save`) |
| `bind_element(ark, name, value, qualifier="")` | `update_or_create` on `(ark, qualifier, name)`; `ValidationError` on blank name; returns `(binding, created)` | ARK page, `bind` command |
| `unbind_elements(ark, name=None, qualifier=None)` | delete; `qualifier=None` means every qualifier, `name=None` means every element → returns count | ARK page remove, purge, `unbind` command |
| `bulk_upsert_bindings({(ark_id, qualifier, name): value})` | per 2000-ARK chunk: read existing rows for those ARKs, `bulk_create` the new, `bulk_update(value, updated_at)` only where the value **changed**; returns `(created, updated)` | bulk bind, import |
| `collection_stats(collection)` | live `COUNT`s: total, bound (`Exists`), unbound, elements, redirects (`Sum`) | `ark_stats`, refresh |
| `refresh_collection_stats(collection)` | counts and stores them on the row with `stats_refreshed_at` | scheduler task, `refresh_collection_stats` command |
| `current_stats(collection)` | `(stats, as_of)`: stored figures when `ark_count >= LIVE_STATS_MAX_ARKS (50,000)` and refreshed at least once, else counts live and returns `as_of=None` | dashboard, collection page |

`bulk_upsert_bindings` chunks by ARK id so one IN-list never approaches MySQL's `max_allowed_packet` (around 4M ids) and so only one chunk's rows are in memory. Unchanged values are left alone, which is what makes re-import and re-upload cheap no-ops.

---

## 10. Search and export

`core/search.py`. Two constraints: search must reach *any* element name, and it must stay inside the portable SQL subset (no full-text, no regex).

### `search_arks(...)` filters

| Parameter | SQL shape |
|---|---|
| `collection` | `WHERE collection_id = ?` |
| `text`, `text_mode=TEXT_STARTS` | `pk IN _starts_with_ids(text)`: two **separate** index range scans, `identifier ILIKE 'x%'` on ARKs and `value_prefix ILIKE 'x%' AND name IN (element_names)` on bindings, unioned in Python. More than `STARTS_WITH_CAP = 50,000` ids → `TooManyMatches` |
| `text`, `text_mode=TEXT_CONTAINS` (CLI default) | `identifier ILIKE '%x%' OR EXISTS(binding.value ILIKE '%x%')`: a scan, ~16 s at 4M ARKs on MySQL |
| `element`, `value` | `EXISTS(binding WHERE name=UPPER(element) [AND value_prefix = value_prefix(value) AND value IEXACT value])`: the prefix hits the index, `iexact` re-checks the full value |
| `bound` | `EXISTS` / `NOT EXISTS` any binding |
| `minted_after`, `minted_before` | `minted_at >= / <=` |
| `min_redirects` | `EXISTS(resolution WHERE count >= n)` |

`Exists()` keeps rows distinct without a `DISTINCT`, which would force a sort over the whole result.

### Sorting (`parse_sort`, `sort_arks`)

`SORT_KEYS = ("ark", "minted", "redirects", "elements")`; a leading `-` means descending; unknown → default `ark`. `minted` orders by `(minted_at, id)` so pages are stable when an import stamped thousands with the same instant. `redirects` and `elements` annotate a correlated subquery (`Sum(count)` / `Count(id)`) and order by it, which the database must evaluate for every matching row, so `admin_ui.views.ark_list` refuses them above `SORT_SUBQUERY_MAX_ROWS` (50,000).

### Counting

`counted(queryset, cap=COUNT_CAP=10_000)` → `(n, capped)` via `queryset[:cap].count()`. InnoDB keeps no row count, so an exact `COUNT(*)` is a full index scan. The browse page shows "10,000+" and skips the count entirely when page 1 holds everything.

### Export (`export_rows`, `_id_chunks`)

```mermaid
flowchart LR
    A["header = [Ark_ID] + sorted(element_names(collection))"] --> B["_id_chunks: page by key<br/>WHERE (naan, identifier) after last ORDER BY naan, identifier LIMIT 2000"]
    B --> C["bindings for the chunk,<br/>ordered by ark, qualifier, name"]
    C --> D["one row per (ark, qualifier);<br/>unbound ARK → a row with blanks<br/>value → csv_safe(value)"]
    D --> B
```

Key paging rather than `.iterator()` because MySQL's client buffers the whole result before the first row (a 4M-id list, 371 MB). The header comes from the cached element names, so an element bound mid-stream is skipped rather than aborting the download. The output shape is exactly what bulk bind consumes.

`element_names(collection_id, refresh, lifetime)` is a `DISTINCT name` over bindings capped at `MAX_ELEMENT_NAMES = 500`, cached under `element-names:<id|all>` for 300 s; the scheduler rebuilds it every `COLLECTION_STATS_SECONDS` with a 3× lifetime so requests normally only read the cache.

`csv_safe(value)` prefixes `'` to values starting with `= + - @ \t \r` (spreadsheet formula injection); `csv_unsafe` undoes it and is applied **only** when a job's results file is read back (`BulkBindJob.iter_results`). See section 19 for the round-trip consequence.

---

## 11. Redirect counting

`core/counters.py` talks to `REDIS_URL` with redis-py directly (not the Django cache), with `socket_timeout = socket_connect_timeout = CACHE_SOCKET_TIMEOUT (0.5 s)` and `health_check_interval=30`.

```mermaid
sequenceDiagram
    participant R as resolver (web)
    participant V as Valkey DB1
    participant S as scheduler: flush_counters()
    participant DB

    R->>V: HINCRBY arks:hits "ark_id:qualifier" 1
    alt any exception / no REDIS_URL
        R->>DB: Resolution.record(ark, qualifier)  (write-through; one warning per 60 s per process)
    end

    Note over S: every RESOLUTION_FLUSH_SECONDS (60)
    S->>V: SET arks:flush-lock token NX EX 300
    alt lock held by another flush
        S-->>S: return 0
    end
    loop at most twice
        S->>V: EXISTS arks:hits:flushing ?
        alt not exists
            S->>V: RENAME arks:hits → arks:hits:flushing  (atomic; new hits start a fresh hash)
        end
        S->>V: HGETALL arks:hits:flushing
        loop batches of FLUSH_BATCH = 500 pairs
            S->>DB: one transaction: UPDATE count = count + n per distinct n; INSERT missing rows; skip dead ARKs
            Note over S,DB: IntegrityError (a write-through row appeared) → retry the batch once
            S->>V: HDEL arks:hits:flushing <fields of this batch>
        end
        S->>V: DEL arks:hits:flushing
    end
    S->>V: SET arks:last-flush <unix time>
    S->>V: DEL arks:flush-lock (only if the token is still ours)
```

Properties:

- Per-hit cost is one `HINCRBY`, independent of how many ARKs have pending hits; concurrent hits cannot clobber each other (the earlier pickled-set buffer did both).
- Counts lag by up to the flush interval. This is the trade that makes resolving a pure read.
- An interrupted flush leaves `arks:hits:flushing`; the next flush drains it first, then renames the live hash and drains that too (the "two passes").
- **The one double-count window**: a crash between a batch's commit and its `HDEL`. Bounded to one batch of 500 pairs; a hit is never lost.
- `_apply` groups pairs by hit count and issues one `UPDATE … count = count + n` per distinct `n` (a handful), which was six times faster on MySQL than `bulk_update`'s CASE expression.
- `ping()` returns `True` with no server configured; `last_flush_age()` feeds `/healthz`.
- Test suite: the autouse `counter_redis` fixture swaps `_client` for a per-test `fakeredis` server.

---

## 12. Staff interface

### Routes (`admin_ui/urls.py`), roles and templates

| Path | View | Minimum role | Template | Notes |
|---|---|---|---|---|
| `login/` | `ThrottledLoginView` | – | `login.html`, `locked_out.html` (429) | |
| `logout/` | Django `LogoutView` | – | – | POST only |
| `` | `collection_list` | Viewer | `collection_list.html` | dashboard |
| `collections/new/` | `collection_create` | **Admin** | `collection_form.html` | |
| `collections/<pk>/` | `collection_detail` | Viewer (POST re-checks Admin) | `collection_detail.html` | edit name + NAA only |
| `collections/<pk>/mint/` | `mint_view` | Editor | `mint.html` | |
| `collections/<pk>/mint/template.csv` | `mint_template` | Editor | CSV | ids from cache, 1 h |
| `collections/<pk>/bulk-bind/` | `bulk_bind` | Editor | `bulk_bind.html` | |
| `collections/<pk>/activity/` | `collection_activity` | Viewer | `_collection_activity.html` | the ARK list's activity strip, polled every 3 s while a job runs |
| `arks/` | `ark_list` | Viewer | `ark_list.html` / `_ark_table.html` (HTMX) | **requires `?collection=`**; otherwise redirects to Collections (`HX-Redirect` for htmx) |
| `arks/<pk>/` | `ark_detail` | Viewer (POST re-checks Editor) | `ark_detail.html` | bind/unbind, variants |
| `arks/<pk>/purge/` | `ark_purge` | **Admin**, POST only | – | |
| `export.csv` | `export` | Viewer | streaming CSV | requires `?collection=`, as the list does |
| `jobs/<pk>/` | `job_detail` | Editor | `job.html` / `_job_status.html` (HTMX) | |
| `jobs/<pk>/results.csv` | `job_results` | Editor | CSV | |
| `users/` | `user_list` | **Admin** | `user_list.html` | role changes; never your own row or a superuser's |
| `users/new/` | `user_create` | **Admin + `is_superuser`**, POST only | re-renders `user_list.html` on error | add an ordinary account |
| `users/<pk>/delete/` | `user_delete` | **Admin + `is_superuser`**, POST only | – | hard delete; refuses self, superusers, the last Admin |
| `/fallback/<name>` | `resolver.fallback.asset` | – (public) | file | a stylesheet or image beside the fallback pages; allow-listed extensions, bare filenames only |
| `/fallback/preview/<key>/` | `resolver.fallback.preview` | `is_superuser` | file, status 200 | preview of `index`/`403`/`404`/`500`/`503` |

The sidebar has two entries (Collections, and Users for Admins). Inside a collection, `_collection_header.html` renders a second-level **tab row**: Overview (`collection_detail`), Browse ARKs (`ark_list`), and for Editors Mint and Bulk bind; `COLLECTION_TABS` in `views.py` maps each view to its tab, and `_header()` supplies the collection's size (one `COUNT` for a small collection, the stored figure for a large one).

### Roles (`admin_ui/roles.py`)

```mermaid
flowchart LR
    U["request.user"] --> A{"authenticated?"}
    A -->|no| L["redirect_to_login(next=…)"]
    A -->|yes| S{"is_superuser?"}
    S -->|yes| AD["ADMIN"]
    S -->|no| G["groups among Admin, Editor, Viewer<br/>most privileged wins; cached on the user object for the request"]
    G -->|none| N["role None → PermissionDenied 403<br/>'This needs the X role; yours is none.'"]
    G --> R{"_RANK[role] ≥ _RANK[minimum]?"}
    AD --> R
    R -->|no| F["403"]
    R -->|yes| V["view runs"]
```

`set_role` removes every role group and adds one inside a transaction; `clear_role` leaves an account that can sign in and do nothing; `is_last_administrator(user)` counts other **active** superusers or Admin-group members, and `user_list` refuses to demote the last one. Two more refusals in `user_list`: your own row (so nobody locks themselves out) and any superuser's row (groups do not affect a superuser, so the control would do nothing). Ordinary accounts are added and deleted on the Users page by a **superuser** only (`user_create`, `user_delete`; Django's password validators apply, delete refuses self, superusers and the last Admin). Superusers themselves are created on the server (`createsuperuser`), never in the UI.

### Login throttle (`throttle.py`, `auth_views.py`)

Failures are counted in the Django cache under `login-failures:<username lower>:<address>` with `cache.incr`, or `cache.add(key, 1, LOGIN_LOCKOUT_SECONDS)` to start. At `LOGIN_MAX_ATTEMPTS` (5) the POST is answered with `locked_out.html` and 429 **before** the form is processed, so a later correct guess is still refused for 900 s. `client_address` uses the **last** `X-Forwarded-For` entry only when `TRUST_FORWARDED_FOR` is true (Apache appends the real address; everything before it is client-controlled). With the locmem fallback the counter is per gunicorn process, which is why production requires `REDIS_URL`.

### Context processors

| Processor | Adds |
|---|---|
| `organisation` | `organisation`, `user_role`, `can_edit`, `can_administer` |
| `navigation` | `section` ∈ {collections, users} from `resolver_match.url_name`, for `aria-current` in the sidebar; every ARK view lights Collections |
| `environment` | `ark_base_url` (always one trailing `/`), `environment_label`, `environment_is_local`. Derived from `request.build_absolute_uri("/")` unless `ARK_PUBLIC_BASE_URL` is set; behind Apache the request already carries the public host and `https` via `X-Forwarded-Proto`. The sidebar badge exists so nobody pastes a `localhost` ARK into a catalogue record |

### HTMX and the CSP

`htmx.min.js` is vendored into `static/js/`. Four places use it: the ARK list (`hx-get` on filter change, sort headers and pager into `#results`, `hx-push-url`), the job page (`#status` polls itself every 2 s until finished and shows a `<progress>` bar from `jobs/progress.py`; filters, search and pager swap `outerHTML`), the results search form, and the ARK list's activity strip (`#activity` polls `collection_activity` every 3 s while a job is pending or running). `static/js/app.js` provides, by delegated listeners (so swapped markup keeps working): the mobile nav toggle (`data-nav-toggle`), copy-to-clipboard (`data-copy`), confirm-before-submit (`data-confirm`, because `onsubmit=` is dropped by the CSP) and the busy state (`data-busy`: on submit the button is disabled and relabelled and any `.busy` block in the form, holding an indeterminate `<progress>`, is revealed; used by the mint, bulk-bind upload, collection-create and add-user forms). `collection_form.js` shows the chosen template's description and capacity from `data-description`/`data-capacity` on the `<option>`s. Views detect a partial request with `request.headers.get("HX-Request")` and render the fragment template.

### View responsibilities (`admin_ui/views.py`)

| View | Key behaviour |
|---|---|
| `collection_list` | `current_stats` per collection (live or stored), oldest `as_of` shown as "Counts as of", running-job count |
| `collection_create` | form fields `name, prefix, naan, naa, template, term`; requires a prefix (model allows blank for legacy imports); duplicate `(naan, prefix)` message copied from legacy; long term requires NAA; `full_clean` validates the template |
| `collection_detail` | POST (Admin) saves **only** `name` and `naa`; shows the collection header (Overview tab), spec/capacity, stats, "Export all N as CSV", last 5 jobs under `#recent-jobs` |
| `collection_activity` | the activity strip alone: the pending/running job with its progress, else the latest job and what it did |
| `ark_list` | `_require_collection` first (redirect, or `HX-Redirect`, to Collections without one); `_search_from_request` (a `TooManyMatches` becomes a warning + empty list); subquery sorts refused above the threshold; `PAGE_SIZE 50`, `MAX_PAGE 1000`, fetch `PAGE_SIZE+1` to know `has_next`; count skipped when page 1 holds all; bindings and redirect totals loaded in two queries; `_remember_list` stores the query string in the session under `ark_list_query`; the full page adds `header` and `activity`, the htmx fragment does not; the result line offers "Export these N as CSV" |
| `ark_detail` | POST (Editor) `action=bind|unbind` with `name, value, qualifier`; after editing a variant, redirect back to `#variant-N` keeping `q`/`sort`; builds the variants table (`_variants`: counting order via `_variant_order`, first 4 elements shown, `+N more`, per-variant redirects, search over qualifier/name/value, sort by variant/elements/redirects); `_back_to_list` returns to the remembered list if it could have contained this ARK |
| `ark_purge` | POST, Admin: `unbind_elements(ark)` for every qualifier |
| `mint_view` | parses `count`; `mint()` runs inside the request (a capped mint is seconds; the form shows a busy state meanwhile); errors become messages; ids of the new ARKs cached under `last-minted:<session_key>` for 1 h (not in the session, which is re-saved every request) |
| `mint_template` | CSV of those ids ordered by sequence, 404 "Nothing was minted in this session." otherwise |
| `export` | `_require_collection` first; `counted(cap=EXPORT_SYNC_MAX_ROWS+1)`; above the limit, a warning naming the equivalent `export_arks` command and a redirect back; else `StreamingHttpResponse` of `export_rows`, filename sanitised |
| `bulk_bind` | `_upload_problem`: missing file, size > `BULK_BIND_MAX_BYTES`, not `.csv`; creates the job, `run_bulk_bind.delay`; if the broker is unreachable the job is marked failed with an explanation instead of a 500 |
| `job_detail` | unfinished jobs: `describe(read("bulkbind", pk))` from `jobs/progress.py` gives the `<progress>` value and label ("Waiting for a worker" while PENDING, indeterminate until a phase with a known total); finished jobs: `_job_results_page` reads the results **file** once, counts every filter (All, Errors, Minted, Bound, Unchanged, Not applied), keeps only the requested page; a job with failures opens on the Errors filter; search `q` ≤ 200 chars narrows counts too |
| `user_list` | POST `user=<id>`, `role=Admin|Editor|Viewer|none`; refuses your own row, a superuser's row and demoting the last Admin; `as_int` guards non-numeric ids; `_user_rows` gives the template `can_change`/`can_delete` per row |
| `user_create` | POST, superuser only: `username` (unique, case-insensitive), optional `email`/`first_name`/`last_name`, `password` + `password_confirm` through `validate_password`, `role` or `none`; errors re-render the page with the typed values |
| `user_delete` | POST, superuser only: refuses self, superusers and the last Admin; otherwise a hard delete (`Ark.minted_by` and `BulkBindJob.created_by` are `SET_NULL`) |

`as_int` rejects non-ASCII digits (`"²".isdigit()` is true but `int()` fails) so a crafted query string cannot 500.

### Fallback pages (`resolver/fallback.py`)

`FALLBACK_PAGES_DIR` (empty by default) names a directory of operator-written files. `arkservice/urls.py` sets `handler403/404/500` to this module: each serves `<status>.html` from the directory with the real status, or defers to `django.views.defaults`. `CSRF_FAILURE_VIEW` points at `csrf_failure` in the same module, because Django does not send CSRF failures through `handler403` and that failure is in practice the only public 403. `landing` serves `index.html` when present, with three placeholders (`{{organisation_name}}`, `{{organisation_website}}`, `{{naa_table}}`) filled by plain substitution of HTML-escaped values, empty if the database is unreachable; error pages get no substitution, and the 500 handler reads one file and nothing else. A signed-in request under `/admin/` that is refused renders `templates/admin_ui/403.html` inside the staff shell with the `require_role` message instead. Files are cached per name with their mtime for `CACHE_SECONDS` (60). Fallback responses carry `FALLBACK_CSP` (`style-src 'self' 'unsafe-inline'`, everything else as strict as before). `asset()` serves `/fallback/<name>` for bare filenames with an allow-listed extension that resolve inside the directory; the page files themselves are not assets. `active()` feeds the read-only card on the Users page (superusers), `preview()` serves a page with status 200 to superusers. The directory is server content outside every repository; the kit is `docs/fallback-example/`.

---

## 13. Bulk bind

### The CSV contract (`jobs/bulkbind.py`)

- Required column `Ark_ID` (case-insensitive, whitespace-stripped). Every other non-empty header is an element name, upper-cased.
- `Ark_ID` may carry a qualifier: `61220/utsc1/page1`, `61220/utsc1.image.png`.
- Empty cell = leave the existing value alone. To clear, use `purge_first`.
- Up to `BULK_BIND_MAX_ROWS` (100,000) rows and `BULK_BIND_MAX_BYTES` (50 MB).
- Decoded as `utf-8-sig`, then `cp1252`; anything else fails the whole job with a message.
- `apply_csv(..., progress=None)`: an optional `progress(phase, done, total)` callback is told where the work is (`reading` with no total, `checking` rows, `minting`, `purging`, `writing` bindings via `bulk_upsert_bindings`); the worker passes a throttled `jobs.progress.Reporter`, the CLI passes nothing.

### Validate everything, then write

```mermaid
flowchart TD
    A["apply_csv(collection, handle, mint_missing, purge_first, user)<br/>@transaction.atomic"] --> B["_read: DictReader; no Ark_ID column / empty / header-only / more than max rows → BulkBindError (whole file)"]
    B --> C["_lookup_arks: only the identifiers the file names, 2000 per IN-list"]
    C --> D{"for each row"}
    D --> E{"Ark_ID blank?"}
    E -->|"yes, mint_missing off"| R1["row error: No Ark_ID…"]
    E -->|"yes, mint_missing on"| R2["to_mint; provisional error 'Not minted: another row failed'"]
    E -->|no| F{"parse_ark_path ok?"}
    F -->|no| R3["row error: Not a valid ARK."]
    F -->|yes| G{"known in THIS collection?"}
    G -->|no| R4["row error: … is not an ARK in this collection. Mint it first."]
    G -->|yes| H["named.add((ark_pk, qualifier))<br/>for each non-empty cell: duplicate (ark, qualifier, ELEMENT) in file? → row error 'X is set twice'<br/>else planned[(ark_pk, qualifier, ELEMENT)] = value"]
    H --> D
    D -->|done| I{"to_mint and no other errors?"}
    I -->|yes| J["mint(count=len(to_mint), enforce_cap=False)<br/>rows become 'minted' with their new ARK; their cells planned"]
    I -->|no| K
    J --> K{"result.ok?"}
    K -->|no| L["transaction.set_rollback(True); return result<br/>(defence in depth: nothing was written yet anyway)"]
    K -->|yes| M{"purge_first?"}
    M -->|yes| N["_purge: delete bindings for exactly the (ark, qualifier) pairs named — even rows with all cells blank"]
    M -->|no| O
    N --> O["bulk_upsert_bindings(planned, outcomes=…) → created, updated<br/>outcomes[key] = created | replaced | unchanged"]
    O --> Q["_stamp: fold each row's outcomes back onto it<br/>bound / unchanged / minted + message"]
    Q --> P["return BulkBindResult(rows, created, updated, minted)"]
    L --> L2["valid rows keep status ok with message<br/>'Not applied: another row in the file failed.'"]
```

Row statuses, once the file is applied: `bound` (at least one element created or replaced, message such as `3 created, 1 replaced, 2 unchanged`, or `6 created (previous elements removed)` with `purge_first`), `unchanged` (`6 unchanged`, or `nothing to bind`), `minted` (`minted; 6 created`), `error` (the reason). On a file that failed as a whole the valid rows stay `ok` with the not-applied message. `result.ok` is "no error rows". The stamping happens after `_write`, so a row never claims a binding that was rolled back. The guarantee is the validation order, not the rollback; the `set_rollback` is there in case a future change writes earlier.

### Job lifecycle (`jobs/models.py`, `jobs/tasks.py`)

```mermaid
stateDiagram-v2
    [*] --> PENDING : upload creates BulkBindJob;\nrun_bulk_bind.delay(job.pk)
    PENDING --> FAILED : .delay() raised (broker down)\nmark_failed("Could not be queued…")
    PENDING --> RUNNING : claim(task_id)\nUPDATE … WHERE status='pending' (atomic; 1 row or 0)
    PENDING --> PENDING : reap_stale_jobs: PENDING > 15 min\n→ re-queue, at most once/hour (cache.add)
    RUNNING --> FINISHED : apply_csv + mark_finished(result)\nin ONE transaction; results CSV stored
    RUNNING --> FAILED : BulkBindError / Exception\nmark_failed(message)
    RUNNING --> FAILED : found RUNNING on redelivery\nor RUNNING > time limit + 300 s (reaper)\n→ mark_interrupted(): "Interrupted… Nothing was applied"
    FINISHED --> [*]
    FAILED --> [*]
    FINISHED --> deleted : prune_jobs(older_than_days)\nwith its files
    FAILED --> deleted
```

`run_bulk_bind` is `acks_late=True, reject_on_worker_lost=True`, so a killed worker's message is redelivered. It reports progress through a `jobs.progress.Reporter("bulkbind", job_id)`: one cache key `job-progress:bulkbind:<id>` holding `{phase, done, total}`, written on every phase change and end of phase and otherwise at most twice a second, lifetime one hour, deleted in a `finally` when the task ends. The cache rather than the row because the row's transaction is still open while the work runs; a cache that is down loses the bar, not the job. The conditional-UPDATE `claim` lets exactly one delivery run; a job seen RUNNING on redelivery committed nothing (apply and outcome share one transaction) and is failed with `INTERRUPTED_MESSAGE`; a job already FINISHED/FAILED is skipped. The file is read into a `StringIO` with no lingering references so each copy can be freed.

**Results file**: `job-<pk>-results.csv`, columns `row, ark_id, status, message` (statuses as above), values through `csv_safe`; `iter_results()` streams it back through `csv_unsafe`, and a missing file yields no rows (the page must still open). A FINISHED job with `failed > 0` wrote nothing.

**Upload discard** (`BulkBindJob.discard_upload()`): a claimed job never runs again, so its uploaded CSV is deleted as soon as the job ends: in `run_bulk_bind`'s `finally` (after the transaction, on every outcome), on the redelivered-while-RUNNING branch, and when `reap_stale_jobs` interrupts it. A PENDING job keeps its file (the reaper may re-queue it). A storage error is logged and leaves the name set, never changing the outcome. The worker reads the whole file into memory before applying, so nothing reads it afterwards.

**Retention** (`jobs/retention.py::prune_jobs`): finished/failed jobs older than N days (by `finished_at`, else `created_at`), their results file (and any upload still present) deleted through the storage; pending/running never touched; `dry_run` reports. Off unless `BULK_BIND_RETENTION_DAYS > 0`; also `manage.py prune_bulk_jobs --older-than N`.

---

## 14. Celery and scheduling

`arkservice/celery.py`: `Celery("arkservice")`, `config_from_object("django.conf:settings", namespace="CELERY")`, `autodiscover_tasks()`.

| Queue | Consumer | Tasks |
|---|---|---|
| `celery` (default) | `worker -Q celery --concurrency 2 --max-tasks-per-child 20 --max-memory-per-child 1000000` | `jobs.tasks.run_bulk_bind` |
| `periodic` | `worker -Q periodic --pool solo --concurrency 1 --beat` (run exactly one) | everything in `CELERY_BEAT_SCHEDULE`, routed by `CELERY_TASK_ROUTES` |

| Beat entry | Task | Interval |
|---|---|---|
| `flush-resolution-counters` | `flush_resolution_counters` → `core.counters.flush_counters()` | `RESOLUTION_FLUSH_SECONDS` (60) |
| `reap-stale-jobs` | `reap_stale_jobs` | 600 |
| `clear-expired-sessions` | `clear_expired_sessions` → `call_command("clearsessions")` | 86,400 |
| `prune-bulk-jobs` | `prune_bulk_jobs` (no-op when retention is 0) | 86,400 |
| `refresh-collection-stats` | `refresh_collection_stats` (every collection + element-name caches, lifetime 3×) | `COLLECTION_STATS_SECONDS` (300) |

`tests/test_schedule.py` fails if any scheduled task is not routed to `periodic`, does not exist, or if results are stored.

Settings: `CELERY_TASK_IGNORE_RESULT=True` (nothing reads results), `CELERY_WORKER_PREFETCH_MULTIPLIER=1` (a busy worker does not reserve the next long job), `CELERY_TASK_TIME_LIMIT=3600`, `visibility_timeout = time limit + 600` (the Redis transport must not redeliver a running job), `CELERY_BEAT_SCHEDULE_FILENAME=/tmp/celerybeat-schedule` (the systemd units make the working directory read-only; `PrivateTmp` makes `/tmp` writable), `CELERY_TASK_ALWAYS_EAGER` for a bare dev box with no broker (jobs run inline in the request; never in production).

---

## 15. Management commands

There is no HTTP API; commands are the scripting surface, run on the server. Exit 1 with a `CommandError` is the designed failure; a traceback is a defect.

**Two sources since 2026-11-07** (`INTENTS_cli_plugin.md`):
- **Core** (`core/management/commands/`) ships the **operator** commands every server needs for migration, cutover and maintenance: `export_arks`, `refresh_collection_stats`, `flush_counters`, `prune_bulk_jobs`, `import_legacy`, `resolve_diff`, `check_manifests`.
- **The optional `arks-cli` plugin** (sibling repo, Django app `arks_cli`) carries the **staff** commands, moved unchanged: `createcollection`, `mint`, `bind`, `unbind`, `bulk_bind`, `ark_stats`. It is enabled by `ARKS_PLUGINS=arks_cli` (`arkservice/plugins.py::plugin_apps`, which refuses a missing plugin at start-up).
- **What plugins may use** is versioned as `arkservice.plugins.PLUGIN_API` (1): the services, the models and `_common`. The plugin checks it in `AppConfig.ready()`.
- **The rows below** marked *(arks-cli)* exist only when the plugin is installed.

| Command | Arguments | Calls | Notes |
|---|---|---|---|
| `createcollection NAME --naan N --template T [--prefix P] [--naa A] [--term short\|medium\|long] [--redirect-elements URL,WHERE?] [--proxied-suffixes manifest] [--suffix-passthrough]` *(arks-cli)* | the three resolution settings, section 5 | `Collection.full_clean().save()` | prints prefix, firstpart, template (mask, gen type), capacity; `ValidationError`/`IntegrityError` → CommandError |
| `mint COLLECTION [COUNT=1] [--template FILE]` *(arks-cli)* | | `minting.minter.mint` | prints one ARK per line; writes the fill-in CSV; `MintError` → CommandError; cap enforced |
| `bind ARK ELEMENT VALUE` *(arks-cli)* | ARK may carry a qualifier | `bind_element` | |
| `unbind ARK [ELEMENT] [--all]` *(arks-cli)* | | `unbind_elements` | `--all` on a bare ARK clears every qualifier (same as UI purge); on a qualifier only that one |
| `bulk_bind COLLECTION CSV [--mint-missing] [--purge-first] [--results FILE]` *(arks-cli)* | | `jobs.bulkbind.apply_csv` | results CSV written either way; rows failed → CommandError "N row(s) failed; nothing was written" |
| `export_arks [--collection] [--text] [--element] [--value] [--bound\|--unbound] [--min-redirects] [--minted-after] [--minted-before] [--out]` | | `search_arks` (text mode **contains**), `export_rows` | stdout when no `--out`; bad date → CommandError |
| `ark_stats` *(arks-cli)* | | `collection_stats` | table per collection + top 10 element names |
| `refresh_collection_stats [COLLECTION]` | | `refresh_collection_stats` | all when omitted |
| `flush_counters` | | `core.counters.flush_counters` | |
| `prune_bulk_jobs --older-than DAYS [--dry-run]` | | `jobs.retention.prune_jobs` | `< 1` → CommandError |
| `import_legacy (--legacy-dump FILE \| --legacy-url URL) [--encoding] [--table T]* [--collection-name N] [--report CSV] [--dry-run]` | exactly one source | section 16 | |
| `resolve_diff --legacy-base URL --new-base URL [--collection] [--sample N] [--no-inflections] [--workers 8] [--timeout 20] [--out CSV] [--known CSV] [--stop-after N]` | | `core.verify` | section 16 |
| `check_manifests [--collection C] [--out CSV] [--sample N] [--workers 4]` | read-only; `--collection` restricts to one collection, `--sample` to the first N targets, `--out` writes every result, `--workers` is the number of concurrent fetches (keep it low against on-demand manifests) | `resolver.services.fetch_json` | fetches every explicitly bound proxied-suffix target (`/manifest` by default) exactly as the resolver would, same guards and limits, and reports what came back |

`_common.get_collection(reference)`: exact `name` first (case-sensitive on every engine, MySQL included); then `<naan>/<prefix>`; then `prefix` if exactly one collection has it, else "More than one collection uses the prefix… Name it as <naan>/<prefix>"; else "No collection with prefix or name … Known: …". `_common.get_ark(reference)` parses `ark:/<reference>` with `parse_ark_path` and returns `(ark, qualifier)` or "is not a valid ARK" / "No such ARK".

---

## 16. Legacy import and cutover verification

### `core/legacy.py`: two readers, one surface

| | `LegacyReader` | `DumpReader` |
|---|---|---|
| Source | live DB via `open_legacy(url)`: `sqlite://`, `mysql://`/`mariadb://` (MySQLdb), `postgres://` (psycopg); plain DB-API, never in `settings.DATABASES` | a `mysqldump`/phpMyAdmin `.sql` or `.sql.gz` via `open_legacy_dump(path, encoding)` |
| `collection_tables()` | every table except `system`/`user` | every `INSERT INTO` table seen whose columns include `_key, _value`, excluding `system`/`user` |
| `rows(table)` | `SELECT _key, _value`, `fetchmany(5000)` | streams the file line by line; `_FAST_ROW` regex for the common `('k','v')` row, a real scanner (`_scan_row`, MySQL escapes, `''`, values spanning lines) otherwise; `DumpFormatError` with the line number on garbage or a truncated file |
| `system_settings()` | the `system` table | collected during the first indexing pass |
| Both apply `normalise_row` | `decode_legacy_text` on key and value (exact inverse of `htmlspecialchars`, `&amp;` last), value `rstrip("\r")`; the **key keeps** its `\r` so the importer can see which spelling won |

Key grammar: `parse_legacy_key("61220/utsc1\t/page1\t.png\tURL")` → `("61220/utsc1", "/page1.png", "URL")` (middle parts joined). `is_reserved` = starts with `:`; `is_hold` = `:/h`; `is_circulation` = `:/c`; `parse_circulation("i|20201022094659|1603374419|1")` prefers the Unix timestamp in field 3, falls back to the 14-digit local stamp.

### `import_legacy` flow

```mermaid
flowchart TD
    A["open reader (dump or url)"] --> B["tables = collection_tables(); apply --table / --collection-name checks"]
    B --> C["transaction.atomic()"]
    C --> D["_import_organisation: system → Organisation"]
    D --> E{"for each table"}
    E --> F["pass 1: reserved rows → LegacyCollection.config"]
    F --> G["_upsert_collection: needs :/naan; prefix clash under same NAAN (other name) → CommandError;<br/>update_or_create by name"]
    G --> H["pass 2: stream element rows, _batched(IMPORT_CHUNK=20,000, key=ark) so one ARK's rows stay together"]
    H --> I["_create_missing_arks: skip REDIRECT-only keys; split 'naan/id' or fall back to the collection NAAN;<br/>sequence = xdig2n(identifier[prefix:], mask) or None; minted_at from :/c; bulk_create"]
    I --> J["_write_bindings: drop :/c; REDIRECT → counters dict (held back);<br/>duplicate (ark, qualifier, NAME): canonical spelling wins, loser → report 'duplicate-element';<br/>bulk_upsert_bindings"]
    J --> E
    E -->|done| K["_write_counters: match counters to ARKs now that the whole table is read;<br/>unknown ARK → report 'redirect-for-unknown-ark'; bulk create/update Resolution"]
    K --> L{"--dry-run?"}
    L -->|yes| M["transaction.set_rollback(True)"]
    L -->|no| N["commit"]
    M --> O["print totals; report file always written"]
    N --> O
```

Totals printed: collections created/updated, arks created, minted at recovered, bindings created/updated, elements merged, resolutions, redirects skipped. Idempotent: a second run changes only values that differ (`bulk_upsert_bindings`), never `minted_at`. Note it **does** overwrite a value a curator changed after the first import, so re-import only before cutover.

### `resolve_diff` and `core/verify.py`

```mermaid
flowchart LR
    A["iter_check_paths(collection, sample, inflections)<br/>/ark:/naan/ per NAAN · every ARK · ?, ??, ?info · every bound qualifier (once)"] --> B["ThreadPoolExecutor(workers) in batches of workers×8<br/>_fetch(legacy_base+path), _fetch(new_base+path): no redirects, 200 → body (64 KiB), 3xx → Location, error → (0, 'error: …')"]
    B --> C["compare(path, legacy, new, legacy_base)"]
    C --> D{"normalise"}
    D --> D1["legacy target: decode_legacy_text, rstrip CR"]
    D --> D2["legacy 302 to its own /404.php (relative or on its host) == new 404"]
    D --> D3["200 vs 200: compare SET of non-empty lines after dropping legacy's loader page (head/style/script) and stripping tags (legacy's <pre> wrapping, row order)<br/>with '_' read as a space (legacy displayed values that way; ours are verbatim)"]
    D --> D4["otherwise: same status and same target"]
    D1 --> E{"Difference?"}
    E -->|"is_error (status 0)"| F["counted separately: proves nothing"]
    E -->|"base_path in --known"| G["excused: the import reported this ARK"]
    E -->|real| H["printed, written to --out"]
    H --> I["exit 1: 'N of M paths differ. Do not flip the vhost yet.'"]
    F --> J["exit 1: 'could not be checked. Re-run'"]
    G --> K["exit 0: 'identically apart from N already reported'"]
```

Every fetch from legacy increments that ARK's `REDIRECT` counter there, which is why the export is taken before the diff. The default 8 workers can exhaust local ports when both services share a host.

---

## 17. Settings and configuration

`arkservice/settings.py` creates `environs.Env()`, calls `env.read_env(BASE_DIR / ".env", recurse=False)` (only this checkout's `.env`), then `check_production_settings(...)` unless `PYTEST_VERSION` or `ARKSERVICE_SKIP_CONFIG_CHECK` is set.

### Boot guard (`arkservice/checks.py`)

With `DJANGO_DEBUG=false`, refuse to start (one message listing every problem) when: `DJANGO_SECRET_KEY` is unset, equals `dev-insecure-key-change-me`, or is shorter than 32; `DATABASE_URL` is unset or starts with `sqlite`; `REDIS_URL` is unset. Without it an incomplete `.env` would serve 404 for every ARK from an empty SQLite file with a forgeable key.

### Settings by concern

| Concern | Variable | Default | Effect |
|---|---|---|---|
| Core | `DJANGO_DEBUG` | `false` | `true` relaxes the guard (when false, `DJANGO_SECRET_KEY`, a non-SQLite `DATABASE_URL` and `REDIS_URL` are all required), enables SQLite fallback and non-hashed static storage |
| | `DJANGO_SECRET_KEY` | dev placeholder | required in production |
| | `DJANGO_ALLOWED_HOSTS` | `localhost,127.0.0.1` | |
| | `DJANGO_CSRF_TRUSTED_ORIGINS` | empty | only when forms post from another hostname |
| | `DJANGO_TIME_ZONE` | `America/Toronto` | `USE_TZ=True` |
| | `DJANGO_LOG_LEVEL` | `INFO` | console handler to stderr |
| Database | `DATABASE_URL` | SQLite file | `mysql://` or `postgres://`; MySQL gets `charset=utf8mb4`, `init_command SET sql_mode='STRICT_TRANS_TABLES'` |
| | `DB_CONN_MAX_AGE` | 60 | seconds a connection is reused |
| | `DB_CONN_HEALTH_CHECKS` | `true` | ping a reused connection; avoids "server has gone away" across a network |
| | `DB_CONNECT_TIMEOUT` / `DB_READ_TIMEOUT` / `DB_WRITE_TIMEOUT` | 5 / 60 / 60 | MySQL only |
| Cache / counters | `REDIS_URL` | empty | `RedisCache` when set (socket timeouts = `CACHE_SOCKET_TIMEOUT`), else `LocMemCache` (10,000 entries); also the counter buffer. **Required in production** |
| | `CACHE_SOCKET_TIMEOUT` | 0.5 | connect and read timeout |
| | `RESOLUTION_FLUSH_SECONDS` | 60 | flush interval |
| | `COLLECTION_STATS_SECONDS` | 300 | stats + element-name refresh interval |
| Sign-in | `LOGIN_MAX_ATTEMPTS` / `LOGIN_LOCKOUT_SECONDS` | 5 / 900 | |
| | `TRUST_FORWARDED_FOR` | `false` | use last `X-Forwarded-For` entry; only behind a proxy that is the sole route to gunicorn |
| | `SESSION_COOKIE_AGE` | 28,800 | 8 h, `SESSION_SAVE_EVERY_REQUEST=True` |
| Security (DEBUG false) | `SESSION_COOKIE_SECURE` / `CSRF_COOKIE_SECURE` | `true` | the Docker dev stack sets both false |
| | `SECURE_HSTS_SECONDS` / `SECURE_HSTS_INCLUDE_SUBDOMAINS` | 0 / `false` | enable once TLS is proven |
| | (fixed) | | `SECURE_PROXY_SSL_HEADER=("HTTP_X_FORWARDED_PROTO","https")`, `SECURE_CONTENT_TYPE_NOSNIFF`, `X_FRAME_OPTIONS=DENY`, `SESSION_COOKIE_HTTPONLY`, SameSite Lax |
| Celery | `CELERY_BROKER_URL` | `redis://localhost:6379/0` | `redis://` or `rediss://` for Valkey or Redis alike |
| | `CELERY_RESULT_BACKEND` | = broker | unused (`task_ignore_result`) |
| | `CELERY_TASK_ALWAYS_EAGER` | `false` | dev only |
| | `CELERY_TASK_TIME_LIMIT` | 3600 | visibility timeout = +600 |
| | `CELERY_BEAT_SCHEDULE_FILENAME` | `/tmp/celerybeat-schedule` | |
| Resolver | `ARK_PUBLIC_BASE_URL` | empty | override the derived public base URL |
| | `MANIFEST_FETCH_TIMEOUT` / `MANIFEST_TOTAL_TIMEOUT` | 30 / 30 | per read / whole fetch (legacy: 30 s; on-demand manifests send nothing for 23–35 s while built); keep the total under gunicorn's 60 s |
| | `MANIFEST_MAX_BYTES` | 10 MiB | |
| | `MANIFEST_MAX_CONCURRENT` | 4 | per gunicorn process |
| Limits | `MINT_MAX_PER_REQUEST` | 10,000 | 0 removes the cap |
| | `BULK_BIND_MAX_ROWS` / `BULK_BIND_MAX_BYTES` | 100,000 / 50 MiB | |
| | `BULK_BIND_RETENTION_DAYS` | 0 | 0 keeps forever |
| | `DATA_UPLOAD_MAX_MEMORY_SIZE` / `FILE_UPLOAD_MAX_MEMORY_SIZE` | 20 MiB / 5 MiB | Django's own; the former does **not** cover file parts |
| | `SORT_SUBQUERY_MAX_ROWS` | 50,000 | |
| | `EXPORT_SYNC_MAX_ROWS` | 100,000 | |
| Files | `MEDIA_ROOT` | `./media` | results files, plus uploads until their job ends; `STATIC_ROOT=staticfiles/` via WhiteNoise `CompressedManifestStaticFilesStorage` when DEBUG is false |

---

## 18. Testing

```
tests/
├── fixtures/noid_vectors.json, generate_vectors.php   golden vectors from the legacy PHP
├── test_noid.py          conformance: alphabets, n2xdig ×1328, check_char, parse_template, make_id, xdig2n
├── test_minter.py        sequential/random/exhaustion/cap/pk read-back; concurrency (skips on SQLite)
├── test_arkpath.py       the URL grammar
├── test_resolver.py      every resolver path, headers, health, manifest with a monkeypatched fetch
├── test_manifest_fetch.py  SSRF guard, pinned address, size/time caps
├── test_manifest_hardening.py  /manifest made dependable: legacy-length timeouts, CORS header, on-demand targets
├── test_suffix_passthrough.py  the opt-in per-collection passthrough to the nearest bound ancestor (R6)
├── test_object_variants.py     utsc1.image.png read as ARK utsc1 + qualifier .image.png, everywhere
├── test_identifier_normalisation.py  hyphens and trailing ./ ignored as a fallback only (draft-kunze-ark-44 §3.2)
├── test_collection_resolution_settings.py  redirect_elements / proxied_suffixes: preview, confirm, audit
├── test_fallback.py      operator-supplied landing and error pages (FALLBACK_PAGES_DIR)
├── test_models.py        constraints; Resolution.record race (skips on SQLite)
├── test_services.py, test_search.py, test_scale_limits.py, test_counters.py
├── test_bulkbind.py, test_jobs.py, test_job_results_table.py, test_retention.py, test_schedule.py
├── test_row_outcomes.py  per-element created/replaced/unchanged folded back onto each row
├── test_progress.py      a running bulk bind's phase and counts, read from the cache
├── test_upload_discard.py  the upload is deleted as soon as its job can never run again
├── test_admin_ui_shell.py, test_ark_list_sorting.py, test_ark_detail_variants.py, test_ark_back_link.py,
│   test_collection_form.py, test_roles.py, test_security.py, test_workflow.py
├── test_collection_pages.py  one collection header with the ARK list, Mint and Bulk bind as tabs
├── test_busy_state.py    forms that take a moment say so while the browser waits
├── test_users.py         who may manage accounts; superusers and one's own row are untouchable
├── test_commands.py, test_legacy_dump.py, test_legacy_import.py, test_verify.py
├── test_command_helpers.py  core.management.commands._common, shared with the arks-cli plugin
├── test_plugins.py       ARKS_PLUGINS: the staff commands are gone from core, a missing plugin refuses to start
└── test_settings_db.py, test_settings_guards.py
```

- **Counts**: 3,817 collected from about 908 functions in 43 files as of 2026-11-07 (3,683 pass and 134 skip on SQLite; the vectors are parametrised). `CLAUDE.md`'s "~3,400 / ~550 functions" is an older figure.
- **`conftest.py`**: autouse `_clear_caches` (element names and stats are cached, so one test's data would answer another's lookup) and autouse `counter_redis`, which monkeypatches `core.counters._client` to return a fresh `fakeredis.FakeRedis` per test; a test simulates an outage by patching `_client` to raise.
- **Per-file fixtures**: `collection`, `ark`, `make_user(username, role, superuser)`, `viewer`/`editor`/`admin` (signed-in clients) are defined in each test module, not in `conftest.py`.
- **Skips on SQLite**: `test_concurrent_minters_never_produce_the_same_ark` and the counter-race test in `test_models.py` (SQLite serialises writes globally). A green SQLite run does not prove them; run MySQL at least once.
- **CSP enforcement**: `test_admin_ui_shell.py::test_no_admin_page_relies_on_inline_styles_or_handlers` renders every staff page and fails on any `style=` or `on*=` attribute.
- **Mutation-tested** (per `README_EXTENDED.md`): the check character, digit order, repertoire order, `WHERE?` fallback, suffix passthrough, metadata counting.

```bash
./.venv/bin/python -m pytest -q
./.venv/bin/python -m pytest tests/test_noid.py
DATABASE_URL=postgres://ark:ark@127.0.0.1:5432/ark ./.venv/bin/python -m pytest -q
DATABASE_URL=mysql://root:root@127.0.0.1:3306/ark   ./.venv/bin/python -m pytest -q
php tests/fixtures/generate_vectors.php > tests/fixtures/noid_vectors.json   # NOIDLIB=… to override
./.venv/bin/ruff check . && ./.venv/bin/ruff format --check .                 # E,F,I,UP,B,DJ,C4,SIM; line 100
```

---

## 19. Conventions and gotchas

- **Portability rules**: no JSON columns, no DB regex, no engine full-text, ORM only against this schema (raw SQL only in the read-only legacy reader), never rely on `bulk_create` returning PKs (MySQL does not). CI runs PostgreSQL and MySQL to enforce it.
- **New write paths go in `core/services.py`**, not in a view or a command.
- **Adding a top-level Django app** needs a `COPY --from=src <app>/ <app>/` line in `../docker-arks-service/Dockerfile`, or the container fails with `ModuleNotFoundError`.
- **No inline CSS or JS** in templates; the CSP and a test forbid it. Use `data-*` attributes and `static/js/app.js`.
- **Element names are upper-cased** on every path; search by name is case-insensitive because of it.
- **Identifiers are never reissued**: purge removes bindings, keeps the `Ark`; sequential minting never refills gaps.
- **No fallback up the hierarchy**: `/page9` with nothing bound is 404 even if the parent resolves, unless the collection turns on suffix passthrough (`Collection.suffix_passthrough`, off by default), which then redirects it to the nearest bound ancestor's URL + `/page9`.
- **Hyphens are tolerated on lookup, refused on write**: the resolver retries a miss without hyphens or a trailing `.`, and `core/services.py::qualifier_problem` / `prefix_problem` refuse `-` in a new qualifier (UI, `bind`, bulk bind) or a new collection's prefix, because N2T and arks.org strip hyphens before forwarding. Unbind and `import_legacy` are not checked.
- **Counts lag** by up to 60 s; stored collection stats lag by up to 300 s above 50,000 ARKs.
- **Bare `?` needs gunicorn** (`RAW_URI`) and Apache `nocanon`; `runserver` cannot be used for the cutover diff.
- **Export → upload round trip caveat**: `csv_safe` prefixes `'` to formula-leading values on export; `apply_csv` does not strip it, so re-uploading such a value stores `'=foo`. Only `iter_results` applies `csv_unsafe`.
- **`.rdedk` capacity** is 2,900 in code; `USAGES.md` was corrected on 2026-11-05.
- **Variant on a bare ARK** (`/ark:/61220/utsc1.image.png`) still *parses* the dot into the identifier; it resolves through the `object_variant()` reading after that lookup misses (section 6). So `resolve_diff` reports one as a difference from legacy, which 404s it.
- **Re-import after cutover** overwrites values curators changed since the export.
- **Bulk bind uploads live in `MEDIA_ROOT` until their job ends**, which in Docker is the `media` volume: `make rebuild` on an external-DB stack deletes queued jobs' files while their messages survive in Valkey, so they fail with a file-not-found.
- **`.env.example` ships `TRUST_FORWARDED_FOR=true`**, which is only safe behind a proxy that is the sole route to gunicorn.
- **Secrets**: `ARK_CORE.sql` (the legacy export) holds reversibly-encrypted staff passwords; never commit, paste or mount it.

---

## 20. Glossary

| Term | Meaning here |
|---|---|
| **ARK** | Archival Resource Key, `ark:/<NAAN>/<name>`; a persistent identifier that resolves by HTTP redirect |
| **NAAN** | Name Assigning Authority Number, e.g. `61220`; `Collection.naan`, `Ark.naan` |
| **NAA** | Name Assigning Authority, the organisation name returned for `/ark:/<naan>/`; `Collection.naa` |
| **prefix / shoulder** | The constant string after the NAAN that every ARK in a collection shares (`utsc`); `Collection.prefix`; unique within a NAAN |
| **identifier** | Everything after the NAAN including the prefix (`utsc1`); `Ark.identifier`; unique within a NAAN |
| **qualifier** | Everything after the identifier: hierarchy and/or variant, stored as one string (`/page1.image.png`); `Binding.qualifier` |
| **hierarchy** | The `/segment…` part of a qualifier, a sub-object such as a page |
| **variant** | The `.suffix` part of a qualifier, an alternate form such as `.image.png` |
| **inflection** | A trailing `?`, `??` or `?info` asking for metadata instead of a redirect |
| **ERC** | Electronic Resource Citation, the `erc:` / `erc-support:` key-value text block the inflections return |
| **element / binding** | A named value attached to an ARK under a qualifier: `Binding(name, value)`; any name is allowed |
| **URL / WHERE?** | The two element names the resolver redirects to, in that order |
| **noid** | "Nice Opaque Identifier", Kunze's minter; its template language and algorithms are ported in `minting/noid.py` |
| **template / mask** | `.zd`: `z` order plus `d` repertoire; the prefix plus template is the "full template" noid parses |
| **repertoire / alphabet** | The character set a mask letter draws from; `e` is the 29 extended digits without vowels |
| **check character** | A trailing character computed from the whole ARK (`k` in the mask) so a mistyped ARK fails validation |
| **sequence** | The counter value an identifier was generated from; `Ark.sequence`; `xdig2n` recovers it |
| **collection** | A minter: one NAAN, prefix, template; `Collection` |
| **resolution** | One counted redirect; `Resolution(ark, qualifier, count)` |
| **mint** | Create new identifiers; they do not resolve until something is bound |
| **purge** | Remove every element from an ARK (and its qualifiers), keeping the identifier |
| **bulk bind** | Upload a CSV with an `Ark_ID` column and one column per element |
| **periodic queue** | The Celery queue for scheduled housekeeping, consumed by the scheduler with beat |
| **write-through** | Counting a hit directly in MySQL when the Valkey buffer is unavailable |
