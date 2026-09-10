# ruff: noqa
"""Vulture whitelist: names used dynamically that static analysis cannot see.

This file is parsed by ``vulture`` (see ``[tool.vulture]`` in ``pyproject.toml``)
and never imported.  It exists so the dynamic plugin/dispatch wiring in this
codebase does not drown the real dead-code report.  Ruff skips it
(``extend-exclude``), so the undefined ``_`` below is intentional.
"""

# Pydantic's configuration object, consumed by Pydantic itself.
model_config

# Pydantic validators, invoked by the framework.
_._exactly_one_accessor

# Screen layout variants: dispatched by name (Theme.variants -> Screen.compose).
_.compose_4000
_.compose_3000

# http.server hooks overridden for the streaming server, called by the stdlib.
server_version
_.do_GET
_.do_HEAD
_.log_message

# Pytest module marker and Pydantic fields on test-only models.
pytestmark
mode
interval
