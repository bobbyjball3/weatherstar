"""Base plugin abstraction shared by Screen/Component/Media/Datasource/Sequence.

A plugin is a Pydantic model that declares a stable ``name`` (its identifier in
config and sequences) plus typed config fields.  Declaring an annotated field
with a default makes it optional in config; a field without a default is
required.  Sensitive fields are typed ``SecretStr`` so ``repr``/``str`` and the
logging redaction processor never leak them.

Because plugins are Pydantic models they are validated/coerced by Pydantic and
instantiated with ``cls.model_validate(scope_dict)``.  Non-config metadata such
as ``kind``/``name``/``media``/``datasources`` are declared ``ClassVar`` so they
never become fields.
"""

from __future__ import annotations

from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, SecretStr

from weatherstar.errors import InvalidConfiguration
from weatherstar.logging_setup import get_logger

_log = get_logger("weatherstar.plugin")


class Plugin(BaseModel):
    """Base class for all configurable, registered plugins."""

    model_config = ConfigDict(
        # Accept unknown keys in a config scope and arbitrary runtime
        # attributes (e.g. engine-injected state / test stubs) without treating
        # them as validated fields.
        extra="allow",
        # Some plugins carry non-config types on instances (sessions, fonts).
        arbitrary_types_allowed=True,
    )

    #: Kind of plugin ("screen", "component", "media", "datasource", "sequence").
    kind: ClassVar[str | None] = None
    #: Stable identifier referenced from configuration and sequences.
    name: ClassVar[str | None] = None

    # -- Configuration ---------------------------------------------------

    @classmethod
    def config_scope(cls) -> str:
        """The config section name this plugin instance maps to."""
        kind = cls.kind or "plugin"
        name = cls.name or cls.__name__
        return f"{kind}.{name}"

    @classmethod
    def is_sensitive_field(cls, field_name: str) -> bool:
        field = cls.model_fields.get(field_name)
        return field is not None and _is_secret_annotation(field.annotation)

    @classmethod
    def from_config(cls, values: dict[str, Any]) -> Plugin:
        """Instantiate and validate this plugin from a config scope dict.

        Raises :class:`InvalidConfiguration` (with an example snippet) when the
        scope is missing required keys or contains invalid values.
        """
        from pydantic import ValidationError

        try:
            instance = cls.model_validate(values)
        except ValidationError as exc:
            scope = cls.config_scope()
            missing: list[str] = []
            details: list[str] = []
            for error in exc.errors():
                loc = error.get("loc") or ()
                key = str(loc[0]) if loc else "?"
                if error.get("type") == "missing":
                    missing.append(key)
                else:
                    details.append(f"{key}: {error.get('msg', 'invalid value')}")
            parts = [f"{cls.__name__} {cls.name!r} has invalid configuration in scope [{scope}]."]
            if details:
                parts.append("Errors: " + "; ".join(details))
            raise InvalidConfiguration("\n".join(parts), scope=scope, missing=missing) from exc
        _log.info(
            "plugin_configured",
            kind=cls.kind,
            name=cls.name,
            scope=cls.config_scope(),
            config=instance.config_repr(),
        )
        return instance

    # -- Introspection / logging ----------------------------------------

    def config_repr(self) -> str:
        """Render this plugin's config values with sensitive ones masked."""
        parts: list[str] = []
        for key, field in type(self).model_fields.items():
            value = getattr(self, key, None)
            if isinstance(value, SecretStr):
                parts.append(f"{key}=***")
            else:
                parts.append(f"{key}={value!r}")
        return ", ".join(parts)

    def __repr__(self) -> str:
        name = getattr(self, "name", type(self).__name__)
        body = self.config_repr()
        return f"<{type(self).__name__} {name!r} [{body}]>"

    def __str__(self) -> str:
        return self.__repr__()


def _is_secret_annotation(annotation: Any) -> bool:
    import typing

    if annotation is SecretStr:
        return True
    if typing.get_origin(annotation) is typing.Union:
        return any(_is_secret_annotation(arg) for arg in typing.get_args(annotation))
    return False
