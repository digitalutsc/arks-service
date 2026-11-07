"""
Optional plugins (INTENTS_cli_plugin.md).

The staff command line (createcollection, mint, bind, unbind, bulk_bind,
ark_stats) is no longer part of the core: it is the separate ``arks-cli``
package, a Django app enabled with ``ARKS_PLUGINS=arks_cli`` in ``.env``. Core
keeps the operator commands that migration, cutover and maintenance need on
every server.
"""

import pytest
from django.core.management import CommandError, call_command, get_commands

from arkservice.checks import ConfigurationError
from arkservice.plugins import PLUGIN_API, plugin_apps

pytestmark = pytest.mark.django_db

OPERATOR_COMMANDS = {
    "import_legacy",
    "resolve_diff",
    "check_manifests",
    "flush_counters",
    "refresh_collection_stats",
    "prune_bulk_jobs",
    "export_arks",
}
PLUGIN_COMMANDS = {"createcollection", "mint", "bind", "unbind", "bulk_bind", "ark_stats"}


def test_the_plugin_api_has_a_version():
    assert PLUGIN_API == 1


def test_no_plugins_by_default():
    assert plugin_apps([]) == []


def test_named_plugins_are_returned_once_and_trimmed():
    # 'core' stands in for any importable app.
    assert plugin_apps([" core ", "core", ""]) == ["core"]


def test_a_plugin_that_is_not_installed_is_refused_clearly():
    with pytest.raises(ConfigurationError) as excinfo:
        plugin_apps(["arks_cli_not_installed"])
    message = str(excinfo.value)
    assert "ARKS_PLUGINS" in message
    assert "arks_cli_not_installed" in message
    assert "not installed" in message


def test_core_keeps_the_operator_commands():
    assert OPERATOR_COMMANDS <= set(get_commands())


def test_core_no_longer_has_the_staff_commands():
    assert not (PLUGIN_COMMANDS & set(get_commands()))


def test_a_staff_command_without_the_plugin_is_unknown():
    with pytest.raises(CommandError, match="Unknown command"):
        call_command("mint", "utsc", "1")


def test_startup_refuses_a_missing_plugin():
    # A fresh process, as gunicorn or manage.py would start: the settings
    # refuse to load, with the message, instead of a ModuleNotFoundError.
    import os
    import subprocess
    import sys
    from pathlib import Path

    env = {**os.environ, "ARKS_PLUGINS": "arks_cli_not_installed", "DJANGO_DEBUG": "true"}
    env.pop("PYTEST_VERSION", None)
    result = subprocess.run(
        [sys.executable, "manage.py", "check"],
        cwd=Path(__file__).resolve().parent.parent,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "ARKS_PLUGINS names arks_cli_not_installed, which is not installed" in result.stderr
