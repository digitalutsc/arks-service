"""
Optional plugins: separately installed Django apps, enabled through ``.env``.

``ARKS_PLUGINS`` lists their module names (comma-separated); each is appended to
``INSTALLED_APPS``. Empty by default, so a core installation runs exactly as it
would without the setting. The staff command line is the first plugin:
``arks-cli`` (app ``arks_cli``), which adds ``createcollection``, ``mint``,
``bind``, ``unbind``, ``bulk_bind`` and ``ark_stats`` (INTENTS_cli_plugin.md).

What a plugin may rely on is :data:`PLUGIN_API`. A plugin checks it at start-up
and refuses to run against a core it was not written for.
"""

from __future__ import annotations

import importlib.util

from arkservice.checks import ConfigurationError

#: The version of what core offers plugins: the shared services
#: (core.services, minting.minter, jobs.bulkbind, core.search), the models, and
#: the command helpers in core.management.commands._common. Raise it when a
#: change would break a plugin written against the previous version.
PLUGIN_API = 1


def plugin_apps(names: list[str]) -> list[str]:
    """
    The plugin app modules named in ``ARKS_PLUGINS``, trimmed and without repeats.

    A plugin that cannot be imported is refused here with a message that says
    what to do, rather than as a ModuleNotFoundError deep inside Django's start-up.
    """
    apps: list[str] = []
    for raw in names:
        name = raw.strip()
        if name and name not in apps:
            apps.append(name)
    missing = [name for name in apps if importlib.util.find_spec(name.split(".")[0]) is None]
    if missing:
        listed = ", ".join(missing)
        raise ConfigurationError(
            f"ARKS_PLUGINS names {listed}, which is not installed. Install it "
            "(for the command line: pip install arks-cli) or remove it from .env."
        )
    return apps
