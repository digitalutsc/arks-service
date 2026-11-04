# Scale and capacity

What this service does as a collection grows, measured rather than estimated.
Every number below was taken on MySQL 8 with a real dataset; the harness that
produced them is in `scripts/bench/`.

```bash
DATABASE_URL=mysql://... python scripts/bench/seed.py --arks 1000000
DATABASE_URL=mysql://... python scripts/bench/measure.py --label "my change"
```

---

## Measured, 1,000,000 ARKs / 4,500,000 bindings

Single MySQL 8 container, in-process client (no HTTP server), before and after
the scalability work.

| Operation | Before | After | Why |
|---|---|---|---|
| Resolve one ARK | 4.8 ms | **0.73 ms** hot, 3.0 ms cold | Target cached; no write on the path |
| Mint 100 | 1.78 s / 116 MB | **0.02 s / 0.2 MB** | Stopped loading every identifier |
| Exact value lookup (find by PID) | 5.91 s | **0.00 s** | Indexed `value_prefix` column |
| Free-text substring search | 8.69 s | 3.90 s | Still a scan — see below |
| Admin list, page 1 | 0.09 s | 0.05 s | Capped count |
| Admin list, page 1000 | 1.47 s | 0.82 s | |
| Admin list + free text | 14.46 s | 8.81 s | Count no longer runs the LIKE twice |
| Collection statistics | 2.00 s | 1.90 s | Unchanged; see *Known limits* |
| Export 5,000 rows | 32.87 s / 311 MB | **1.34 s / 93 MB** | Streamed instead of materialised |
| Import 100k ARKs / 440k rows | 7 m 13 s | **12 s** | Bulk writes, streamed in batches |
| Process peak RSS | 936 MB | **356 MB** | |

Resolver throughput, single-threaded, in-process:

| | requests/s | per request |
|---|---|---|
| One hot ARK (cached target) | 1,363 | 0.73 ms |
| 500 distinct ARKs | 332 | 3.02 ms |

---

## How each operation grows

| | 100k | 1M | 10M | 100M | 1B |
|---|---|---|---|---|---|
| **Resolve an ARK** | flat | flat | flat | flat | flat — two index lookups, never a scan |
| **Mint** | flat | flat | flat | flat | flat — bounded probe from the highest sequence |
| **Exact value lookup** | flat | flat | flat | flat | flat — index on `(name, value_prefix)` |
| **Export** | linear in rows exported, flat in memory |
| **Import** | linear in rows imported, flat in memory |
| **Free-text substring** | linear in bindings scanned |
| **Collection statistics** | linear in the collection |
| **Storage** | 0.2 GB | 2 GB | 22 GB | 220 GB | 2.2 TB |

Storage is roughly **2.2 KB per ARK** all in: the row, its six indexes, about
4.5 bindings, and their indexes. Values longer than about 8 KB move to overflow
pages and cost more.

---

## Known limits, and what to do about them

### Free-text substring search is a scan

`LIKE '%text%'` cannot use an index in any engine, and the schema is
deliberately restricted to the portable SQL subset (see README). Measured at
3.9 s over 4.5M bindings, so roughly 40 s at 10M ARKs and minutes at 100M.

Mitigations already in place: the result count is capped so the scan is not run
twice per page, and exact and starts-with lookups are index-backed. If
substring search over values becomes a daily need at 10M+, add an
engine-specific index — MySQL `FULLTEXT` with `MATCH … AGAINST`, or PostgreSQL
trigram — behind a setting. That trades the portable-subset rule for the speed,
which is a decision to take deliberately.

### Collection statistics count the collection

`collection_stats` runs `COUNT(*)` and a bound/unbound count. InnoDB keeps no
row count, so this is a full index scan: 1.9 s at 1M, minutes at 1B. It is on
the collection page only, not the resolver. Past ~10M, denormalise the counts
onto `Collection` and refresh them on a schedule.

### Redirect counts lag

Hits are buffered in one Valkey/Redis hash (`HINCRBY`, one round trip per hit
however many ARKs are pending) and written every 60 seconds
(`RESOLUTION_FLUSH_SECONDS`) by the scheduler, in batches of 500 pairs per
transaction. Counts are therefore up to a minute behind. This is the trade that
makes resolution a pure read — which in turn is what would let a read replica
serve it.

If Valkey/Redis is unreachable (0.5 s timeout), the hit is written straight to
the database, so counts are never silently abandoned and the redirect still
happens. A flush interrupted part-way is finished by the next one; the only
possible error is one batch counted twice if the scheduler dies in the instant
between a commit and clearing that batch from the hash.

*Changed 2026-11-04:* the earlier buffer kept a pickled set of pending pairs,
read and rewritten on every redirect. Concurrent hits dropped each other, the
flush lost hits that landed between reading and clearing a counter, and the cost
per hit grew with the number of distinct ARKs hit.

### Deployment capacity

`deploy/arkservice.service` runs gunicorn with 3 processes × 8 threads. The
threads matter: `/manifest` parks a worker on someone else's server, and with
three plain processes three slow targets stalled everything. `/manifest` now
times out after 5 seconds.

Rough ceiling on the current single VM: **several hundred resolutions a second**,
mostly bounded by the database round trip. To go further, in order of effort:
raise `--workers` to `2 × cores + 1`; put a read replica behind the resolver
(possible because resolving no longer writes); front the redirects with a CDN,
accepting that cached redirects are not counted.

### Beyond ~100M ARKs

Not reachable on one VM without operational changes:

- **Backups.** `mysqldump` stops being restorable somewhere around 100 GB
  (~40M ARKs) — the dump is quick, the index rebuild on restore is 6–20 hours.
  Move to physical backups (`mariabackup`) with binlog point-in-time recovery.
- **Schema changes.** Adding an index to a 100M-row InnoDB table rebuilds it.
  Use `gh-ost` or `pt-online-schema-change`.
- **Partitioning.** `core_binding` is the big table; partition by `ark_id` range
  past ~500M rows.
- **Media.** Uploaded CSVs and results are on local disk, which blocks running
  a second application host. Move to shared or object storage first.
- **Retention.** `BulkBindJob` rows and their files are kept forever. Add a
  retention job before this matters.

---

## What was fixed, and what it cost

Each of these was a real ceiling, not a micro-optimisation:

- **Minting read the whole collection** into memory on every call, inside the
  transaction holding the collection lock — 116 MB at 1M, OOM at 100M, with
  every other minter queued behind it. Now a bounded probe. *Cost: gaps left by
  deleted rows below the highest sequence are no longer refilled.*
- **Export materialised every matching id** and passed them all in one `IN`
  list, which fails outright above roughly 4M ids on MySQL's default
  `max_allowed_packet`. Now streamed. *Cost: the header comes from the
  collection's element names, so an element bound mid-export is skipped rather
  than aborting the download.*
- **Values were unindexable.** `value` is TEXT; MySQL cannot index it without a
  prefix length. A generated `value_prefix` column carries the index, and the
  database maintains it so no bulk writer can forget it. *Cost: one migration
  with a batched backfill — 20 s for 4.5M rows.*
- **Every redirect was a write.** *Cost: counts lag by up to a minute.*
- **The import held the whole legacy table** in memory, three times over — 4–5 GB
  per million ARKs. Now streamed in batches. *Cost: none.*
- **`prefix` was unique service-wide**, so a second NAAN could never reuse
  `utsc`. Now unique per NAAN. *Cost: a CLI referring to an ambiguous prefix
  must say `61220/utsc`.*
