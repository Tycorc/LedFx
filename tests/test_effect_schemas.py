"""
Every effect schema must convert to the JSON schema the API serves.

The /api/schema endpoint converts the voluptuous schema of every effect
in one go, so a single validator the converter does not know breaks the
whole endpoint, and with it the effect list in the frontend and the
server based test suite.
"""

import importlib
import pkgutil

import pytest

import ledfx.effects
from ledfx.api.utils import convertToJsonSchema
from ledfx.effects import Effect

PARTY_EFFECTS = ["disco", "light_show", "orbit", "party", "rave", "true_strobe"]


def effect_classes(module_name):
    module = importlib.import_module(f"ledfx.effects.{module_name}")
    return [
        obj
        for obj in vars(module).values()
        if isinstance(obj, type)
        and issubclass(obj, Effect)
        and obj is not Effect
        and obj.__module__ == module.__name__
        and getattr(obj, "NAME", "")
    ]


def all_effect_modules():
    return sorted(
        name
        for _, name, is_pkg in pkgutil.iter_modules(ledfx.effects.__path__)
        if not is_pkg and not name.startswith("_")
    )


@pytest.mark.parametrize("module_name", PARTY_EFFECTS)
def test_party_effect_schemas_convert(module_name):
    classes = effect_classes(module_name)
    assert classes, module_name
    for cls in classes:
        schema = convertToJsonSchema(cls.schema())
        assert "properties" in schema


@pytest.mark.parametrize("module_name", all_effect_modules())
def test_every_effect_schema_converts(module_name):
    for cls in effect_classes(module_name):
        convertToJsonSchema(cls.schema())
