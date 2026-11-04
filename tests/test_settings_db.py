"""
Database connection settings.

Production may reach MySQL over the network (the Docker stack's
docker-compose.external-db.yml points at an existing server). Connections are
kept open for DB_CONN_MAX_AGE seconds, and a persistent connection that the
server or a firewall has dropped in the meantime fails the next request with
"MySQL server has gone away". Health checks make Django test a reused
connection first and reconnect instead.
"""

from django.conf import settings


def test_reused_connections_are_health_checked_by_default():
    assert settings.DATABASES["default"]["CONN_HEALTH_CHECKS"] is True


def test_connections_are_still_persistent():
    # Health checks only matter for connections that outlive a request.
    assert settings.DATABASES["default"]["CONN_MAX_AGE"] > 0


def test_mysql_connections_time_out_rather_than_hang():
    # A server that stops answering must not hold request threads until the
    # OS abandons the TCP connection.
    import pytest

    db = settings.DATABASES["default"]
    if db["ENGINE"] != "django.db.backends.mysql":
        pytest.skip("MySQL-only options")
    for option in ("connect_timeout", "read_timeout", "write_timeout"):
        assert db["OPTIONS"][option] > 0
