# Deployment files

- `arkservice.service` — systemd unit for gunicorn
- `arkservice-worker.service` — systemd unit for the Celery worker
- `apache-arkservice.conf` — Apache vhost (note the `nocanon` on `ProxyPass`)

**The deployment guide lives in [../DEPLOY.md](../DEPLOY.md)** — installation for
local, Docker, CI and production, the cutover runbook, every environment
variable, and troubleshooting. Keep it as the single source of truth rather than
duplicating it here.
