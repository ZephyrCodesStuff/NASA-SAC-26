"""Farmer crop preferences for the rotation optimizer.

They are stored next to the farmer's soil/utility inputs in the plot's `soil_override` JSON (no extra PocketBase
field), under the keys below. Everything that treats `soil_override` as soil values must drop them first.
"""

from __future__ import annotations

from typing import Any

WHITELIST_KEY = "crop_whitelist"  # "only grow these" -> analytics-api `preferred_candidate_crops`
BLACKLIST_KEY = "crop_blacklist"  # "never grow these" -> analytics-api `excluded_crops`
CROP_PREFERENCE_KEYS = (WHITELIST_KEY, BLACKLIST_KEY)


def soil_values_only(override: dict[str, Any] | None) -> dict[str, Any]:
    """`soil_override` without the crop preference keys."""
    if not isinstance(override, dict):
        return {}
    return {k: v for k, v in override.items() if k not in CROP_PREFERENCE_KEYS}


def crop_preferences(override: dict[str, Any] | None) -> tuple[list[str], list[str]]:
    """(whitelist, blacklist) as clean lists of crop ids; a crop in both lists counts as blocked."""
    if not isinstance(override, dict):
        return [], []

    def clean(raw: Any) -> list[str]:
        if not isinstance(raw, list):
            return []
        out: list[str] = []
        for item in raw:
            if isinstance(item, str) and item.strip() and item.strip() not in out:
                out.append(item.strip())
        return out

    blacklist = clean(override.get(BLACKLIST_KEY))
    whitelist = [c for c in clean(override.get(WHITELIST_KEY)) if c not in blacklist]
    return whitelist, blacklist
