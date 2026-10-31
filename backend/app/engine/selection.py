"""Niveaux A-D, sélection des pronostics retenus et détection des matchs à éviter."""
from __future__ import annotations

from typing import Mapping, Optional

from .markets import DISPLAY_KEYS

DEFAULT_SETTINGS: dict = {
    # Niveaux de probabilité (cahier des charges)
    "tier_a": 0.85,
    "tier_b": 0.78,
    "tier_c": 0.70,
    # Critères de sélection
    "min_probability": 0.70,
    "min_confidence": 55,
    # Exclut les marchés quasi certains sans intérêt (cote juste < 1,10, ex. +0,5 but à 95 %)
    "min_fair_odds": 1.10,
    "max_picks_per_match": 2,
    "max_daily_picks": 15,
    "days_ahead": 3,
    "enabled_markets": list(DISPLAY_KEYS),
    # Sélection SAM du jour : courte liste, critères renforcés
    "featured_min_probability": 0.75,
    "featured_min_confidence": 70,
    "featured_max_per_day": 5,
    "featured_min_fair_odds": 1.15,  # écarte les quasi-certitudes sans intérêt de la vitrine
    # Pronostics à cote : probabilité moyenne mais solide, cote plus intéressante
    "value_min_odds": 1.40,
    "value_max_odds": 2.20,
    "value_min_probability": 0.52,
    "value_min_confidence": 60,
    "value_max_per_day": 5,
    "value_max_disagreement": 0.08,  # écart maximal modèle / marché quand des cotes existent
    # Matchs à éviter
    "avoid_confidence_below": 45,
    "market_divergence_alert": 0.15,
}


def merged_settings(overrides: Optional[Mapping] = None) -> dict:
    s = dict(DEFAULT_SETTINGS)
    if overrides:
        s.update({k: v for k, v in overrides.items() if k in DEFAULT_SETTINGS})
    return s


def tier_of(p: float, s: Mapping) -> str:
    if p >= s["tier_a"]:
        return "A"
    if p >= s["tier_b"]:
        return "B"
    if p >= s["tier_c"]:
        return "C"
    return "D"


def selection_score(m: Mapping) -> float:
    """Score de classement : probabilité et confiance, petit bonus si valeur positive."""
    score = 0.55 * m["probability"] + 0.45 * (m["confidence"]["score"] / 100)
    if m.get("edge") is not None:
        score += 0.25 * max(-0.1, min(0.1, m["edge"]))
    return round(score, 4)


def eligible(m: Mapping, s: Mapping) -> bool:
    if not m.get("available"):
        return False
    if m["key"] not in s["enabled_markets"]:
        return False
    p = m["probability"]
    if p < s["min_probability"] or m["confidence"]["score"] < s["min_confidence"]:
        return False
    odds = m.get("odds")
    reference_odds = odds if odds else 1.0 / p
    if reference_odds < s["min_fair_odds"]:
        return False
    return True


def select_picks(markets: list[dict], s: Mapping) -> list[str]:
    """Au plus `max_picks_per_match` sélections, une par groupe (pas de redondance)."""
    cands = sorted((m for m in markets if eligible(m, s)), key=selection_score, reverse=True)
    picked: list[str] = []
    groups: set[str] = set()
    for m in cands:
        if m["group"] in groups:
            continue
        picked.append(m["key"])
        groups.add(m["group"])
        if len(picked) >= s["max_picks_per_match"]:
            break
    return picked


def avoid_reasons(payload: Mapping, s: Mapping) -> list[str]:
    reasons: list[str] = []
    if payload.get("status") != "ok":
        reasons.extend(payload.get("reasons") or ["Données insuffisantes"])
        return reasons
    avail = [m for m in payload.get("markets", []) if m.get("available")]
    if not avail:
        return ["Données insuffisantes"]
    best_conf = max(m["confidence"]["score"] for m in avail)
    if best_conf < s["avoid_confidence_below"]:
        reasons.append(f"Confiance trop faible sur tous les marchés (max {best_conf}/100)")
    for m in avail:
        if m["key"] in ("1", "X", "2") and m.get("implied_probability") is not None:
            if abs(m["probability"] - m["implied_probability"]) >= s["market_divergence_alert"]:
                reasons.append("Fort désaccord entre le modèle et les cotes sur le résultat")
                break
    res = {m["key"]: m["probability"] for m in avail if m["key"] in ("1", "X", "2")}
    if res and max(res.values()) < 0.42 and not payload.get("picks"):
        reasons.append("Match très équilibré : aucun résultat ne se détache")
    return reasons
