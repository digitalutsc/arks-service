# Deploying

Production runs bare on the existing LAMP VM against the MySQL server already
there. Docker is for development and prototyping only; the image carries no
data.

## First install

```bash
sudo apt install python3.13 python3.13-venv redis-server \
                 libmysqlclient-dev pkg-config
sudo mkdir -p /var/www/arkservice /var/log/arkservice
sudo chown -R www-data:www-data /var/www/arkservice /var/log/arkservice

# as www-data, in /var/www/arkservice
git clone <repo> .
python3.13 -m venv .venv
.venv/bin/pip install -e '.[mysql]'

cp .env.example .env      # then edit: DATABASE_URL, DJANGO_SECRET_KEY, hosts
.venv/bin/python manage.py migrate
.venv/bin/python manage.py collectstatic --no-input
.venv/bin/python manage.py createsuperuser
```

`.env` must be readable only by `www-data` — it holds the database password:

```bash
sudo chmod 640 /var/www/arkservice/.env
sudo chown www-data:www-data /var/www/arkservice/.env
```

Then the services and the vhost:

```bash
sudo cp deploy/arkservice.service deploy/arkservice-worker.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now arkservice arkservice-worker

sudo a2enmod proxy proxy_http headers ssl rewrite
sudo cp deploy/apache-arkservice.conf /etc/apache2/sites-available/arkservice.conf
# leave it disabled until cutover — see below
```

## The one configuration detail that matters

A trailing bare `?` on an ARK is an *inflection* — "show me the metadata" —
not an empty query string. Django never sees it (it does not reach
`QUERY_STRING`), so the resolver reads the original request line from gunicorn's
`RAW_URI`. For that to arrive intact, Apache must proxy with `nocanon`.

After any Apache change, check it:

```bash
curl -sI 'https://ark.digital.utsc.utoronto.ca/ark:/61220/utsc1?' | head -1
# expect: HTTP/1.1 200  (text/plain metadata)   NOT a 302
```

`resolve_diff` covers this too (inflections are checked by default) and is the
better check.

## Cutover

The new system runs alongside the old one and only takes the domain once every
ARK is proven to resolve identically.

1. **Freeze writes on the legacy service.** Nothing may mint or bind after the
   dump is taken, or the two will diverge.

2. **Dump and restore into a scratch database:**
   ```bash
   mysqldump ark_legacy > /tmp/ark-legacy.sql
   mysql -e 'CREATE DATABASE ark_legacy_copy CHARACTER SET utf8mb4'
   mysql ark_legacy_copy < /tmp/ark-legacy.sql
   ```

3. **Import** (idempotent — rehearse it as often as you like):
   ```bash
   .venv/bin/python manage.py import_legacy \
       --legacy-url mysql://user:pw@localhost/ark_legacy_copy --dry-run
   .venv/bin/python manage.py import_legacy \
       --legacy-url mysql://user:pw@localhost/ark_legacy_copy
   .venv/bin/python manage.py ark_stats
   ```
   Around 100k ARKs / 440k rows takes roughly 15 seconds.

4. **Diff every ARK against the running legacy service.** Start with a sample,
   then run it clean over everything:
   ```bash
   .venv/bin/python manage.py resolve_diff \
       --legacy-base https://ark.digital.utsc.utoronto.ca \
       --new-base http://127.0.0.1:8000 --sample 500
   .venv/bin/python manage.py resolve_diff \
       --legacy-base https://ark.digital.utsc.utoronto.ca \
       --new-base http://127.0.0.1:8000 --out cutover-diff.csv
   ```
   It exits non-zero while anything differs, and separately if any path could
   not be fetched — a socket failure proves nothing either way, so those are
   reported apart from real differences rather than counted as passes. If you
   see them, lower `--workers`; the default of 8 can exhaust local ports when
   both services are on one host.

   Legacy answers a miss by redirecting to its own `404.php` and wraps metadata
   in `<pre>`, so those idioms are normalised before comparison; what remains is
   a real difference in what an ARK resolves to. Rehearsed against a stand-in
   legacy service over 2,000 ARKs, their qualifiers and variants, and all three
   inflections — 8,343 paths, clean — and confirmed to still fail when a single
   binding is changed.

   Do not continue until it is clean.

5. **Flip the vhost:**
   ```bash
   sudo a2dissite <legacy-site> && sudo a2ensite arkservice
   sudo systemctl reload apache2
   ```

6. **Verify in the open:**
   ```bash
   curl -sI https://ark.digital.utsc.utoronto.ca/ark:/61220/utsc1  | head -2
   curl -s  'https://ark.digital.utsc.utoronto.ca/ark:/61220/utsc1?' | head -3
   curl -s  https://ark.digital.utsc.utoronto.ca/ark:/61220/
   ```

**Rollback** is re-enabling the old site and reloading Apache. The legacy
database is never written to by any of this, so it stays a valid fallback.

## Before cutover, check who calls the old REST endpoint

This system has no HTTP API, so `admin/rest.php` disappears. Find out whether
anything depends on it first:

```bash
grep -c 'rest\.php' /var/log/apache2/*access*.log
awk '$7 ~ /rest\.php/ {print $1}' /var/log/apache2/*access*.log | sort | uniq -c | sort -rn | head
```

If real integrations show up, they need converting to a management command run
locally, or the decision to add a read-only API needs revisiting.

## Things that will bite

**`.env` must be complete.** The service refuses to start when `DJANGO_DEBUG`
is false and either `DJANGO_SECRET_KEY` or `DATABASE_URL` is missing, and says
which. That is deliberate: without the check it would come up against an empty
SQLite file, 404 every ARK, and use a well-known key that makes session cookies
forgeable.

**systemd `EnvironmentFile` is not dotenv.** systemd keeps everything after the
`=`, including inline `#` comments and trailing spaces, where python-dotenv
would strip them. A value written `DJANGO_SECRET_KEY=abc # note` differs between
the service and a manual `manage.py` run, and sessions minted under one are
invalid under the other. Keep values bare and unquoted, with no trailing
comments.

**MySQL cannot return primary keys from a bulk insert.** Anything that mints and
then immediately uses the new rows has to read them back; `mint()` does. Worth
remembering before adding another bulk write path — and worth running the test
suite against MySQL, not just SQLite, before believing it.

## Routine operations

```bash
# who has what
.venv/bin/python manage.py ark_stats

# mint a batch and produce the fill-in template
.venv/bin/python manage.py mint utsc 500 --template /tmp/batch.csv

# apply an edited file
.venv/bin/python manage.py bulk_bind utsc /tmp/batch.csv --results /tmp/out.csv

# export everything in a collection
.venv/bin/python manage.py export_arks --collection utsc --out /tmp/utsc.csv
```

## Accepted deviations from the original design note

- **Uniqueness is `(naan, identifier)`**, not `(collection, identifier)` as the
  design note said. Stricter, and it is what makes resolution unambiguous.
- **`bindings` is indexed on `name` only.** `value` is unbounded TEXT, which
  MySQL cannot index without a prefix length, so value search is a scan. At
  current scale that is about a quarter of a second over 418k rows.
- **NAA lives on the collection**, mirroring the legacy `:/naa` row, rather than
  on the organisation. Where several collections share a NAAN, `/ark:/<naan>/`
  answers with the lowest collection name, deterministically.

## Backups

The legacy service dumped the whole database before every mint and bind. That
is no longer done inline: writes are transactional and a mint can no longer
corrupt anything it did not touch. Use ordinary scheduled `mysqldump` instead —
the ARK tables are the only state, plus `MEDIA_ROOT` for uploaded CSVs.
