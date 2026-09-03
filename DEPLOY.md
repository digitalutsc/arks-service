# Deploying the ARK service

Four environments, one codebase. Nothing in the repo refers to the checkout
directory name, so it can be renamed or moved freely.

| Environment | Runs on | Database | Worker | Static files |
|---|---|---|---|---|
| **Local** | `runserver` | SQLite | eager (in-process) | Django dev server |
| **Dev / Docker** | Compose: gunicorn + celery, defined in `docker-arks-service` | PostgreSQL 16 | Redis + Celery | WhiteNoise |
| **CI** | GitHub Actions | PostgreSQL **and** MySQL | n/a | n/a |
| **Production** | Bare on the LAMP VM | MySQL/MariaDB | Redis + Celery (systemd) | Apache, WhiteNoise as fallback |

No Docker file lives in this repository. The stack is defined next door in
`../docker-arks-service`, which builds an image from this checkout; see section
2. Production deliberately does not use it either, running against the MySQL
server already on the VM.

---

## 1. Local development

```bash
uv venv --python 3.13
uv sync --extra postgres --extra mysql
cp .env.example .env
```

Then edit `.env` and set at minimum:

```ini
DJANGO_DEBUG=true
```

With `DJANGO_DEBUG=true` the secret key and database URL are optional and the
service falls back to a local SQLite file. Then:

```bash
./.venv/bin/python manage.py migrate
./.venv/bin/python manage.py createsuperuser
./.venv/bin/python manage.py runserver
```

- Public resolver and landing page: <http://127.0.0.1:8000/>
- Staff interface: <http://127.0.0.1:8000/admin/>

A superuser is automatically treated as **Admin**. To give other accounts a
role, use the staff interface at `/admin/users/`.

### Running bulk binds without Redis

Set `CELERY_TASK_ALWAYS_EAGER=true` in `.env` and uploads run inline in the
request instead of on a worker. Fine for development; never use it in
production, where a 100k-row upload would hold an HTTP connection open.

### Why `manage.py` may refuse to run

