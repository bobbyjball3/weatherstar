"""Tests for the Plugin base: Pydantic fields, binding, repr masking."""

import pytest
from pydantic import SecretStr

from weatherstar import InvalidConfiguration
from weatherstar.plugin import Plugin


class Widget(Plugin):
    kind = "widget"
    name = "sample"
    timeout: int = 10
    retries: int = 0


def test_model_fields_collects_annotations():
    assert set(Widget.model_fields) == {"timeout", "retries"}


def test_inherited_fields_merged():
    class FancyWidget(Widget):
        mode: str = "a"

    assert set(FancyWidget.model_fields) == {"timeout", "retries", "mode"}
    assert FancyWidget().timeout == 10


def test_model_validate_merges_defaults():
    instance = Widget.model_validate({"timeout": 30})
    assert instance.timeout == 30
    assert instance.retries == 0


class KeyedWidget(Plugin):
    kind = "widget"
    name = "sample"
    api_key: SecretStr


def test_from_config_required_missing_raises_with_example():
    with pytest.raises(InvalidConfiguration) as excinfo:
        KeyedWidget.from_config({})
    message = str(excinfo.value)
    assert "widget.sample" in message
    assert "api_key" in message
    assert "[widget.sample]" in message
    assert "api_key = " in message  # example snippet present


def test_config_scope_builds_kind_dot_name():
    assert Widget.config_scope() == "widget.sample"


class SecretWidget(Plugin):
    kind = "widget"
    name = "secret"
    api_key: SecretStr = SecretStr("topsecret")
    label: str = "hello"


def test_repr_masks_sensitive_values():
    text = repr(SecretWidget())
    assert "topsecret" not in text
    assert "***" in text
    assert "hello" in text


def test_str_is_safe_for_sensitive():
    assert "topsecret" not in str(SecretWidget())


def test_extra_scope_keys_not_treated_as_fields():
    instance = Widget.model_validate({"timeout": 1, "bogus": "ignored"})
    assert instance.timeout == 1
    assert "bogus" not in Widget.model_fields
    assert not hasattr(type(instance), "bogus")


def test_invalid_value_type_raises_invalid_configuration():
    with pytest.raises(InvalidConfiguration) as excinfo:
        Widget.from_config({"timeout": "not-a-number"})
    assert "widget.sample" in str(excinfo.value)
