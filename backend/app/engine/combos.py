"""Générateur et évaluateur de combinés.

Règles :
* Matchs différents : événements supposés indépendants (approximation
  raisonnable entre rencontres distinctes) → produit des probabilités.
* Même match : JAMAIS de multiplication naïve. Pour les marchés « temps
  réglementaire » liés aux buts (1X2, double chance, plus/moins, BTTS) la
  probabilité jointe est lue dans la matrice des scores du modèle ; pour les
  autres combinaisons (corners + buts, mi-temps + résultat…) la corrélation
  n'est pas modélisée et la combinaison est refusée.
"""
from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field
from typing import Hashable, Optional

import numpy as np

from .markets import is_ft_goal_market, joint_ft_probability


@dataclass
class Leg:
    match_id: Hashable
    market_key: str
    label: str
    probability: float  # probabilité calibrée
    confidence: int
    odds: Optional[float] = None
    raw_probability: Optional[float] = None
    match_label: str = ""
    competition: str = ""
    kickoff: str = ""
    tier: str = ""


@dataclass
class MatchModel:
    """Matrice des scores du match (pour la probabilité jointe intra-match)."""

    matrix: np.ndarray
    raw: dict = field(default_factory=dict)


def risk_level(p: float) -> str:
    if p >= 0.60:
        return "Modéré"
    if p >= 0.40:
        return "Élevé"
    if p >= 0.25:
        return "Très élevé"
    return "Extrême"


def evaluate_combo(legs: list[Leg], models: dict[Hashable, MatchModel]) -> dict:
    warnings: list[str] = []
    errors: list[str] = []
    by_match: dict[Hashable, list[Leg]] = {}
    for leg in legs:
        by_match.setdefault(leg.match_id, []).append(leg)

    group_probs: list[float] = []
    same_match = False
    for mid, group in by_match.items():
        if len(group) == 1:
            group_probs.append(group[0].probability)
            continue
        same_match = True
        keys = [g.market_key for g in group]
        if len(set(keys)) < len(keys):
            errors.append("Sélection en double sur un même match")
            continue
        if not all(is_ft_goal_market(k) for k in keys) or mid not in models:
            errors.append(f"{group[0].match_label} : corrélation non modélisée entre ces marchés du même match")
            continue
        mm = models[mid]
        joint_raw = joint_ft_probability(keys, mm.matrix)
        if joint_raw <= 0:
            errors.append(f"{group[0].match_label} : sélections incompatibles (probabilité nulle)")
            continue
        # Conditionnelle issue de la matrice, marginale calibrée de la jambe la plus restrictive.
        anchor = min(group, key=lambda g: g.probability)
        raw_anchor = anchor.raw_probability or float(mm.raw.get(anchor.market_key, anchor.probability))
        cond = min(1.0, joint_raw / max(raw_anchor, 1e-9))
        joint = min(anchor.probability * cond, min(g.probability for g in group))
        naive = math.prod(g.probability for g in group)
        if joint_raw >= 0.995 * min(float(mm.raw.get(k, 1.0)) for k in keys):
            warnings.append(f"{group[0].match_label} : sélections redondantes (l'une implique l'autre)")
        else:
            warnings.append(
                f"{group[0].match_label} : probabilité jointe {round(joint * 100)} % calculée sur la matrice "
                f"des scores (le produit naïf donnerait {round(naive * 100)} %)")
        group_probs.append(joint)

    if errors:
        return {"valid": False, "errors": errors, "warnings": warnings, "legs": [leg.__dict__ for leg in legs]}

    p = float(math.prod(group_probs))
    all_odds = all(leg.odds for leg in legs)
    total_odds = None
    if all_odds and not same_match:
        total_odds = round(math.prod(leg.odds for leg in legs), 2)
    elif all_odds and same_match:
        warnings.append("Cote totale non calculable : les bookmakers appliquent une cote spécifique "
                        "aux combinaisons d'un même match")
    elif not all_odds:
        warnings.append("Cote totale indisponible : au moins une sélection n'a pas de cote")
    ev = (p * total_odds - 1) if total_odds else None
    too_risky = p < 0.35
    if too_risky:
        warnings.append("Combiné trop risqué : moins de 35 % de chances estimées de passer")
    weak = [leg for leg in legs if leg.confidence < 50]
    if weak:
        warnings.append(f"{len(weak)} sélection(s) avec une confiance faible")
    return {
        "valid": True,
        "legs": [leg.__dict__ for leg in legs],
        "n_legs": len(legs),
        "probability": round(p, 4),
        "fair_odds": round(1 / p, 2) if p > 0 else None,
        "total_odds": total_odds,
        "expected_value": round(ev, 4) if ev is not None else None,
        "risk": risk_level(p),
        "too_risky": too_risky,
        "independent": not same_match,
        "warnings": warnings,
        "errors": [],
    }


def generate_combos(candidates: list[Leg], n_legs: int, mode: str = "prudent", max_results: int = 3,
                    min_confidence: int = 55) -> list[dict]:
    """Combinés de `n_legs` matchs différents (une sélection par match)."""
    best_per_match: dict[Hashable, Leg] = {}
    for c in candidates:
        if c.confidence < min_confidence:
            continue
        if mode == "valeur" and not (c.odds and c.probability * c.odds > 1.0):
            continue
        cur = best_per_match.get(c.match_id)
        key = (c.probability * c.confidence) if mode == "prudent" else (c.probability * c.odds - 1)
        if cur is None:
            best_per_match[c.match_id] = c
        else:
            cur_key = (cur.probability * cur.confidence) if mode == "prudent" else (cur.probability * cur.odds - 1)
            if key > cur_key:
                best_per_match[c.match_id] = c
    pool = list(best_per_match.values())
    if len(pool) < n_legs:
        return []
    if mode == "prudent":
        pool.sort(key=lambda c: c.probability * (0.5 + c.confidence / 200), reverse=True)
    else:
        pool.sort(key=lambda c: c.probability * c.odds - 1, reverse=True)
    pool = pool[: max(n_legs + 4, 8)]
    scored = []
    for combo in itertools.combinations(pool, n_legs):
        p = math.prod(c.probability for c in combo)
        if mode == "prudent":
            score = p * (sum(c.confidence for c in combo) / (100 * n_legs))
        else:
            odds = math.prod(c.odds for c in combo)
            score = p * odds - 1
        scored.append((score, combo))
    scored.sort(key=lambda t: t[0], reverse=True)
    out, seen = [], []
    for _, combo in scored:
        ids = {c.match_id for c in combo}
        if any(len(ids & s) >= n_legs - 1 and n_legs > 2 for s in seen):
            continue  # diversité : éviter des combinés quasi identiques
        seen.append(ids)
        out.append(evaluate_combo(list(combo), {}))
        if len(out) >= max_results:
            break
    return out