If `DJANGO_DEBUG` is false and either `DJANGO_SECRET_KEY` or `DATABASE_URL` is
missing, the service refuses to start and names what is missing. That is
deliberate — see [Boot guards](#boot-guards). For local work, set
`DJANGO_DEBUG=true`.

---

## 2. Docker (dev and prototyping)

The Docker stack lives in its own repository, `docker-arks-service`, checked out
beside this one. It contains no application code: it points at this checkout and
builds an image from it, which is why nothing here refers to Docker.

```
arks-redesign/
├── arks-service-new/       this repository
└── docker-arks-service/    the Docker stack
```

```bash
cd ../docker-arks-service
make install     # build and start everything, from nothing
make up          # start an already-built stack
make down        # stop it, keeping the data
make clean       # remove it entirely: containers, volumes, image
make rebuild     # clean, then install
```

`make install` generates a secret key and an administrator password, brings up
`web` (gunicorn), `worker` (celery), `redis` and `db` (PostgreSQL 16), waits
until `/healthz` answers, creates the administrator, and prints the login.
Re-running it changes nothing that is already set.

Management commands run through the same Makefile:

```bash
make manage ARGS="createcollection 'UTSC Digital Collections' \
    --prefix utsc --naan 61220 --naa 'UTSC Library' --template .zd"
make manage ARGS="mint utsc 10"
```

Configuration is the `.env` file in that repository, and `ARKS_SRC` in it says
where this checkout is. The image runs `collectstatic` at build time and serves
static files through WhiteNoise, so no separate web server is needed.

One thing to know when working here: the Dockerfile copies each top-level
package of this repository by name rather than the whole tree, so **a new
top-level Django app needs a matching `COPY --from=src` line** in
`docker-arks-service/Dockerfile`. Its README says so too.

---

## 3. Continuous integration

`.github/workflows/ci.yml` runs three jobs:

- **lint** — `ruff check` and `ruff format --check`.
- **test** — the suite against **both** PostgreSQL and MySQL. This is what keeps
  the schema inside the portable subset; do not remove one of them.
- **conformance** — regenerates the noid golden vectors from the legacy PHP and
  fails if the committed fixture has drifted from what the original
  implementation actually does.

Run the same checks locally:

```bash
./.venv/bin/ruff check . && ./.venv/bin/ruff format --check .
./.venv/bin/python -m pytest -q

# against real engines
docker run -d --rm --name ark-pg -e POSTGRES_USER=ark -e POSTGRES_PASSWORD=ark \
    -e POSTGRES_DB=ark -p 55432:5432 postgres:16-alpine
docker run -d --rm --name ark-mysql -e MYSQL_ROOT_PASSWORD=root \
    -e MYSQL_DATABASE=ark -p 33306:3306 mysql:8.0

DATABASE_URL=postgres://ark:ark@127.0.0.1:55432/ark ./.venv/bin/python -m pytest -q
DATABASE_URL=mysql://root:root@127.0.0.1:33306/ark  ./.venv/bin/python -m pytest -q
```

> Some tests (concurrent minting, the resolution-counter race) skip on SQLite
> because it serialises writes globally. **A green SQLite run does not prove
> those.** Run MySQL at least once before believing a change is safe.

---

## 4. Production (bare on the LAMP VM)

### 4.1 System packages

```bash
sudo apt install python3.13 python3.13-venv redis-server \
                 libmysqlclient-dev pkg-config
sudo mkdir -p /var/www/arkservice /var/log/arkservice
sudo chown -R www-data:www-data /var/www/arkservice /var/log/arkservice
```

`libmysqlclient-dev` and `pkg-config` are needed to build `mysqlclient`; without
them the install fails with a `pkg-config: command not found` message that does
not mention MySQL.

### 4.2 Application

As `www-data`, in `/var/www/arkservice`:

```bash
git clone <repo> .
python3.13 -m venv .venv
.venv/bin/pip install -e '.[mysql]'

cp .env.example .env      # then edit — see 4.3
.venv/bin/python manage.py migrate
.venv/bin/python manage.py collectstatic --no-input
.venv/bin/python manage.py createsuperuser
```

### 4.3 Configuration

`.env` holds the database password, so lock it down:

```bash
sudo chmod 640 /var/www/arkservice/.env
sudo chown www-data:www-data /var/www/arkservice/.env
```

Required in production:

```ini
DJANGO_DEBUG=false
DJANGO_SECRET_KEY=<64 random characters>
DATABASE_URL=mysql://arkuser:password@localhost:3306/ark
DJANGO_ALLOWED_HOSTS=ark.digital.utsc.utoronto.ca
DJANGO_CSRF_TRUSTED_ORIGINS=https://ark.digital.utsc.utoronto.ca
CELERY_BROKER_URL=redis://localhost:6379/0
```

Generate the key with:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(64))"
```

> **systemd `EnvironmentFile` is not dotenv.** systemd keeps everything after
> the `=`, including inline `#` comments and trailing spaces, where python-dotenv
> strips them. `DJANGO_SECRET_KEY=abc # note` therefore differs between the
> service and a manual `manage.py` run, and sessions minted under one are
> invalid under the other. Keep values bare, unquoted, with no trailing comments.

### 4.4 Services

```bash
sudo cp deploy/arkservice.service deploy/arkservice-worker.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now arkservice arkservice-worker
sudo systemctl status arkservice arkservice-worker
```

- `arkservice` — gunicorn on `127.0.0.1:8000`, 3 processes × 8 threads. Threads
  matter: `/manifest` parks a worker on someone else's server, and with plain
  processes a few slow targets stalled the whole service.
- `arkservice-worker` — Celery with `--beat`, concurrency 2. Beat runs the
  periodic redirect-counter flush; with more than one worker host, run beat on
  exactly one of them.

