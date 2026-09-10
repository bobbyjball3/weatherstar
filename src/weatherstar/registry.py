"""Plugin registry: built-ins plus entry-point discovery.

Concrete plugins register themselves with the ``@plugin`` decorator:

    @plugin
    class CurrentConditionsScreen(Screen):
        name = "current_conditions"
        ...

The ``plugins`` package imports every built-in module so their registration
side effects run.  External packages can register additional plugins by
installing an entry point in the ``weatherstar.plugins`` group whose
module self-registers.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING

from weatherstar.errors import PluginNotFound

if TYPE_CHECKING:
    from weatherstar.plugin import Plugin

ENTRY_POINT_GROUP = "weatherstar.plugins"
BUILTIN_PACKAGE = "weatherstar.plugins"


class PluginRegistry:
    """Maps (kind, name) -> plugin class."""

    def __init__(self) -> None:
        self._plugins: dict[str, dict[str, type[Plugin]]] = {}

    def register(self, kind: str, name: str, cls: type[Plugin]) -> type[Plugin]:
        if not kind or not name:
            raise ValueError(f"Plugin {cls.__module__}.{cls.__qualname__} needs kind and name")
        self._plugins.setdefault(kind, {})[name] = cls
        return cls

    def get(self, kind: str, name: str) -> type[Plugin]:
        by_name = self._plugins.get(kind, {})
        try:
            return by_name[name]
        except KeyError:
            raise PluginNotFound(kind, name, available=by_name) from None

    def names(self, kind: str) -> list[str]:
        return sorted(self._plugins.get(kind, {}))

    def items(self, kind: str) -> Iterator[tuple[str, type[Plugin]]]:
        yield from sorted(self._plugins.get(kind, {}).items())

    def kinds(self) -> list[str]:
        return sorted(self._plugins)


# The process-wide registry used by the engine and by the @plugin decorator.
registry = PluginRegistry()


def plugin(cls: type[Plugin]) -> type[Plugin]:
    """Class decorator registering a concrete plugin in the global registry."""
    registry.register(cls.kind, cls.name, cls)  # type: ignore[arg-type]
    return cls


def load_builtins() -> None:
    """Import all built-in plugin modules so they self-register."""
    import importlib

    module = importlib.import_module(BUILTIN_PACKAGE)
    load_fn = getattr(module, "load_builtin_plugins", None)
    if load_fn:
        load_fn()


def load_entry_points(group: str = ENTRY_POINT_GROUP) -> list[str]:
    """Import externally-registered plugin modules from the given entry-point group."""
    from importlib import metadata

    loaded: list[str] = []
    try:
        eps = metadata.entry_points(group=group)
    except TypeError:  # pragma: no cover - older importlib.metadata API
        eps = metadata.entry_points().get(group, [])
    for ep in eps:
        try:
            ep.load()
            loaded.append(ep.name)
        except Exception:  # pragma: no cover - external plugin failures surface loudly
            raise
    return loaded


def discover() -> None:
    """Load built-ins then any externally installed plugins (idempotent-ish)."""
    load_builtins()
    load_entry_points()
