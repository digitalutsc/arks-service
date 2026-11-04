# Deployment files

- `arkservice.service` — systemd unit for gunicorn
- `arkservice-worker.service` — systemd unit for the Celery worker (bulk binds, queue `celery`)
- `arkservice-beat.service` — systemd unit for Celery beat and the scheduled
  housekeeping (counter flush, stale-job reaper, session cleanup), queue
  `periodic`. Run exactly one.
- `apache-arkservice.conf` — Apache vhost (note the `nocanon` on `ProxyPass`)

These are for the bare install on a VM. The worker unit works with either
broker package, `valkey-server` (the default) or `redis-server`. Production in
Docker uses the `docker-arks-service` stack instead, with
`docker-compose.external-db.yml` pointing it at the MySQL server.

**The deployment guide lives in [../DEPLOY.md](../DEPLOY.md)** — installation for
local, Docker, CI and production, the cutover runbook, every environment
variable, and troubleshooting. Keep it as the single source of truth rather than
duplicating it here.
