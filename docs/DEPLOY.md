# Deploying the ARK service

Four environments, one codebase. Nothing in the repo refers to the checkout
directory name, so it can be renamed or moved freely.

| Environment | Runs on | Database | Worker | Static files |
|---|---|---|---|---|
| **Local** | `runserver` | SQLite | eager (in-process) | Django dev server |
| **Dev / Docker** | Compose: gunicorn + celery, defined in `docker-arks-service` | PostgreSQL 16 (or MySQL 8.0) container | Valkey (or Redis) + Celery | WhiteNoise |
| **CI** | GitHub Actions | PostgreSQL **and** MySQL | n/a | n/a |
| **Production, Docker** | The same Compose stack with `docker-compose.external-db.yml` | An existing MySQL server, no container | Valkey (or Redis) + Celery | WhiteNoise, behind Apache |
| **Production, bare** | Bare on the LAMP VM | MySQL/MariaDB | Valkey (or Redis) + Celery (systemd) | Apache, WhiteNoise as fallback |

No Docker file lives in this repository. The stack is defined next door in
`../docker-arks-service`, which builds an image from this checkout; see section
2. Production either runs that stack pointed at an existing MySQL server
(section 2, [Production in Docker](#production-in-docker)) or runs bare on the
VM (section 4). Either way the broker and cache is **Valkey by default, or
Redis**: Valkey speaks the same protocol, so the application and its
`redis://` URLs do not change. There is no `valkey://` scheme.

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

With `DJANGO_DEBUG=true` the secret key, database URL and `REDIS_URL` are
optional. `.env.example` points `DATABASE_URL` at a local PostgreSQL server;
comment out or remove that line and the service falls back to a local SQLite
file instead. Then:

```bash
./.venv/bin/python manage.py migrate
./.venv/bin/python manage.py createsuperuser
./.venv/bin/python manage.py runserver
```

- Public resolver and landing page: <http://127.0.0.1:8000/>
- Staff interface: <http://127.0.0.1:8000/admin/>

A superuser is automatically treated as **Admin**. To give other accounts a
role, use the staff interface at `/admin/users/`.

### Running bulk binds without Redis or Valkey

Set `CELERY_TASK_ALWAYS_EAGER=true` in `.env` and uploads run inline in the
request instead of on a worker. Fine for development; never use it in
production, where a 100k-row upload would hold an HTTP connection open.

### Why `manage.py` may refuse to run

If `DJANGO_DEBUG` is false and any of `DJANGO_SECRET_KEY`, `DATABASE_URL` or
`REDIS_URL` is missing, the service refuses to start and names what is missing. That is
deliberate — see [Boot guards](#boot-guards). For local work, set
`DJANGO_DEBUG=true`.

---

## 2. Docker (development, demos and production)

The Docker stack lives in its own repository,
[`docker-arks-service`](https://github.com/digitalutsc/docker-arks-service). It
contains no application code: it points at a checkout of this repository and
builds an image from it, which is why nothing here refers to Docker.

When you are working on the application, check the two out side by side and the
stack builds from your working tree:

```
arks-redesign/
├── arks-service/           this repository
└── docker-arks-service/    the Docker stack
```

When you only want the service running, clone `docker-arks-service` on its own:
finding no checkout beside it, it clones this repository into its own
gitignored `src/arks-service`. Either way the path ends up as `ARKS_SRC` in
that repository's `.env`, and a checkout that already exists is never pulled or
reset.

```bash
cd ../docker-arks-service
make up          # bring everything up, from nothing if need be
make install     # the same, but always rebuild the image first
make down        # stop it, keeping the data
make clean       # remove it entirely: containers, volumes, image
make rebuild     # clean, then install
```

`make up` generates a secret key and an administrator password, fetches the
application if there is no checkout, builds the image if there is none, brings
up `web` (gunicorn), `worker` (celery, bulk binds), `scheduler` (celery beat and
the periodic queue), `broker` (Valkey) and `db` (PostgreSQL 16), waits until
`/healthz` answers, creates the administrator, and prints the login.
Re-running it changes nothing that is already set, so it is also the everyday
way to start the stack.

The source is copied into the image, not mounted. **After changing code here,
run `make install`** there; `make up` alone keeps serving the image it already
has.

Management commands run through the same Makefile:

```bash
make manage ARGS="createcollection 'UTSC Digital Collections' \
    --prefix utsc --naan 61220 --naa 'UTSC Library' --template .zd"
make manage ARGS="mint utsc 10"
```

Those two are staff commands from the optional `arks-cli` plugin, so the image
must have been built with it: set `ARKS_PLUGIN_SRC` (the plugin checkout) and
`ARKS_PLUGINS=arks_cli` in the stack's `.env`, then `make install`.

Configuration is the `.env` file in that repository. `ARKS_SRC` in it says where
this checkout is; `ARKS_REPO` and `ARKS_REF` say where to clone it from, and at
which branch or tag, when there is none. The image runs `collectstatic` at build time and serves
static files through WhiteNoise, so no separate web server is needed.

One thing to know when working here: the Dockerfile copies each top-level
package of this repository by name rather than the whole tree, so **a new
top-level Django app needs a matching `COPY --from=src` line** in
`docker-arks-service/Dockerfile`. Its README says so too.

The stack picks its database with `COMPOSE_FILE` in its `.env`
(`docker-compose.mysql.yml` runs a MySQL 8.0 container instead of PostgreSQL;
`POSTGRES_DB`, `POSTGRES_USER` and `POSTGRES_PASSWORD` name the PostgreSQL
container's database and account), and its broker with `BROKER_IMAGE`: Valkey
when that is unset, `BROKER_IMAGE=redis:7-alpine` for Redis. The broker
container requires `BROKER_PASSWORD`, which `make up` generates.

### Production in Docker

For production the stack runs against an existing MySQL server and starts no
database container. The broker can stay a password-protected container, or be
an existing Valkey or Redis server too. In `docker-arks-service/.env`:

```ini
COMPOSE_FILE=docker-compose.yml:docker-compose.external-db.yml:docker-compose.external-broker.yml
MYSQL_HOST=<the MySQL endpoint>
MYSQL_PORT=3306
MYSQL_DATABASE=ark
MYSQL_USER=ark
MYSQL_PASSWORD=<letters and digits, or percent-encoded>
BROKER_HOST=<the Valkey or Redis endpoint>
BROKER_PORT=6379
BROKER_USERNAME=<a named account, or blank for the default user>
BROKER_PASSWORD=<that account's password>
```

Leave `:docker-compose.external-broker.yml` and the `BROKER_HOST` block out to
keep the broker container. For a broker reached over TLS, also set
`BROKER_SCHEME=rediss` and `BROKER_URL_OPTIONS=?ssl_cert_reqs=required`. The
database must exist already; `web` runs `migrate` against it on every start.
Everything else (the caveats about reaching the servers from a container,
`make clean`, and `make import-dump` writing into that database) is in the
stack's README under "Production: an external MySQL server" and "Production:
an external Valkey or Redis server". Behind Apache with TLS, add
`docker-compose.proxy.yml` (loopback-only port, secure cookies, trusted
`X-Forwarded-For`); the stack's README section "Behind a reverse proxy with
TLS" has the vhost shape.

---

## 3. Continuous integration

`.github/workflows/ci.yml` runs three jobs:

- **lint** — `ruff check` and `ruff format --check`.
- **test** — the suite against **both** PostgreSQL and MySQL. This is what keeps
  the schema inside the portable subset; do not remove one of them.
- **conformance** — regenerates the noid golden vectors from the legacy PHP and
  fails if the committed fixture has drifted from what the original
  implementation actually does. The legacy app is checked out from
  `digitalutsc/arks-service-archived`, pinned to commit `b30909c`; the name
  `digitalutsc/arks-service` now belongs to this repository.

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
sudo apt install python3.13 python3.13-venv valkey-server \
                 libmysqlclient-dev pkg-config pipx
sudo pipx install --global uv   # /usr/local/bin/uv, for every user; the project is installed with uv, as CI and the image do
```

Valkey is the default broker and cache. Debian 13 packages it, and so do
recent Ubuntu releases; check with `apt-cache policy valkey-server`. On a
release without it, or to run Redis by choice, install `redis-server` instead.
Nothing else changes: both listen on port 6379, the `redis://` URLs below stay
as they are, and `arkservice-worker.service` already orders itself after
either one.

```bash
sudo mkdir -p /var/www/arkservice /var/log/arkservice
sudo chown -R www-data:www-data /var/www/arkservice /var/log/arkservice
```

`libmysqlclient-dev` and `pkg-config` are needed to build `mysqlclient`; without
them the install fails with a `pkg-config: command not found` message that does
not mention MySQL. They are needed even when MySQL runs on another machine,
because they build the client driver, not a server.

### 4.2 Application

As `www-data`, in `/var/www/arkservice`:

```bash
git clone <repo> .
uv sync --frozen --no-dev --extra mysql --python python3.13 --no-cache   # creates .venv from uv.lock

cp .env.example .env      # then edit — see 4.3
.venv/bin/python manage.py migrate
.venv/bin/python manage.py collectstatic --no-input
.venv/bin/python manage.py createsuperuser
```

Optional: the staff command line (`createcollection`, `mint`, `bind`, `unbind`, `bulk_bind`, `ark_stats`) is the separate `arks-cli` plugin. The operator commands used below (`import_legacy`, `resolve_diff`, `export_arks`, …) need nothing extra.

```bash
uv pip install -e /path/to/arks-cli --python .venv/bin/python --no-cache   # a checkout of github.com/digitalutsc/arks-cli; not on PyPI
echo "ARKS_PLUGINS=arks_cli" >> .env                                       # then restart the services
```

The application is not a Python package (`pyproject.toml` has no build
backend, on purpose: it is a Django project, not a library), so
`pip install -e .` fails with a setuptools "multiple top-level packages"
error. `uv sync` installs the locked dependencies into `.venv` and leaves the
code where `git` put it. `--no-cache` because `www-data` has no writable home
for uv's cache. A plain `uv sync` later removes the plugin again; use
`--inexact` when upgrading, as below.

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
# localhost, or the MySQL server's hostname when it is on another machine
DATABASE_URL=mysql://arkuser:password@localhost:3306/ark
DJANGO_ALLOWED_HOSTS=ark.digital.utsc.utoronto.ca
DJANGO_CSRF_TRUSTED_ORIGINS=https://ark.digital.utsc.utoronto.ca
CELERY_BROKER_URL=redis://:<broker password>@localhost:6379/0
REDIS_URL=redis://:<broker password>@localhost:6379/1
# Apache is the only route to gunicorn (it binds 127.0.0.1), so trust its
# X-Forwarded-For. Left false, the login throttle sees every client as
# 127.0.0.1 and five failed attempts from anyone lock the real user out.
TRUST_FORWARDED_FOR=true
```

**Give the broker a password.** Valkey and Redis accept anyone who can reach
them unless told otherwise, and anyone who can write to the queue can run
jobs as the application. Set `requirepass <broker password>` in
`/etc/valkey/valkey.conf` (or `/etc/redis/redis.conf`), restart the service,
and put the same password in both URLs as above. The form depends on the
server:

```ini
# the server's default user, with requirepass
CELERY_BROKER_URL=redis://:password@localhost:6379/0
# a named account (ACL user), as a managed service hands out
CELERY_BROKER_URL=redis://username:password@valkey.example:6379/0
# over TLS; Celery refuses rediss:// without ssl_cert_reqs
CELERY_BROKER_URL=rediss://username:password@valkey.example:6380/0?ssl_cert_reqs=required
```

`REDIS_URL` takes the same form with database `1`. Percent-encode anything but
letters and digits in the user name and password: `@` as `%40`, `/` as `%2F`,
`#` as `%23`, `%` as `%25`, `:` as `%3A`.

Generate the key with:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(64))"
```

Optional, for a branded landing page and error pages:

```ini
FALLBACK_PAGES_DIR=/srv/ark/fallback
```

Copy `docs/fallback-example/` there and edit it; `ProtectSystem=strict` leaves
the directory readable, which is all the service needs. Its README has the
rules; a superuser can preview the pages from the Users page.

> **systemd `EnvironmentFile` is not dotenv.** systemd keeps everything after
> the `=`, including inline `#` comments and trailing spaces, where python-dotenv
> strips them. `DJANGO_SECRET_KEY=abc # note` therefore differs between the
> service and a manual `manage.py` run, and sessions minted under one are
> invalid under the other. Keep values bare, unquoted, with no trailing comments.

### 4.4 Services

```bash
sudo cp deploy/arkservice.service deploy/arkservice-worker.service \
    deploy/arkservice-beat.service /etc/systemd/system/
sudo cp deploy/logrotate-arkservice /etc/logrotate.d/arkservice
sudo systemctl daemon-reload
sudo systemctl enable --now arkservice arkservice-worker arkservice-beat
sudo systemctl status arkservice arkservice-worker arkservice-beat
```

- `arkservice` — gunicorn on `127.0.0.1:8000`, 3 processes × 8 threads. Threads
  matter: `/manifest` parks a worker on someone else's server, and with plain
  processes a few slow targets stalled the whole service. Each process is
  recycled after about 2,000 requests (`--max-requests`). It writes only an
  error log; Apache's access log already records every request.
- `arkservice-worker` — Celery, queue `celery`, concurrency 2: bulk binds only.
  A worker process is replaced after 20 jobs or ~1 GB.
- `arkservice-beat` — Celery beat plus a one-process worker for queue
  `periodic`: the redirect-count flush every `RESOLUTION_FLUSH_SECONDS`, the
  collection-stats refresh every `COLLECTION_STATS_SECONDS`, the stale-job
  reaper every 10 minutes, daily session cleanup and optional bulk-bind
  retention. Kept apart so a long bulk bind can never delay the flush. Run exactly one, even with several worker hosts. Beat's state file is
  `/tmp/celerybeat-schedule` (`CELERY_BEAT_SCHEDULE_FILENAME`), private to the
  unit through `PrivateTmp`; the working directory is read-only.

Upgrading from a release with only two units: copy and enable
`arkservice-beat.service` and the logrotate file, and restart
`arkservice-worker`, which no longer runs beat. Without the beat unit nothing
flushes redirect counts (`/healthz` shows `counters_flushed_ago` growing).

All three run as `www-data` under `ProtectSystem=strict` with explicit
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
ProxyPass        / http://127.0.0.1:8000/ nocanon ttl=3
ProxyPassReverse / http://127.0.0.1:8000/
AllowEncodedSlashes NoDecode
```

The vhost also sets `ProxyTimeout 120`, `ttl=3` (below gunicorn's 5 s
keep-alive, so Apache never reuses a connection gunicorn has closed), and
`LimitRequestBody`: 1 MiB everywhere except the bulk-bind upload, which gets
55 MiB. Apache refuses an oversized body before it reaches disk; raise that
number if you raise `BULK_BIND_MAX_BYTES`.

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
database, the Django cache and the redirect-hit buffer rather than merely
confirming the process started. Returns 200 when healthy and 503 when not, so
Docker, a monitor or a load balancer can act on it. Failures say only `"error"`;
the detail goes to the log, because the endpoint is public.

```bash
curl -s http://127.0.0.1:8000/healthz
# {"status": "ok", "checks": {"database": "ok", "cache": "ok", "counters": "ok"},
#  "counters_flushed_ago": 12}
```

`counters_flushed_ago` is the seconds since buffered redirect counts were last
written to the database (null before the first flush). It never fails the
check, but a value far above `RESOLUTION_FLUSH_SECONDS` means the scheduler
(`arkservice-beat`, or the Docker `scheduler` service) is not running.

The resolver itself does not depend on Valkey: a redirect reads its target from
MySQL, and if the hit buffer is unreachable the hit is written straight to the
database. With Valkey down, redirects keep working (`/healthz` reports
degraded); staff sign-in and the admin pages that cache need it back.

### Valkey settings for a host-installed server

The server holds the Celery queue (database 0) and the cache plus buffered hits
(database 1), so it must not drop keys on its own. In `/etc/valkey/valkey.conf`
(or `redis.conf`):

```
appendonly yes
appendfsync everysec
maxmemory 256mb
maxmemory-policy noeviction
```

Never an `allkeys-*` policy: it would evict queued bulk-bind jobs and unflushed
redirect counts. With `noeviction` a full server refuses writes; hits then fall
back to the database and a new bulk bind fails visibly instead of vanishing.

### Database server (MySQL)

At ~100k ARKs the defaults are fine. For a few million ARKs (about 9 GB of data
and indexes at 4M; see [SCALE.md](SCALE.md)), ask for `innodb_buffer_pool_size`
of at least 4 GB, so the indexes the resolver uses stay in memory even after a
free-text search has scanned the bindings table, and check binary-log retention
against disk space while bulk-loading (each 100k-row bulk bind is one
transaction). Compressing `core_binding` (`ROW_FORMAT=COMPRESSED`) saves space
at some write CPU; it is a server-side choice, not part of the migrations.

## Capacity

Measured numbers and what grows with the collection are in
[SCALE.md](SCALE.md). In short: resolution and minting stay flat at any size,
substring search and collection statistics scale with the data, and the current
single-VM shape is comfortable to roughly 10M ARKs.

## Boot guards

The service refuses to start when `DJANGO_DEBUG` is false and any of
`DJANGO_SECRET_KEY`, `DATABASE_URL` or `REDIS_URL` is missing, and says which. Without that
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
.venv/bin/python manage.py refresh_collection_stats   # prints the counts; also on each collection's page

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
# --inexact keeps the arks-cli plugin installed, if you added it in 4.2
sudo -u www-data uv sync --project /var/www/arkservice --frozen --no-dev --extra mysql --inexact --no-cache
sudo -u www-data /var/www/arkservice/.venv/bin/python manage.py migrate
sudo -u www-data /var/www/arkservice/.venv/bin/python manage.py collectstatic --no-input
sudo systemctl restart arkservice arkservice-worker arkservice-beat
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
- `MEDIA_ROOT` — bulk-bind per-row results files, plus the uploaded CSV of any job still
  pending or running (an upload is deleted as soon as its job has run).

```bash
mysqldump --single-transaction ark > /backup/ark-$(date +%F).sql
tar czf /backup/ark-media-$(date +%F).tar.gz /var/www/arkservice/media
```

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Service will not start, "Refusing to start" | `DJANGO_SECRET_KEY`, `DATABASE_URL` or `REDIS_URL` missing with `DEBUG=false` | Set them in `.env`; the message names which |
| Every ARK 404s after deploy | Pointing at the wrong/empty database | Check `DATABASE_URL`; run `manage.py refresh_collection_stats`, which prints each collection's counts |
| `…/ark:/x/y?` returns 302 instead of metadata | Apache is missing `nocanon` | See [4.5](#45-apache) |
| Static files 404 | `collectstatic` not run | `manage.py collectstatic --no-input` |
| Bulk-bind jobs stay "Pending" | Worker not running or wrong broker | `systemctl status arkservice-worker`; check `CELERY_BROKER_URL`. A job pending for 15 minutes is re-queued by the reaper |
| A job says "Interrupted: the worker stopped…" | The worker was restarted or killed mid-job | Nothing from that file was applied; upload it again |
| Redirect counts never change; `/healthz` `counters_flushed_ago` keeps growing | The scheduler is not running | `systemctl status arkservice-beat` (Docker: `make logs`, look for `scheduler`) |
| Service will not start: "REDIS_URL is unset" | Production without the cache server configured | Set `REDIS_URL` |
| `pkg-config: command not found` on install | MySQL client headers absent | `apt install libmysqlclient-dev pkg-config` |
| Mint-missing crashes with "Column 'ark_id' cannot be null" | Pre-2ecdb88 build on MySQL | Upgrade; `mint()` now reads keys back |
| `resolve_diff` reports "could not be fetched" | Local port exhaustion | Lower `--workers` |

Logs:

```bash
journalctl -u arkservice -f          # application log (Django logs to stderr)
journalctl -u arkservice-worker -f
journalctl -u arkservice-beat -f
tail -f /var/log/arkservice/{error,worker,beat}.log
tail -f /var/log/apache2/arkservice-{access,error}.log
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
| `DB_CONN_MAX_AGE` | `60` | Seconds a connection is kept for reuse; `0` closes it after each request |
| `DB_CONN_HEALTH_CHECKS` | `true` | Check a reused connection before using it. Keep it on when MySQL is across a network, where idle connections get dropped ("server has gone away") |
| `CELERY_BROKER_URL` | `redis://localhost:6379/0` | Valkey or Redis; the scheme is `redis://` (or `rediss://`) for both. Credentials go in the URL: `redis://:password@host:6379/0`, or `redis://user:password@…` for a named account |
| `REDIS_URL` | empty | Valkey or Redis, for the login lockout, the staff-side cache and the buffered redirect counters, with credentials as for `CELERY_BROKER_URL` and a different database number. **Required in production**: the service refuses to start without it |
| `CACHE_SOCKET_TIMEOUT` | `0.5` | Seconds to wait on Valkey/Redis before giving up, so a hung server cannot hold request threads |
| `LOGIN_MAX_ATTEMPTS` | `5` | Failures before a username+address is locked out |
| `LOGIN_LOCKOUT_SECONDS` | `900` | How long the lockout lasts |
| `TRUST_FORWARDED_FOR` | `false` | Set true behind a proxy that sets it and is the only route to gunicorn: the vhost in this guide, so set it (4.3). Never true with gunicorn reachable directly |
| `SESSION_COOKIE_AGE` | `28800` | Eight hours, refreshed on activity |
| `RESOLUTION_FLUSH_SECONDS` | `60` | How often buffered redirect counts are written |
| `COLLECTION_STATS_SECONDS` | `300` | How often the scheduler recounts collections and rebuilds element-name lists. Collections of 50,000+ ARKs show these stored counts |
| `SORT_SUBQUERY_MAX_ROWS` | `50000` | Largest result the staff list will sort by Redirects or Elements |
| `EXPORT_SYNC_MAX_ROWS` | `100000` | Largest export the staff interface streams; bigger ones point to `export_arks` |
| `ARK_PUBLIC_BASE_URL` | empty | Base URL the admin UI shows for an ARK. Empty derives it from the request (correct behind Apache, which preserves the Host and sets `X-Forwarded-Proto`). Set it only when staff reach the admin on a different hostname than the resolver |
| `BULK_BIND_MAX_BYTES` | `52428800` | Upload ceiling; `DATA_UPLOAD_MAX_MEMORY_SIZE` does **not** cover file parts |
| `CELERY_RESULT_BACKEND` | same as broker | Results are not stored (`task_ignore_result`); nothing reads them |
| `CELERY_TASK_ALWAYS_EAGER` | `false` | `true` runs jobs inline — development only |
| `CELERY_TASK_TIME_LIMIT` | `3600` | Seconds |
| `ARKS_PLUGINS` | empty | Optional plugins to enable, comma-separated Django app names; `arks_cli` for the staff command line (`createcollection`, `mint`, `bind`, `unbind`, `bulk_bind`, `ark_stats`) once the `arks-cli` package is installed. A name that is not installed stops the service with a clear message |
| `MINT_MAX_PER_REQUEST` | `10000` | Largest single mint from the form or the `mint` command; `0` removes the cap. Bulk bind is not subject to it (it is bounded by `BULK_BIND_MAX_ROWS`). A very large form mint can outlast Apache's `ProxyTimeout`: the browser gets an error page, but the mint still completes |
| `BULK_BIND_RETENTION_DAYS` | `0` | Delete finished bulk-bind jobs and their results files after this many days, daily (uploads are already deleted when a job ends). `0` keeps them forever; `manage.py prune_bulk_jobs --older-than N [--dry-run]` does it by hand |
| `CELERY_BEAT_SCHEDULE_FILENAME` | `/tmp/celerybeat-schedule` | Beat's state file; must be writable by the scheduler |
| `BULK_BIND_MAX_ROWS` | `100000` | Largest upload |
| `FALLBACK_PAGES_DIR` | empty | A directory holding operator-written `index.html`, `403.html`, `404.html`, `500.html` and their assets, served in place of the built-in landing page and Django's plain error pages (`resolver/fallback.py`). Empty means off. Starting kit: `docs/fallback-example/` |
| `DATA_UPLOAD_MAX_MEMORY_SIZE` | `20971520` | 20 MB |
| `MANIFEST_FETCH_TIMEOUT` | `30` | Seconds each read may wait. On-demand manifests send nothing until they are built (23–35 s cold, measured); the concurrency cap, not this, stops slow targets taking every thread |
| `MANIFEST_TOTAL_TIMEOUT` | `30` | Seconds for the whole `/manifest` fetch, as in legacy; keep it under gunicorn's `--timeout` (60) |
| `MANIFEST_MAX_BYTES` | `10485760` | 10 MB; a larger declared `Content-Length` is refused before reading |
| `MANIFEST_MAX_CONCURRENT` | `4` | `/manifest` fetches at once per gunicorn process; beyond it, 503 with `Retry-After` |
| `DB_CONNECT_TIMEOUT` / `DB_READ_TIMEOUT` / `DB_WRITE_TIMEOUT` | `5` / `60` / `60` | MySQL only. Seconds before a stalled server is given up on |
| `FILE_UPLOAD_MAX_MEMORY_SIZE` | `5242880` | Uploads larger than this are spooled to a temporary file |
| `MEDIA_ROOT` | `./media` | Bulk-bind results files, and uploads until their job ends |
| `SESSION_COOKIE_SECURE` / `CSRF_COOKIE_SECURE` | `true` when `DEBUG` false | Set false only for plain-HTTP testing |
| `SECURE_HSTS_SECONDS` | `0` | Enable once TLS is proven; hard to walk back |
| `SECURE_HSTS_INCLUDE_SUBDOMAINS` | `false` | |

---

## Accepted deviations from the original design note

- **Uniqueness is `(naan, identifier)`**, not `(collection, identifier)`.
  Stricter, and it is what makes resolution unambiguous.
- **`bindings` is indexed on `(name, value_prefix)`**, a generated column holding
  the first characters of the value, because `value` is unbounded `TEXT`, which
  MySQL cannot index without a prefix length. Starts-with search and exact-value
  lookups use that index; *contains* search is still a scan over every value.
- **NAA lives on the collection**, mirroring the legacy `:/naa` row, rather than
  on the organisation. Where several collections share a NAAN, `/ark:/<naan>/`
  answers with the lowest collection name, deterministically.
