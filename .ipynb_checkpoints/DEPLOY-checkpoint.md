# Deploying the ARK service

Four environments, one codebase. Nothing in the repo refers to the checkout
directory name, so it can be renamed or moved freely.

| Environment | Runs on | Database | Worker | Static files |
|---|---|---|---|---|
| **Local** | `runserver` | SQLite | eager (in-process) | Django dev server |
| **Dev / Docker** | Compose: gunicorn + celery | PostgreSQL 16 | Redis + Celery | WhiteNoise |
| **CI** | GitHub Actions | PostgreSQL **and** MySQL | n/a | n/a |
| **Production** | Bare on the LAMP VM | MySQL/MariaDB | Redis + Celery (systemd) | Apache, WhiteNoise as fallback |

Production deliberately does **not** use Docker: it runs against the MySQL
server already on the VM. The image exists so the whole stack can be brought up
anywhere with one command, and carries no data.

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

Brings up four containers: `web` (gunicorn), `worker` (celery), `redis`, and
`db` (PostgreSQL 16).

```bash
docker compose up --build
# http://localhost:8000
```

The Compose project is named `arkservice` explicitly, so renaming the checkout
directory does not orphan the volumes.

```bash
# create a collection and mint inside the stack
docker compose exec web python manage.py createcollection "UTSC Digital Collections" \
    --prefix utsc --naan 61220 --naa "UTSC Library" --template .zd
docker compose exec web python manage.py mint utsc 10
docker compose exec web python manage.py createsuperuser

# tear down, keeping data
docker compose down
# tear down, discarding data
docker compose down -v
```

Configuration comes from the environment block in `docker-compose.yml`; override
`DJANGO_SECRET_KEY` in your shell or an `.env` file next to the compose file.

The image runs `collectstatic` at build time and serves static files through
WhiteNoise, so no separate web server is needed.

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

- `arkservice` — gunicorn on `127.0.0.1:8000`, 3 workers.
- `arkservice-worker` — Celery, concurrency 2, for bulk-bind uploads.

Both run as `www-data` with `NoNewPrivileges`, `PrivateTmp`, `ProtectSystem=full`
and `ProtectHome`.

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

### Step 2 — dump and restore into a scratch database

```bash
mysqldump ark_legacy > /tmp/ark-legacy.sql
mysql -e 'CREATE DATABASE ark_legacy_copy CHARACTER SET utf8mb4'
mysql ark_legacy_copy < /tmp/ark-legacy.sql
```

### Step 3 — import

Idempotent, so rehearse it as often as you like.

```bash
.venv/bin/python manage.py import_legacy \
    --legacy-url mysql://user:pw@localhost/ark_legacy_copy --dry-run
.venv/bin/python manage.py import_legacy \
    --legacy-url mysql://user:pw@localhost/ark_legacy_copy
.venv/bin/python manage.py ark_stats
```

Roughly 100k ARKs / 440k rows takes about 15 seconds. A second run is a no-op of
a few seconds.

### Step 4 — diff every ARK against the running legacy service

```bash
# quick read first
.venv/bin/python manage.py resolve_diff \
    --legacy-base https://ark.digital.utsc.utoronto.ca \
    --new-base http://127.0.0.1:8000 --sample 500

# then the whole thing
.venv/bin/python manage.py resolve_diff \
    --legacy-base https://ark.digital.utsc.utoronto.ca \
    --new-base http://127.0.0.1:8000 --out cutover-diff.csv
```

It walks every NAAN root, every ARK, every qualifier anything is bound under,
and the `?`, `??` and `?info` inflections. It exits non-zero while anything
differs, and **separately** if any path could not be fetched — a socket failure
proves nothing either way, so those are reported apart from real differences
rather than counted as passes. If you see them, lower `--workers`; the default
of 8 can exhaust local ports when both services are on one host.

Legacy answers a miss by redirecting to its own `404.php` and wraps metadata in
`<pre>`; those idioms are normalised before comparison, so what remains is a
real difference in what an ARK resolves to.

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
| `CELERY_RESULT_BACKEND` | same as broker | |
| `CELERY_TASK_ALWAYS_EAGER` | `false` | `true` runs jobs inline — development only |
| `CELERY_TASK_TIME_LIMIT` | `3600` | Seconds |
| `MINT_MAX_PER_REQUEST` | `10000` | Largest single mint batch |
| `BULK_BIND_MAX_ROWS` | `100000` | Largest upload |
| `DATA_UPLOAD_MAX_MEMORY_SIZE` | `20971520` | 20 MB |
| `MANIFEST_FETCH_TIMEOUT` | `30` | Seconds, for `/manifest` |
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