Both run as `www-data` under `ProtectSystem=strict` with explicit
`ReadWritePaths`, `NoNewPrivileges`, `PrivateTmp`, `PrivateDevices`, kernel and
cgroup protection, `RestrictAddressFamilies`, an empty `CapabilityBoundingSet`,
a syscall filter and a memory ceiling.

### 4.5 Apache

```bash
sudo a2enmod proxy proxy_http headers ssl rewrite
sudo cp deploy/apache-arkservice.conf /etc/apache2/sites-available/arkservice.conf
# leave it disabled until cutover
```

**The one detail that must not be wrong: `nocanon`.**

A trailing bare `?` on an ARK is an *inflection* — "show me the metadata" — not
an empty query string. Django never sees it (it does not reach `QUERY_STRING`),
so the resolver reads the original request line from gunicorn's `RAW_URI`. For
that to arrive intact, Apache must proxy with `nocanon`:

```apache
ProxyPass        /static/ !
ProxyPass        / http://127.0.0.1:8000/ nocanon
ProxyPassReverse / http://127.0.0.1:8000/
AllowEncodedSlashes NoDecode
```

Check it after any Apache change:

```bash
curl -sI 'https://ark.digital.utsc.utoronto.ca/ark:/61220/utsc1?' | head -1
# expect: HTTP/1.1 200   (text/plain metadata)   NOT a 302
```

`resolve_diff` covers this too — inflections are checked by default — and is the
better check.

---

## Health check

`GET /healthz` reports whether this instance can actually serve — it checks the
database and the cache rather than merely confirming the process started.
Returns 200 when healthy and 503 when not, so Apache or a load balancer can act
on it.

```bash
curl -s http://127.0.0.1:8000/healthz
# {"status": "ok", "checks": {"database": "ok", "counters": "ok"}}
```

## Capacity

Measured numbers and what grows with the collection are in
[SCALE.md](SCALE.md). In short: resolution and minting stay flat at any size,
substring search and collection statistics scale with the data, and the current
single-VM shape is comfortable to roughly 10M ARKs.

## Boot guards

The service refuses to start when `DJANGO_DEBUG` is false and either
`DJANGO_SECRET_KEY` or `DATABASE_URL` is missing, and says which. Without that
check an incomplete `.env` would start gunicorn against an empty SQLite file —
**404ing every one of the ~100k ARKs, with nothing in the log to say why** — using
a well-known key that makes session cookies forgeable.

`.env.example` therefore ships `DJANGO_DEBUG=false`: copying it straight into
production fails loudly on the missing secret rather than quietly running in
debug mode.

---

## Cutover from the legacy service

The new system runs alongside the old one and only takes the domain once every
ARK is proven to resolve identically.

### Step 0 — find out who calls the old REST endpoint

This system has **no HTTP API**, so `admin/rest.php` disappears at cutover.

```bash
grep -c 'rest\.php' /var/log/apache2/*access*.log
awk '$7 ~ /rest\.php/ {print $1}' /var/log/apache2/*access*.log \
    | sort | uniq -c | sort -rn | head
```

If real integrations show up, they need converting to a management command run
locally, or the no-API decision needs revisiting.

### Step 1 — freeze writes on the legacy service

Nothing may mint or bind after the dump is taken, or the two will diverge.

### Steps 2 to 4 — export, import, and prove it

These are the substance of the migration and have their own document:
**[MIGRATION.md](MIGRATION.md)**. In brief:

```bash
# on the legacy server, after writes are frozen
mysqldump --single-transaction --default-character-set=utf8mb4 ARK_CORE > /srv/ARK_CORE.sql

# here — no scratch database needed, the export is read directly
.venv/bin/python manage.py import_legacy \
    --legacy-dump /srv/ARK_CORE.sql --report review.csv --dry-run
.venv/bin/python manage.py import_legacy \
    --legacy-dump /srv/ARK_CORE.sql --report review.csv
.venv/bin/python manage.py ark_stats

# then prove every ARK resolves identically, under gunicorn on an alternate port
.venv/bin/python manage.py resolve_diff \
    --legacy-base https://ark.digital.utsc.utoronto.ca \
    --new-base http://127.0.0.1:8001 --known review.csv --sample 500
.venv/bin/python manage.py resolve_diff \
    --legacy-base https://ark.digital.utsc.utoronto.ca \
    --new-base http://127.0.0.1:8001 --known review.csv --out cutover-diff.csv
```

