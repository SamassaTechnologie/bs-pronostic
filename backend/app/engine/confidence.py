"""Indice de confiance (0-100), distinct de la probabilité.

Une probabilité de 85 % issue de 6 matchs et en désaccord avec le marché ne
mérite pas la même confiance qu'une probabilité de 80 % issue de 60 matchs et
cohérente avec les cotes. L'indice combine cinq composantes :

1. Volume de données      : nombre de matchs des deux équipes dans la fenêtre du modèle.
2. Actualité              : fraîcheur des données (dernier match joué, dernière synchronisation).
3. Stabilité              : accord entre le modèle et la fréquence observée récemment.
4. Fiabilité du modèle    : qualité de calibration mesurée en backtest pour ce marché.
5. Cohérence avec le marché : écart avec la probabilité implicite des cotes (si disponibles).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# Fiabilité a priori par famille, utilisée tant qu'aucun backtest n'est disponible.
DEFAULT_FAMILY_RELIABILITY = {
    "result": 0.70,
    "double_chance": 0.75,
    "goals": 0.80,
    "btts": 0.70,
    "halftime": 0.65,
    "halftime_result": 0.55,
    "corners": 0.60,
    "cards": 0.50,
}

WEIGHTS = {"volume": 0.25, "fraicheur": 0.15, "stabilite": 0.20, "modele": 0.20, "marche": 0.20}


def _clip(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


@dataclass
class ConfidenceInputs:
    n_home: int
    n_away: int
    days_since_home_last: Optional[float]
    days_since_away_last: Optional[float]
    data_age_hours: Optional[float]
    p_model: float
    p_recent: Optional[float]
    n_recent: int
    model_reliability: float
    p_market: Optional[float]
    injuries_count: Optional[int] = None
    late_season: bool = False


def level_of(score: int) -> str:
    if score >= 70:
        return "Élevée"
    if score >= 50:
        return "Moyenne"
    return "Faible"


def compute_confidence(ci: ConfidenceInputs) -> dict:
    n_min = min(ci.n_home, ci.n_away)
    volume = _clip((n_min - 6) / 24)

    gaps = [d for d in (ci.days_since_home_last, ci.days_since_away_last) if d is not None]
    gap = max(gaps) if gaps else 90.0
    fresh = 1.0 if gap <= 21 else _clip(1.0 - (gap - 21) / 60, 0.2, 1.0)
    if ci.data_age_hours is not None and ci.data_age_hours > 48:
        fresh *= 0.75

    if ci.p_recent is not None and ci.n_recent >= 8:
        stability = _clip(1.0 - abs(ci.p_model - ci.p_recent) / 0.35)
    else:
        stability = 0.5

    model = _clip(ci.model_reliability)

    if ci.p_market is not None:
        d = abs(ci.p_model - ci.p_market)
        market = _clip(1.0 - (d - 0.04) / 0.16)
    else:
        market = 0.55  # inconnu : ni bonus ni forte pénalité

    comps = {"volume": volume, "fraicheur": fresh, "stabilite": stability, "modele": model, "marche": market}
    score = 100.0 * sum(WEIGHTS[k] * v for k, v in comps.items())
    notes = []
    if ci.injuries_count is not None and ci.injuries_count >= 3:
        score -= 4
        notes.append("Plusieurs absences signalées")
    if ci.late_season:
        score -= 4
        notes.append("Fin de saison : motivation variable")
    score_i = int(round(_clip(score, 0, 100)))
    labels = {
        "volume": "Volume de données",
        "fraicheur": "Actualité des données",
        "stabilite": "Stabilité des performances",
        "modele": "Fiabilité du modèle",
        "marche": "Cohérence avec le marché",
    }
    return {
        "score": score_i,
        "level": level_of(score_i),
        "components": [{"key": k, "label": labels[k], "value": round(v, 3)} for k, v in comps.items()],
        "notes": notes,
    }
