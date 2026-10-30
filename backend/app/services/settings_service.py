"""Lecture / écriture des réglages (seuils, marchés, fournisseurs actifs)."""
from __future__ import annotations

from typing import Any, Mapping

from sqlalchemy.orm import Session

from ..engine.markets import DISPLAY_KEYS
from ..engine.selection import DEFAULT_SETTINGS, merged_settings
from ..models import Setting

PROVIDER_NAMES = ("football_data_co_uk", "api_football", "football_data_org")

BOUNDS = {
    "tier_a": (0.5, 0.99), "tier_b": (0.5, 0.99), "tier_c": (0.5, 0.99),
    "min_probability": (0.5, 0.99), "min_confidence": (0, 100), "min_fair_odds": (1.0, 3.0),
    "max_picks_per_match": (1, 5), "max_daily_picks": (1, 200), "days_ahead": (1, 7),
    "avoid_confidence_below": (0, 100),
    "featured_min_probability": (0.5, 0.99), "featured_min_confidence": (0, 100), "featured_max_per_day": (0, 20),
    "featured_min_fair_odds": (1.0, 3.0), "market_divergence_alert": (0.05, 0.5),
}


def get_selection_settings(db: Session) -> dict:
    row = db.get(Setting, "selection")
    return merged_settings(row.value if row else None)


def update_selection_settings(db: Session, changes: Mapping[str, Any]) -> dict:
    current = get_selection_settings(db)
    errors = []
    for k, v in changes.items():
        if k not in DEFAULT_SETTINGS:
            errors.append(f"Réglage inconnu : {k}")
            continue
        if k == "enabled_markets":
            if not isinstance(v, list) or any(x not in DISPLAY_KEYS for x in v):
                errors.append("Liste de marchés invalide")
                continue
            current[k] = v
            continue
        lo, hi = BOUNDS[k]
        try:
            num = float(v)
        except (TypeError, ValueError):
            errors.append(f"Valeur invalide pour {k}")
            continue
        if not lo <= num <= hi:
            errors.append(f"{k} doit être compris entre {lo} et {hi}")
            continue
        current[k] = int(num) if isinstance(DEFAULT_SETTINGS[k], int) else num
    if not current["tier_a"] > current["tier_b"] > current["tier_c"]:
        errors.append("Les seuils doivent respecter A > B > C")
    if errors:
        raise ValueError("; ".join(errors))
    row = db.get(Setting, "selection")
    if row is None:
        db.add(Setting(key="selection", value=current))
    else:
        row.value = dict(current)
    db.commit()
    return current


def get_provider_flags(db: Session) -> dict:
    row = db.get(Setting, "providers")
    flags = {n: True for n in PROVIDER_NAMES}
    if row and isinstance(row.value, dict):
        flags.update({k: bool(v) for k, v in row.value.items() if k in PROVIDER_NAMES})
    return flags


def set_provider_flag(db: Session, name: str, enabled: bool) -> dict:
    if name not in PROVIDER_NAMES:
        raise ValueError("Fournisseur inconnu")
    flags = get_provider_flags(db)
    flags[name] = bool(enabled)
    row = db.get(Setting, "providers")
    if row is None:
        db.add(Setting(key="providers", value=flags))
    else:
        row.value = dict(flags)
    db.commit()
    return flags