Roughly 100k ARKs and 2.8M rows import in about a minute. It is idempotent, so
rehearse it as often as you like; a second run creates nothing.

`resolve_diff` walks every NAAN root, every ARK, every qualifier anything is
bound under, and the `?`, `??` and `?info` inflections. Legacy answers a miss by
redirecting to its own `404.php`, wraps metadata in `<pre>`, and leaves HTML
entities in both; all three are normalised before comparison. It exits non-zero
while anything differs, and **separately** if any path could not be fetched — a
socket failure proves nothing either way. If you see those, lower `--workers`;
the default of 8 can exhaust local ports when both services are on one host.

`--known review.csv` excuses the handful of ARKs the import already reported as
impossible to carry over verbatim. Nothing else is excused.

Do not continue until it is clean.

### Step 5 — flip the vhost

```bash
sudo a2dissite <legacy-site> && sudo a2ensite arkservice
sudo systemctl reload apache2
```

### Step 6 — verify in the open

```bash
curl -sI https://ark.digital.utsc.utoronto.ca/ark:/61220/utsc1  | head -2
curl -s  'https://ark.digital.utsc.utoronto.ca/ark:/61220/utsc1?' | head -3
curl -s  https://ark.digital.utsc.utoronto.ca/ark:/61220/
```

**Rollback** is re-enabling the old site and reloading Apache. Nothing in this
process writes to the legacy database, so it stays a valid fallback.

---

## Upgrading a running deployment

```bash
sudo -u www-data git -C /var/www/arkservice pull
sudo -u www-data /var/www/arkservice/.venv/bin/pip install -e '.[mysql]'
sudo -u www-data /var/www/arkservice/.venv/bin/python manage.py migrate
sudo -u www-data /var/www/arkservice/.venv/bin/python manage.py collectstatic --no-input
sudo systemctl restart arkservice arkservice-worker
```

Resolution is read-only apart from the redirect counter, so a restart is a brief
blip rather than an outage.

---

## Backups

The legacy service dumped the whole database before every mint and bind. That is
no longer done inline: writes are transactional, and a mint can no longer corrupt
anything it did not touch. Use ordinary scheduled `mysqldump` instead.

What holds state:

- the application database (collections, ARKs, bindings, counters, users);
- `MEDIA_ROOT` — uploaded bulk-bind CSVs and their per-row results files.

