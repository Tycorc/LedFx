"""Preset lookup and effect-config comparison (ignoring UI-only keys)."""

from collections.abc import Mapping

from ledfx.configuration.models import Preset
from ledfx.configuration.plugin import PluginConfig
from ledfx.presets import ledfx_presets
from ledfx.utils import generate_defaults

UI_ONLY_KEYS_IGNORED_FOR_CONFIG_COMPARISON = [
    "advanced",
    "diag",
    "gradient_name",  # UI field that gets expanded to gradient value
]


def filter_config_for_comparison(config: object) -> dict[str, object]:
    """Filter out UI-only keys from effect configuration for comparison."""
    if isinstance(config, PluginConfig):
        config = config.as_dict()  # a running effect's config
    if not isinstance(config, dict):
        return {}
    return {
        k: v
        for k, v in config.items()
        if k not in UI_ONLY_KEYS_IGNORED_FOR_CONFIG_COMPARISON
    }


def configs_match(config1: object, config2: object) -> bool:
    """Compare two effect configurations, ignoring UI-only keys."""
    return filter_config_for_comparison(config1) == filter_config_for_comparison(
        config2
    )


def find_matching_preset(
    ledfx_presets: Mapping[str, Mapping[str, object]],
    user_presets: dict[str, dict[str, Preset]],
    ledfx_effects: object,
    effect_type: str,
    effect_config: object,
) -> tuple[str, str] | tuple[None, None]:
    """Return (preset_id, category), or (None, None), ignoring UI-only keys."""
    if not isinstance(effect_config, dict):
        return None, None

    ledfx_defaults = generate_defaults(ledfx_presets, ledfx_effects, effect_type)
    for preset_id, preset_data in ledfx_defaults.items():
        preset_config = preset_data.get("config")  # absent: compares as {}
        if configs_match(preset_config, effect_config):
            return preset_id, "ledfx_presets"

    if effect_type in user_presets:
        for preset_id, preset_data in user_presets[effect_type].items():
            if configs_match(preset_data.config, effect_config):
                return preset_id, "user_presets"

    return None, None


def preset_category(
    user_presets: dict[str, dict[str, Preset]], category: str
) -> Mapping[str, Mapping[str, object]]:
    """The presets of a category: the built-in dicts or config.user_presets."""
    return user_presets if category == "user_presets" else ledfx_presets


def preset_config(
    user_presets: dict[str, dict[str, Preset]],
    category: str,
    effect_id: str,
    preset_id: str,
) -> dict[str, object]:
    """A stored preset's effect config. Raises KeyError if it does not exist."""
    if category == "user_presets":
        return user_presets[effect_id][preset_id].config
    return ledfx_presets[effect_id][preset_id]["config"]
