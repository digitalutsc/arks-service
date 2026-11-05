# ARK Service — architecture

How the system is put together, why it is shaped this way, and what happens on
each path through it.

- Deployment: [DEPLOY.md](DEPLOY.md)
- Day-to-day use: [USAGES.md](USAGES.md)
- Quick start: [README.md](README.md)

---

## Contents

- [What this replaces](#what-this-replaces)
- [Production infrastructure](#production-infrastructure)
- [Components](#components)
- [Data model](#data-model)
- [Request paths](#request-paths)
- [Minting](#minting)
- [Bulk bind](#bulk-bind)
- [Migration and cutover](#migration-and-cutover)
- [Security model](#security-model)
- [Portability](#portability)
- [Testing strategy](#testing-strategy)
- [Design decisions and their reasons](#design-decisions-and-their-reasons)

---

## What this replaces

The legacy service is a PHP application: a ~1,900-line single-file admin
(`admin/admin.php`), a flat `rest.php` endpoint, and a public resolver
(`resolver.php`) over a vendored fork of Noid4Php. Every collection is a MySQL
table of tab-separated `_key`/`_value` pairs.

```mermaid
flowchart TB
    subgraph LEGACY["Legacy (PHP)"]
        direction TB
        L1["resolver.php<br/><i>own mysqli queries</i>"]
        L2["admin/admin.php<br/><i>1,900 lines, HTTP Digest</i>"]
        L3["admin/rest.php<br/><i>flat op= switch</i>"]
        L4[("Per-collection tables<br/><code>_key</code> / <code>_value</code><br/>tab-separated keys")]
        L1 --> L4
        L2 --> L4
        L3 --> L4
    end

    subgraph NEW["This system (Django)"]
        direction TB
        N1["resolver/<br/><i>the only public surface</i>"]
        N2["admin_ui/<br/><i>templates + HTMX, 3 roles</i>"]
        N3["management commands<br/><i>no HTTP API</i>"]
        N4["core/services.py<br/><i>shared by UI and CLI</i>"]
        N5[("collections / arks<br/>bindings / resolutions")]
        N1 --> N5
        N2 --> N4
        N3 --> N4
        N4 --> N5
    end

    LEGACY -.->|"import_legacy<br/>then resolve_diff"| NEW
```

What carried over unchanged: identifier *format*, and the entire resolver
contract. ~100,000 ARKs are in circulation and must keep resolving byte for
byte.

What did not: Perl's `rand()` emulation, the `:/…` counter rows, HTTP Digest
auth with reversibly-encrypted passwords, the browser-driven row-at-a-time bulk
bind, and the REST endpoint.

---

## Production infrastructure

```mermaid
flowchart TB
    subgraph WORLD["Internet"]
        U["Researchers, crawlers,<br/>citations in papers"]
        S["Staff browsers"]
    end

    subgraph VM["UTSC LAMP VM"]
        AP["<b>Apache</b> :443<br/>TLS · <code>nocanon</code><br/>serves /static/"]

        subgraph SYSTEMD["systemd units"]
            GU["<b>arkservice</b><br/>gunicorn 127.0.0.1:8000<br/>3 workers"]
            CW["<b>arkservice-worker</b><br/>celery, queue celery<br/>bulk binds"]
            CB["<b>arkservice-beat</b><br/>celery beat + queue periodic<br/>counter flush, reaper"]
        end

        RD[("Valkey or Redis<br/>broker + cache")]
        DB[("MySQL / MariaDB<br/><i>the only durable state</i>")]
        MED[("MEDIA_ROOT<br/>uploaded CSVs<br/>+ results")]
    end

    U -->|"GET /ark:/61220/utsc1"| AP
    S -->|"GET /admin/"| AP
    AP -->|"proxy, RAW_URI preserved"| GU
    GU --> DB
    GU -->|"enqueue bulk bind,<br/>count hits"| RD
    RD --> CW
    RD --> CB
    CW --> DB
    CB -->|"flush counts"| DB
    GU --> MED
    CW --> MED
```

**Why `nocanon` matters.** A trailing bare `?` on an ARK is an inflection —
"show me the metadata" — not an empty query string. Django never sees it: it
does not reach `QUERY_STRING`. The resolver therefore reads the original request
line from gunicorn's `RAW_URI`, and Apache must not re-canonicalise the URI on
the way through. Without `nocanon`, metadata requests silently become redirects.

**Docker** replaces Apache with WhiteNoise inside gunicorn. For development it
also brings its own PostgreSQL (or MySQL) container; for production,
`docker-compose.external-db.yml` points it at an existing MySQL server and the
`db` container is not started. The `broker` service runs Valkey by default,
or Redis with `BROKER_IMAGE=redis:7-alpine`, and requires a password; in
production `docker-compose.external-broker.yml` can replace it with an
existing Valkey or Redis server, logged in to with a user name and password. The stack is defined in the `docker-arks-service`
repository beside this one, not here. The development shape:

```mermaid
flowchart LR
    B["Browser :8000"] --> W["web<br/>gunicorn + WhiteNoise"]
    W --> P[("db<br/>PostgreSQL 16")]
    W --> R[("broker<br/>Valkey, or Redis")]
    R --> K["worker<br/>celery"]
    K --> P
    W -.-> V[("media volume")]
    K -.-> V
```

---

## Components

```
arkservice/     settings, URLs, WSGI, Celery app, boot guards
core/           models, ARK path parsing, search/export, shared services,
                legacy reader, cutover verification, management commands
minting/        the noid port (pure) and the minter (stateful)
resolver/       the public /ark:… endpoint and the landing page
admin_ui/       staff interface: views, roles, templates
jobs/           bulk-bind uploads: model, Celery task, CSV application
```

```mermaid
flowchart TD
    RV["resolver/views.py"] --> AP["core/arkpath.py<br/><i>parse the URL</i>"]
    RV --> RS["resolver/services.py<br/><i>ERC rendering, manifest fetch</i>"]
    RV --> M["core/models.py"]

    AU["admin_ui/views.py"] --> RO["admin_ui/roles.py"]
    AU --> SV["core/services.py"]
    AU --> SE["core/search.py"]
    AU --> MI["minting/minter.py"]
    AU --> JB["jobs/models.py + tasks.py"]

    CMD["management commands"] --> SV
    CMD --> SE
    CMD --> MI
    CMD --> LG["core/legacy.py"]
    CMD --> VF["core/verify.py"]

    JB --> BB["jobs/bulkbind.py"]
    BB --> SV
    BB --> MI
    MI --> NO["minting/noid.py<br/><i>pure algorithms</i>"]
    SV --> M
    SE --> M
    BB --> AP

    style NO fill:#eef7f1
    style SV fill:#eaf1f8
```

Two things to notice:

- **`core/services.py` sits between both front ends and the models.** The admin
  UI and the management commands call the same functions, so they cannot drift.
  An earlier version had them written twice and they had already diverged over
  whether a rebind touched `updated_at`.
- **`minting/noid.py` is pure.** No database, no Django. That is what lets it be
  pinned to the legacy PHP by ~1,450 golden vectors.

---

## Data model

Legacy packed everything into one string key per row:

```
61220/utsc1<TAB>URL                        the object's target
61220/utsc1<TAB>/page1<TAB>URL             a part's target
61220/utsc1<TAB>/page1<TAB>.png<TAB>URL    a variant of a part
:/naa, :/naan, :/template, :/prefix        collection configuration
61220/utsc1<TAB>REDIRECT                   hit counter
```

Normalised:

```mermaid
erDiagram
    COLLECTION ||--o{ ARK : mints
    ARK ||--o{ BINDING : "has elements"
    ARK ||--o{ RESOLUTION : "counted by"
    USER ||--o{ ARK : minted_by

    COLLECTION {
        string name UK
        string prefix UK "unique within its NAAN"
        string naan
        text   naa "returned for /ark:/<naan>/"
        string template "noid, e.g. .zd"
        string term
    }
    ARK {
        string naan "UK with identifier"
        string identifier "includes the prefix"
        bigint sequence "counter that produced it"
        datetime minted_at
    }
    BINDING {
        string qualifier "'' | /page1 | .png | /page1.png"
        string name "UK with ark+qualifier"
        text   value "unbounded"
        datetime updated_at
    }
    RESOLUTION {
        string qualifier
        bigint count
        datetime last_at
    }
```

**Any element name may be bound.** `URL`, `WHERE?`, `PID`, `LOCAL_ID` and
`COLLECTION` are conventions the resolver and reports look for — not schema.
A collection can invent `PHOTOGRAPHER` and it is searchable like anything else.

**Two constraints the legacy system lacked:**

| Constraint | Guarantees |
|---|---|
| `unique (naan, identifier)` | an ARK identifies exactly one thing |
| `unique (ark, qualifier, name)` | an element cannot silently exist twice |

**Qualifiers are one normalised string.** Legacy stored hierarchy and variant as
separate tab components; here `/page1` + `.image.png` is stored as
`/page1.image.png` and split at the first dot after the last slash. The round
trip is exact.

**Uploads** are tracked so staff can close the tab and come back:

```mermaid
erDiagram
    COLLECTION ||--o{ BULKBINDJOB : "uploads into"
    USER ||--o{ BULKBINDJOB : created_by
    BULKBINDJOB {
        file   upload
        file   results "per-row outcome CSV"
        bool   mint_missing
        bool   purge_first
        string status "pending|running|finished|failed"
        int    created
        int    updated
        int    minted
        int    failed
        text   error
    }
```

---

## Request paths

### Resolution

```mermaid
flowchart TD
    A["/ark:… request"] --> B["raw_request_uri()<br/><i>RAW_URI keeps a bare '?'</i>"]
    B --> C["parse_ark_path()<br/><i>split, then percent-decode<br/>per component</i>"]
    C --> D{"NAAN only?"}
    D -->|yes| E["200 · the NAA"]
    D -->|no| F{"ARK exists?"}
    F -->|no| G["404"]
    F -->|yes| H{"inflection<br/>? ?? ?info"}
    H -->|yes| I["200 · erc: block<br/><i>no counter increment</i>"]
    H -->|no| J{"/manifest?"}
    J -->|yes| K["check target is public http(s)<br/>fetch (10 s total, 10 MB, 4 at once)<br/>return JSON as received<br/>502/503/504 if refused, busy or slow"]
    J -->|no| L{"URL bound at<br/>this exact qualifier?"}
    L -->|no| M{"WHERE? bound?"}
    M -->|no| N["404<br/><i>no fallback up the hierarchy</i>"]
    M -->|yes| O["count (Valkey, else MySQL) · 302"]
    L -->|yes| O

    style E fill:#eef7f1
    style I fill:#eef7f1
    style O fill:#eef7f1
    style G fill:#fdeeee
    style N fill:#fdeeee
```

Order matters in two places, both to match legacy:

- **Inflection is checked before `/manifest`.** Legacy only treated a URI as a
  manifest request when it *ended* in `/manifest`, so a trailing `?` took it down
  the metadata path.
- **Decoding happens after splitting** on `/` and `?`, so `%2F` stays inside one
  path component and `%3F` is data rather than an inflection marker.

### Staff interface

```mermaid
flowchart LR
    R["request"] --> A{"authenticated?"}
    A -->|no| L["302 → /admin/login/"]
    A -->|yes| RL{"role ≥ required?"}
    RL -->|no| F["403<br/><i>not a login redirect —<br/>they already signed in</i>"]
    RL -->|yes| V["view"]
    V --> S["core/services.py"]
    S --> DB[("database")]
```

Roles are Django groups. `@require_role(VIEWER|EDITOR|ADMIN)` guards each view,
and POST handlers inside a Viewer-readable view re-check before writing — so
posting straight to a URL is refused, not just hidden from the menu.

---

## Minting

The legacy minter kept its position in a `:/oacounter` row and, for random
templates, replayed Perl's `rand()` so the *n*-th identifier was reproducible
even after a rebuild. None of that survived.

```mermaid
flowchart TD
    A["mint(collection, count)"] --> B{"count within<br/>MINT_MAX_PER_REQUEST?"}
    B -->|no| X["ValueError"]
    B -->|yes| C["SELECT … FOR UPDATE<br/>on the collection row"]
    C --> D{"template order"}
    D -->|sequential| E["highest recorded<br/>sequence + 1"]
    D -->|random| F{"space > half full?"}
    F -->|no| G["CSPRNG draw,<br/>retry on collision"]
    F -->|yes| H["enumerate what is free,<br/>pick from that"]
    E --> I["n2xdig(n, mask)<br/>+ firstpart<br/>+ check character"]
    G --> I
    H --> I
    I --> J["bulk_create"]
    J --> K{"driver returned<br/>primary keys?"}
    K -->|no, MySQL| L["read them back"]
    K -->|yes| M["done"]
    L --> M

    style C fill:#eaf1f8
    style L fill:#fdf5e6
```

**The lock is the point.** Ordering moved out of Perl's PRNG and into the
database: `select_for_update` serialises minters, and `unique (naan, identifier)`
is the backstop. Eight threads minting simultaneously produce no duplicate —
that is a test, and it fails on PostgreSQL if the lock is removed.

**MySQL cannot return keys from a multi-row insert.** MySQL is the production
engine, so `mint()` reads the rows back when the driver leaves `pk` unset.
Anything that mints and immediately uses the new rows depends on this.

**Identifiers stay legacy-shaped.** `n2xdig`, the character repertoires, template
parsing and the check character are ported exactly and pinned by golden vectors
generated from the legacy PHP.

---

## Bulk bind

```mermaid
sequenceDiagram
    autonumber
    actor Staff
    participant UI as admin_ui
    participant DB as database
    participant Q as Redis or Valkey
    participant W as Celery worker

    Staff->>UI: upload CSV
    UI->>DB: BulkBindJob(status=pending)
    UI->>Q: run_bulk_bind(job_id)
    UI-->>Staff: 302 → job page (polls itself)

    W->>Q: consume
    W->>DB: status=running
    Note over W: decode UTF-8, else CP1252
    Note over W: validate EVERY row first
    alt any row invalid
        W->>DB: status=finished, failed=N,<br/>nothing written
        Staff->>UI: download per-row results
    else all rows valid
        opt purge_first
            W->>DB: delete exactly the<br/>(ark, qualifier) pairs named
        end
        opt mint_missing
            W->>DB: mint blank rows
        end
        W->>DB: bulk_upsert_bindings()
        W->>DB: status=finished, counts
    end
```

**Validate-then-write is the guarantee**, not a rollback afterwards. Every row is
checked before anything is written, so a bad row cannot leave a collection
half-updated the way the legacy row-at-a-time upload could — and the operator
gets *every* problem in one results file rather than stopping at the first.

The task is `acks_late`, so a job survives the worker being killed; that means
Celery can deliver it twice, so a job that is no longer `pending` is skipped
rather than minting a second batch.

---

## Migration and cutover

```mermaid
flowchart TD
    A["Freeze writes on legacy"] --> B["export the database<br/><i>mysqldump or phpMyAdmin</i>"]
    B --> C["import_legacy --dry-run"]
    C --> D["import_legacy"]
    D --> E["ark_stats<br/><i>do the counts look right?</i>"]
    E --> F["resolve_diff --sample 500"]
    F --> G{"clean?"}
    G -->|no| H["investigate, fix, re-import"]
    H --> D
    G -->|yes| I["resolve_diff over everything<br/><i>every ARK, qualifier, inflection</i>"]
    I --> J{"clean?"}
    J -->|no| H
    J -->|yes| K["flip the Apache vhost"]
    K --> L["verify in the open"]
    L --> M{"trouble?"}
    M -->|yes| N["re-enable the old site<br/><i>legacy DB never written to</i>"]
    M -->|no| O["done"]

    style G fill:#fdf5e6
    style J fill:#fdf5e6
    style O fill:#eef7f1
    style N fill:#fdeeee
```

**`import_legacy`** reads the export file directly — the handover is a `.sql`
file, and requiring it to be restored into a scratch MySQL server first was an
obstacle with no purpose. Keys are read literally rather than re-derived, so
whatever production actually holds survives, including anything legacy wrote in
a form its own resolver could not read back. Identifiers are decoded back to
their counter value, which is what lets minting resume exactly where production
left off. It is idempotent and bulk-written: the real production export, 97,596
ARKs and 2.76M bindings, takes about a minute, and a second run creates nothing.

Three things about the legacy data are not taken literally, each because taking
it literally would be wrong rather than faithful:

| Legacy held | Why it cannot come across as-is |
|---|---|
| every value HTML-escaped (`&amp;` for `&`) | an artefact of the PHP storage layer, not something a curator typed. Decoded once on the way in, and `resolve_diff` decodes legacy's answers the same way so the gate stays meaningful |
| an identifier's mint date only in its `:/c` circulation record | dropping it dated every migrated ARK to the day of the migration. Read back, giving real dates from 2020 to 2026 |
| thousands of elements under two spellings, one ending in a carriage return | only one can survive a `(ark, qualifier, name)` unique constraint. The clean spelling wins and the other is written to a review CSV rather than lost silently |

An identifier is imported if it has a circulation record **or** any element that
is not a redirect count. That brings across the 19,947 identifiers production
minted and never bound — without them, minting would eventually reissue them —
and leaves out the paths the legacy resolver counted hits for but which were
never ARKs. Full detail in [MIGRATION.md](MIGRATION.md).

**`resolve_diff`** is the gate. It walks every NAAN root, every ARK, every
qualifier anything is bound under, and the `?`, `??` and `?info` inflections,
fetching each from both systems without following redirects.

Legacy and this system say the same thing in different words, so differences of
*expression* are normalised away before comparison:

| Legacy says | This system says | Treated as |
|---|---|---|
| `302 → https://<legacy-host>/404.php` | `404` | the same |
| `<pre><pre>\nerc:\nUrl: …\n</pre><pre/>` | `erc:\nUrl: …` | the same, compared line-wise |
| a different redirect target | | **a difference** |
| a metadata line that is missing or changed | | **a difference** |

A path that could not be fetched is reported **separately** from a real
difference — a socket failure proves nothing either way — and still fails the
run, because an unchecked path is not a passed one.

Rehearsed against a stand-in legacy service over 2,000 ARKs with their
qualifiers, variants and all three inflections: 8,343 of 8,343 identical, and
still failing when a single binding value is changed.

---

## Security model

| Concern | How it is handled |
|---|---|
| Authentication | Django sessions, hashed passwords. Legacy used HTTP Digest with reversibly-encrypted passwords; those accounts are not migrated |
| Authorisation | Three roles as Django groups, enforced per view *and* per POST. No role = can do nothing |
| SQL injection | ORM only. The one raw-SQL area is the legacy reader, which is read-only and quotes table names through a vendor-aware allowlist |
| XSS | Django autoescaping; no `\|safe` anywhere. The purge confirmation passes the ARK through a `data-` attribute rather than interpolating it into a JS string |
| CSRF | Django middleware; tokens on all POST forms |
| SSRF | `/manifest` is the only server-side fetch. `http`/`https` only; private, loopback, link-local, reserved and multicast addresses refused; redirects refused; oversized bodies rejected rather than silently truncated |
| Misconfiguration | Boot guards refuse to start without a real `SECRET_KEY` and `DATABASE_URL` when `DEBUG` is false |
| Transport | Apache terminates TLS; secure cookies and `SECURE_PROXY_SSL_HEADER` when `DEBUG` is false; HSTS available, off until TLS is proven |

The public surface is exactly one view. Everything else is behind a login.

---

## Portability

PostgreSQL and MySQL/MariaDB are both first-class: production runs MySQL,
development and Docker run PostgreSQL, CI runs both on every push.

Rules that keep it that way:

- no JSON columns;
- no database regular expressions;
- no engine-specific full-text search;
- ORM only, no raw SQL against this schema;
- no reliance on `bulk_create` returning primary keys.

**Free-text search is therefore a `LIKE` scan.** `value` is unbounded `TEXT`,
which MySQL cannot index without a prefix length, so `bindings` is indexed on
`name` and values are scanned. Measured over 418k bindings: about 0.25 s. An
engine-specific index can be added later without a schema change.

SQLite is supported for local development only, and **some tests skip on it** —
concurrent minting and the resolution-counter race need real row locking.

---

## Testing strategy

Roughly 2,900 tests. Three ideas do most of the work.

**1. Conformance vectors.** `tests/fixtures/generate_vectors.php` runs the
*legacy PHP* and dumps ~1,450 expected values for template parsing, base
conversion, check characters and end-to-end identifier construction. The Python
port is tested against those, so "identical to legacy" is measured, not claimed.
CI regenerates them and fails if the fixture has drifted.

**2. Mutation testing on the parts that matter.** After a suite went green it was
deliberately broken to confirm the tests notice: an off-by-one in the check
character, reversed digit order, the wrong repertoire search order, a dropped
`WHERE?` fallback, an added ancestor fallback, counting metadata as a redirect.
Each failed exactly the tests it should. One such check found that a
`set_rollback` call was *not* what provided bulk bind's atomicity — validation
order was — and the code now says so.

**3. Real engines, real concurrency.** The claims that matter are proved rather
than asserted: eight threads minting produce no duplicate (fails on PostgreSQL
without the lock), eight first-time resolutions of one ARK do not collide, and
the whole suite runs on PostgreSQL and MySQL as well as SQLite. A MySQL-only bug
— `mint()` returning rows with no primary key — was caught exactly this way.

```bash
./.venv/bin/python -m pytest -q                  # everything
./.venv/bin/python -m pytest tests/test_noid.py  # conformance only
DATABASE_URL=mysql://root:root@127.0.0.1:3306/ark ./.venv/bin/python -m pytest -q
```

---

## Design decisions and their reasons

| Decision | Reason |
|---|---|
| **No HTTP API** | The admin UI talks to the ORM; scripts use management commands on the host. One less authenticated surface, and no second implementation to keep in step |
| **Ported the noid format, not the generator** | The format is what 100k circulating ARKs depend on. Perl's `rand()` emulation only decided *ordering*, which nobody observes — dropping it removed the riskiest part of the port |
| **Database decides the next identifier** | `select_for_update` plus a unique constraint makes duplicates impossible rather than unlikely. The legacy system had no such guarantee |
| **Any element name may be bound** | The strongest feature of the legacy system was that a collection could bind anything. Modelling elements as rows keeps it, and makes them searchable |
| **One normalised `qualifier` string** | Legacy's two tab components round-trip exactly into one field, which is far easier to index, query and reason about |
| **Validate the whole upload first** | The legacy browser-driven upload stopped wherever it failed, leaving a half-updated collection and no record of where |
| **Read legacy keys literally on import** | Re-deriving them would reproduce legacy's own bugs, or silently drop what it wrote incorrectly. `resolve_diff` then proves the result |
| **Values emitted verbatim in metadata** | Legacy replaced underscores with spaces, corrupting any URL containing one |
| **Bulk everything** | Row-at-a-time `update_or_create` costs two queries per element: 7m13s for a production-scale import, against 11s in bulk |
| **Portable SQL subset** | Production is MySQL and dev is PostgreSQL; CI on both is what actually enforces it |
| **Roles, not one superuser** | Legacy had a single all-powerful account. Most staff work is minting and binding, which does not need to imply dropping collections |
| **ARKs are never reissued** | Purging removes elements and keeps the identifier, so an ARK can never come to mean something else |