```bash
mysqldump --single-transaction ark > /backup/ark-$(date +%F).sql
tar czf /backup/ark-media-$(date +%F).tar.gz /var/www/arkservice/media
```

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Service will not start, "Refusing to start" | `DJANGO_SECRET_KEY` or `DATABASE_URL` missing with `DEBUG=false` | Set them in `.env`; the message names which |
| Every ARK 404s after deploy | Pointing at the wrong/empty database | Check `DATABASE_URL`; run `manage.py ark_stats` |
| `…/ark:/x/y?` returns 302 instead of metadata | Apache is missing `nocanon` | See [4.5](#45-apache) |
| Static files 404 | `collectstatic` not run | `manage.py collectstatic --no-input` |
| Bulk-bind jobs stay "Pending" | Worker not running or wrong broker | `systemctl status arkservice-worker`; check `CELERY_BROKER_URL` |
| `pkg-config: command not found` on install | MySQL client headers absent | `apt install libmysqlclient-dev pkg-config` |
| Mint-missing crashes with "Column 'ark_id' cannot be null" | Pre-2ecdb88 build on MySQL | Upgrade; `mint()` now reads keys back |
| `resolve_diff` reports "could not be fetched" | Local port exhaustion | Lower `--workers` |

Logs:

```bash
journalctl -u arkservice -f
journalctl -u arkservice-worker -f
tail -f /var/log/arkservice/{access,error,worker}.log
tail -f /var/log/apache2/arkservice-error.log
```

---

## Environment variables

| Variable | Default | Notes |
|---|---|---|
| `DJANGO_DEBUG` | `false` | `true` relaxes the boot guards and enables SQLite fallback |
| `DJANGO_SECRET_KEY` | dev placeholder | **Required** when `DEBUG` is false |
| `DATABASE_URL` | SQLite file | **Required** when `DEBUG` is false; `mysql://` or `postgres://` |
| `DJANGO_ALLOWED_HOSTS` | `localhost,127.0.0.1` | Comma-separated |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | empty | Needed behind HTTPS |
| `DJANGO_TIME_ZONE` | `America/Toronto` | |
| `DJANGO_LOG_LEVEL` | `INFO` | |
| `DB_CONN_MAX_AGE` | `60` | Seconds |
| `CELERY_BROKER_URL` | `redis://localhost:6379/0` | |
| `REDIS_URL` | empty | Cache for the login lockout, target cache and buffered counters. **Set it in production** — without it each gunicorn worker has its own |
| `LOGIN_MAX_ATTEMPTS` | `5` | Failures before a username+address is locked out |
| `LOGIN_LOCKOUT_SECONDS` | `900` | How long the lockout lasts |
| `TRUST_FORWARDED_FOR` | `false` | Set true only behind a proxy that sets it and when gunicorn is unreachable directly |
| `SESSION_COOKIE_AGE` | `28800` | Eight hours, refreshed on activity |
| `RESOLUTION_FLUSH_SECONDS` | `60` | How often buffered redirect counts are written |
| `ARK_PUBLIC_BASE_URL` | empty | Base URL the admin UI shows for an ARK. Empty derives it from the request (correct behind Apache, which preserves the Host and sets `X-Forwarded-Proto`). Set it only when staff reach the admin on a different hostname than the resolver |
| `BULK_BIND_MAX_BYTES` | `52428800` | Upload ceiling; `DATA_UPLOAD_MAX_MEMORY_SIZE` does **not** cover file parts |
| `CELERY_RESULT_BACKEND` | same as broker | |
| `CELERY_TASK_ALWAYS_EAGER` | `false` | `true` runs jobs inline — development only |
| `CELERY_TASK_TIME_LIMIT` | `3600` | Seconds |
| `MINT_MAX_PER_REQUEST` | `10000` | Largest single mint batch |
| `BULK_BIND_MAX_ROWS` | `100000` | Largest upload |
| `DATA_UPLOAD_MAX_MEMORY_SIZE` | `20971520` | 20 MB |
| `MANIFEST_FETCH_TIMEOUT` | `5` | Seconds. Short by design: the request holds a worker while fetching someone else's server |
| `MANIFEST_MAX_BYTES` | `10485760` | 10 MB |
| `MEDIA_ROOT` | `./media` | Uploaded CSVs and results |
| `SESSION_COOKIE_SECURE` / `CSRF_COOKIE_SECURE` | `true` when `DEBUG` false | Set false only for plain-HTTP testing |
| `SECURE_HSTS_SECONDS` | `0` | Enable once TLS is proven; hard to walk back |
| `SECURE_HSTS_INCLUDE_SUBDOMAINS` | `false` | |

---

## Accepted deviations from the original design note

- **Uniqueness is `(naan, identifier)`**, not `(collection, identifier)`.
  Stricter, and it is what makes resolution unambiguous.
- **`bindings` is indexed on `name` only.** `value` is unbounded `TEXT`, which
  MySQL cannot index without a prefix length, so value search is a scan —
  about a quarter of a second over 418k rows at current scale.
- **NAA lives on the collection**, mirroring the legacy `:/naa` row, rather than
  on the organisation. Where several collections share a NAAN, `/ark:/<naan>/`
  answers with the lowest collection name, deterministically.
