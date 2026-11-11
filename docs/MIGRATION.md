# Migrating from the legacy service

Everything already in circulation moves across: ~97,600 identifiers, their
metadata, their redirect counts and the dates they were minted. Nothing is ever
written back to legacy, so the migration can be rehearsed as often as you like
and rolled back by putting the old vhost back.

- **Rehearsing it in Docker:** [`MIGRATION.md` in `docker-arks-service`](https://github.com/digitalutsc/docker-arks-service/blob/main/docs/MIGRATION.md)
- **The rest of the cutover** (vhost, systemd, rollback): [DEPLOY.md](DEPLOY.md#cutover-from-the-legacy-service)
- **Production in Docker:** the commands below are written for a bare install
  (`.venv/bin/python manage.py …`). When production runs the
  `docker-arks-service` stack against its external MySQL server, run the same
  commands from that repository as `make manage ARGS="…"`, and the import as
  `make import-dump DUMP=… ARGS="--dry-run"`, which copies the export into the
  container and removes it again.

## Contents

- [What legacy stored](#what-legacy-stored)
- [How it maps onto this system](#how-it-maps-onto-this-system)
- [The rules the importer applies](#the-rules-the-importer-applies)
- [Getting the export](#getting-the-export)
- [The runbook](#the-runbook)
- [Reading the review report](#reading-the-review-report)
- [What the production export looked like](#what-the-production-export-looked-like)
- [Troubleshooting](#troubleshooting)
- [After cutover](#after-cutover)

---

## What legacy stored

One MySQL table per collection, each a generic key/value store. All the meaning
is in the shape of the key, whose parts are separated by literal tab characters.

| Key | Holds |
|---|---|
| `:/naan`, `:/prefix`, `:/template`, `:/naa`, `:/longterm` … | the minter's configuration, 27 rows in all |
| `61220/utsc1<TAB>URL` | an element bound to the ARK itself |
| `61220/utsc1<TAB>/page1<TAB>URL` | an element on a hierarchical part |
| `61220/utsc1<TAB>/page1<TAB>.png<TAB>URL` | ... and on a variant of that part |
| `61220/utsc1<TAB>REDIRECT` | how many times the resolver sent someone there |
| `61220/utsc1<TAB>:/c` | the circulation record: `i\|20201022094659\|1603374419\|2` |
| `61220/utsc1<TAB>:/h` | a hold. Every identifier in a long-term minter has one |

Two more tables: `system` (organisation name and website) and `user` (staff
accounts). Anything not called `system` or `user` is a collection.

Two properties of the storage layer matter more than they look:

- **Everything was HTML-escaped on the way in.** The PHP layer put every key and
  value through `htmlspecialchars`, so an ampersand is stored as `&amp;` and an
  apostrophe as `&#039;`. Legacy then served that back as it stood, which is why
  its own redirects pointed at URLs containing `&amp;`.
- **An identifier exists whether or not anything is bound to it.** A fifth of
  production was minted and never given a URL. The `:/c` record is the only
  evidence those identifiers were ever issued.

## How it maps onto this system

| Legacy | Here |
|---|---|
| the collection table | one `Collection`, named after the table unless `--collection-name` says otherwise |
| `:/naan`, `:/prefix`, `:/template`, `:/naa` | its NAAN, prefix, template and name-assigning authority |
| `:/longterm` / `:/wrap` | not used: every imported collection is long-term |
| every distinct identifier | one `Ark`, with `sequence` decoded back from the identifier and `minted_at` from `:/c` |
| every element row | one `Binding` — `ark`, `qualifier`, `name`, `value` |
| the hierarchy and variant tab parts | joined into the single `qualifier` string, e.g. `/page1.image.png` |
| `REDIRECT` | one `Resolution` per (ARK, qualifier) |
| the `system` table | the `Organisation` singleton |
| `:/h`, `:/oacounter`, `:/saclist`, `:/c<n>/…`, `:/erc`, `:/q/…` | **dropped** |
| the `user` table | **not migrated** |

The counters go because minting no longer keeps a position: the next identifier
is decided against the database, and a unique constraint makes a duplicate
impossible rather than merely unlikely. Decoding each identifier back to its
counter value is what lets minting resume exactly where legacy left off.

Staff accounts go because legacy stored passwords reversibly encrypted, with the
key in the source. Create accounts fresh with `createsuperuser`.

## The rules the importer applies

**Keys are read literally, never re-derived.** Whatever production actually
holds survives the move, including anything legacy wrote in a form its own
resolver could not read back.

**An identifier is imported if it has a circulation record or any element that
is not a redirect count.** So minted-but-unbound identifiers come across, and
the paths the legacy resolver counted hits for but which were never ARKs — a
crawler asking for `/ark:/61220/utsc35657biblio` — do not. Those redirect rows
are reported rather than dropped silently.

**Redirect counts are matched up after the whole table has been read**, so a
count that appears before the row proving its ARK exists is never lost.

**Entities are decoded once.** `&amp;` becomes `&`; something stored as
`&amp;lt;` — a curator who really typed `&lt;` — comes back as `&lt;`.
`resolve_diff` decodes legacy's answers the same way before comparing, so this
does not show up as thousands of differences at the gate.

**An element held under two spellings keeps the canonical one.** Uploads saved
with Windows line endings left thousands of element names ending in a carriage
return, and 2,743 of those sit beside a clean twin holding a *different* value.
Only one can survive a `(ark, qualifier, name)` unique constraint. The clean
spelling wins, whichever order the rows arrive in, and the value that lost is
written to the review report. This assumes an ARK's rows arrive together, which
they do: both exporters write in primary-key order.

**Identifiers that do not fit the template still import.** They simply carry no
`sequence`, so they tell us nothing about where to resume minting.

**Re-running is safe.** Values that have not changed are left alone, and
`minted_at` is only ever set when the ARK is created, so a second run cannot
overwrite a date a curator has since corrected.

## Getting the export

From phpMyAdmin: export the database, SQL format, defaults are fine. Or on the
server:

```bash
mysqldump --single-transaction --default-character-set=utf8mb4 ARK_CORE > ARK_CORE.sql
gzip -k ARK_CORE.sql          # optional; the importer reads .sql.gz directly
```

> **The export is a secret.** Its `user` table holds staff passwords that can be
> decrypted with a key that is in the legacy source. Keep it outside every git
> checkout, `chmod 600` it, and delete it once the cutover is done. Both
> repositories ignore `*.sql`, but do not rely on that.

## The runbook

### 1. Find out who calls the old REST endpoint

This system has no HTTP API, so `admin/rest.php` disappears at cutover.

```bash
awk '$7 ~ /rest\.php/ {print $1}' /var/log/apache2/*access*.log | sort | uniq -c | sort -rn | head
```

Real integrations need converting to a management command, or the no-API
decision needs revisiting.

### 2. Freeze writes on legacy

Nothing may mint or bind after the export is taken, or the two diverge.

### 3. Import, in a dry run first

```bash
.venv/bin/python manage.py import_legacy \
    --legacy-dump /srv/ARK_CORE.sql --report review.csv --dry-run
```

Read `review.csv` and the totals. Then do it for real:

```bash
.venv/bin/python manage.py import_legacy \
    --legacy-dump /srv/ARK_CORE.sql --report review.csv
.venv/bin/python manage.py refresh_collection_stats
```

`refresh_collection_stats` prints each collection's counts; the collection page
in the staff interface shows the same figures. (`ark_stats`, from the optional
`arks-cli` plugin, adds the top element names.) Idempotent, so rehearse it as
often as you like.

### 4. Prove every ARK resolves identically

Run this system on an alternate port, under gunicorn rather than `runserver` —
the bare `?` inflection depends on the raw request URI, which the development
server does not pass on.

```bash
# a quick read first
.venv/bin/python manage.py resolve_diff \
    --legacy-base https://ark.digital.utsc.utoronto.ca \
    --new-base http://127.0.0.1:8001 --sample 500 --known review.csv

# then the whole thing
.venv/bin/python manage.py resolve_diff \
    --legacy-base https://ark.digital.utsc.utoronto.ca \
    --new-base http://127.0.0.1:8001 --known review.csv --out cutover-diff.csv
```

It walks every NAAN root, every ARK, every qualifier anything is bound under,
and the `?`, `??` and `?info` inflections. Legacy answers a miss by redirecting
to its own `404.php` (with a relative `Location: /404.php`), prints an HTML
"loader" page (`<head>`/`<style>`) before every ARK answer, wraps metadata in
`<pre>`, leaves HTML entities in both, and displays every `_` in a metadata
value as a space (this system shows values verbatim, on purpose); all of these
idioms are normalised before comparison, so what remains is a real difference
in what an ARK resolves to. Redirect
targets are still compared exactly, underscores included.

It exits non-zero while anything differs, and **separately** if a path could not
be fetched — a socket failure proves nothing either way. If you see those, lower
`--workers`; the default of 8 can exhaust local ports when both services are on
one host.

`--known review.csv` excuses the ARKs the import already told you about. Nothing
else is excused. Do not continue until it is clean.

> Every path `resolve_diff` fetches from legacy increments that ARK's `REDIRECT`
> counter over there. That is harmless, but it is why the export is taken before
> the diff and not after.

### 5. Flip the vhost, then verify

`a2dissite` the legacy site, `a2ensite arkservice`, reload, and curl a handful
of real ARKs. Rollback is putting the old site back: nothing in this process
wrote to the legacy database, so it stays a valid fallback indefinitely.

## Reading the review report

`--report FILE` writes one row per thing that could not be carried over exactly.
It is always written, including on a dry run.

| Column | |
|---|---|
| `reason` | `duplicate-element` or `redirect-for-unknown-ark` |
| `table` | the collection it came from |
| `ark_path` | the path it belongs to, e.g. `/ark:/61220/utsc1` |
| `element` | the element name, canonicalised |
| `value` | the value that did **not** make it |

**`duplicate-element`** — the element existed twice under different spellings.
The canonical spelling's value is what got stored; this row is the other one. To
put it back, bind it again on the ARK's page in the staff interface, or with the
optional `arks-cli` plugin: `manage.py bind '61220/utsc1' SOME_ELEMENT 'the other value'`.

**`redirect-for-unknown-ark`** — a hit count for something that was never an
ARK. Nothing to do; it is here so that "we dropped 1,606 rows" is a statement
you can check rather than take on trust.

Feed the same file to `resolve_diff --known` so these ARKs do not hold up the
cutover.

## What the production export looked like

Taken 2026-09-03, so that the next person can tell a healthy import from a
broken one.

| | |
|---|---|
| File | 219 MB, phpMyAdmin export, utf8mb4, 3,028,832 rows |
| Collections | one, `dsu_ark` — NAAN 61220, prefix `utsc`, template `.zd`, long-term, sequential |
| Legacy counter | `:/oacounter` 97,640; highest identifier `utsc97639` |

Importing it produces:

| Total | |
|---|---|
| collections created | 1 |
| arks created | 97,596 |
| minted at recovered | 97,595 |
| bindings created | 2,758,369 |
| elements merged | 2,743 |
| resolutions | 70,898 |
| redirects skipped | 1,606 (across 301 identifiers that were never ARKs) |

The collection page (or `ark_stats`, from the optional `arks-cli` plugin) then
reports 77,649 of those as bound, leaving 19,947 that legacy minted and never
gave any metadata to.

Minting resumes at `61220/utsc97640`. Mint dates run from 2020-10-22 to
2026-08-20. About a minute end to end; a second run creates nothing.

One identifier, `61220/utsc1`, has metadata but no `URL` — it is one of 25,854
that legacy also answered with its 404 page. That is data, not a fault.

## Troubleshooting

**`is not valid utf-8`** — the export was written in another encoding. Re-export
with `mysqldump --default-character-set=utf8mb4`, or name what it really is:
`--encoding latin-1`.

**`could not read line N of the export`** — the file is truncated, or was not
written by mysqldump or phpMyAdmin. Check the tail of the file for a `COMMIT;`.

**`it has no ':/naan' row`** — that table is not a collection, or the export is
partial. Name the ones you want with `--table`.

**`prefix 'utsc' is already used under NAAN 61220`** — a collection with that
prefix already exists under another name. Either import into it with
`--collection-name`, or rename one of the two.

**`… overlaps the prefix … of collection …`**: the legacy prefix starts, or is
the beginning of, the prefix of another collection under the same NAAN (`utsc`
and `utsc1`). Both would mint into the same identifiers, and whichever got there
second could never mint again, so the import refuses it (`INTENTS_prefix_overlap.md`).
Import into a database without the other collection, or remove it first.

**`--collection-name names one collection, but this source holds N`** — add
`--table` to say which one you mean.

**`resolve_diff` reports "could not be fetched"** — local port exhaustion. Lower
`--workers`.

**`resolve_diff` says there is nothing to check** — the import has not run
against the database this command is pointed at.

## After cutover

- Rename the collection from the legacy table name to something readable, in the
  staff interface.
- Create staff accounts. Legacy's are not migrated.
- Keep one copy of the export as the archival snapshot, somewhere access-
  controlled, and delete the working copies.
