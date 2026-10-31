"""Pronostics à cote et combinés courts à cote cible.

Objectif : proposer des sélections plus rémunératrices (cote d'environ 1,40 à 2,20) qui restent solides,
et des combinés de 2 ou 3 matchs atteignant une cote cible (par exemple 2) au lieu d'empiler 8 à 10
sélections à 1,10. À cote totale égale, moins de sélections signifie moins de marge du bookmaker
cumulée et moins d'erreurs de modèle cumulées.

Aucune cote n'est inventée : la « cote de référence » est la cote bookmaker quand elle existe, sinon la
cote juste SAM (1 / probabilité), toujours signalée comme telle.
"""
from __future__ import annotations

import itertools
import math
from typing import Hashable, Mapping, Optional

from .combos import Leg, evaluate_combo

# Marchés exclus des pronostics à cote : issues trop aléatoires (nul, mi-temps exacte).
VALUE_EXCLUDED = {"X", "HT_X", "HT_1", "HT_2"}
# Marge moyenne d'un bookmaker sur un marché à deux ou trois issues (utilisée seulement pour classer,
# jamais affichée comme une cote).
TYPICAL_MARGIN = 0.05


def reference_odds(mk: Mapping) -> tuple[float, bool]:
    """(cote, True si cote bookmaker réelle) ; sinon cote juste SAM."""
    if mk.get("odds"):
        return float(mk["odds"]), True
    return 1.0 / float(mk["probability"]), False


def payout_odds(mk: Mapping) -> float:
    """Cote que l'on peut espérer jouer : cote bookmaker réelle, sinon cote juste diminuée d'une marge
    typique (sert uniquement au filtrage, jamais affichée comme une cote)."""
    odds, real = reference_odds(mk)
    return odds if real else odds * (1 - TYPICAL_MARGIN)


def value_eligible(mk: Mapping, s: Mapping) -> bool:
    if not mk.get("available") or mk["key"] in VALUE_EXCLUDED:
        return False
    if mk["key"] not in s.get("enabled_markets", [mk["key"]]):
        return False
    p = float(mk["probability"])
    if p < float(s["value_min_probability"]) or mk["confidence"]["score"] < int(s["value_min_confidence"]):
        return False
    if not float(s["value_min_odds"]) <= payout_odds(mk) <= float(s["value_max_odds"]):
        return False
    # Fiabilité : quand des cotes existent, le modèle seul doit aller dans le même sens que le marché.
    pm = mk.get("model_probability")
    if mk.get("implied_probability") is not None and pm is not None:
        if abs(float(pm) - p) > float(s["value_max_disagreement"]) or float(pm) < 0.5:
            return False
    return True


def value_score(mk: Mapping) -> float:
    """Classement : chance de passer × confiance, avec un bonus pour la cote et pour une cote réelle."""
    p = float(mk["probability"])
    conf = mk["confidence"]["score"] / 100
    odds, real = reference_odds(mk)
    ret = p * (odds if real else odds * (1 - TYPICAL_MARGIN))  # retour attendu approché
    return round(0.5 * p + 0.3 * conf + 0.2 * min(ret, 1.1), 4)


def _ref(leg: Leg) -> tuple[float, bool]:
    if leg.odds:
        return float(leg.odds), True
    return 1.0 / leg.probability, False


def target_combos(candidates: list[Leg], target: float = 2.0, min_legs: int = 2, max_legs: int = 3,
                  max_results: int = 3, min_confidence: int = 60, min_probability: float = 0.5,
                  low: float = 0.95, high: float = 1.3) -> list[dict]:
    """Combinés de `min_legs` à `max_legs` matchs différents dont la cote de référence totale est proche
    de `target` (entre target × low et target × high), classés par chance de passer."""
    lo_total, hi_total = target * low, target * high
    base = [c for c in candidates if c.confidence >= min_confidence and c.probability >= min_probability]

    def pay(c: Leg) -> float:
        o, real = _ref(c)
        return o if real else o * (1 - TYPICAL_MARGIN)

    def strength(c: Leg) -> float:
        return c.probability * (0.5 + c.confidence / 200)

    scored: list[tuple[float, tuple[Leg, ...]]] = []
    for n in range(min_legs, max_legs + 1):
        # Pour n sélections, chaque cote doit tourner autour de target^(1/n) : on ne garde que cette plage,
        # sinon les quasi-certitudes (cote 1,05) occupent tout le réservoir.
        centre = target ** (1 / n)
        lo_leg, hi_leg = centre / 1.12, centre * 1.18
        band = [c for c in base if lo_leg <= pay(c) <= hi_leg and pay(c) >= 1.1]
        by_match: dict[Hashable, list[Leg]] = {}
        for c in sorted(band, key=strength, reverse=True):
            if len(by_match.setdefault(c.match_id, [])) < 2:
                by_match[c.match_id].append(c)
        pool = sorted((c for v in by_match.values() for c in v), key=strength, reverse=True)[:40 if n == 2 else 28]
        for combo in itertools.combinations(pool, n):
            if len({c.match_id for c in combo}) < n:
                continue
            refs = [_ref(c) for c in combo]
            # Filtre sur la cote réellement jouable : cotes justes diminuées de la marge typique.
            total = math.prod(o if real else o * (1 - TYPICAL_MARGIN) for o, real in refs)
            if not lo_total <= total <= hi_total:
                continue
            p = math.prod(c.probability for c in combo)
            # Retour attendu approché (marge typique retirée des cotes justes), confiance moyenne,
            # et légère préférence pour moins de sélections.
            ret = p * math.prod(o if real else o * (1 - TYPICAL_MARGIN) for o, real in refs)
            conf = sum(c.confidence for c in combo) / (100 * n)
            score = (0.6 * p + 0.25 * min(ret, 1.1) + 0.15 * conf) * (1 - 0.03 * (n - min_legs))
            scored.append((score, combo))
    scored.sort(key=lambda t: t[0], reverse=True)

    out: list[dict] = []
    used: list[set] = []
    for _, combo in scored:
        ids = {c.match_id for c in combo}
        if any(len(ids & u) >= max(1, len(ids) - 1) for u in used):
            continue  # diversité : propositions qui ne reprennent pas les mêmes matchs
        used.append(ids)
        res = evaluate_combo(list(combo), {})
        refs = [_ref(c) for c in combo]
        res["reference_odds"] = round(math.prod(o for o, _ in refs), 2)
        res["all_bookmaker_odds"] = all(real for _, real in refs)
        res["legs_reference"] = [{"odds": round(o, 2), "bookmaker": real} for o, real in refs]
        out.append(res)
        if len(out) >= max_results:
            break
    return out


def naive_equivalent(target: float, leg_odds: float = 1.10, margin: float = TYPICAL_MARGIN) -> dict:
    """Combien de sélections à `leg_odds` faut-il pour atteindre `target`, et quelle chance réelle reste-t-il
    une fois la marge du bookmaker cumulée sur chaque sélection (cotes supposées justes à la marge près)."""
    n = max(1, math.ceil(math.log(target) / math.log(leg_odds)))
    p = math.prod([(1 - margin) / leg_odds] * n)
    return {"legs": n, "leg_odds": leg_odds, "total_odds": round(leg_odds ** n, 2), "probability": round(p, 4)}


def short_equivalent(target: float, n: int = 2, margin: float = TYPICAL_MARGIN) -> dict:
    leg = target ** (1 / n)
    p = math.prod([(1 - margin) / leg] * n)
    return {"legs": n, "leg_odds": round(leg, 2), "total_odds": round(target, 2), "probability": round(p, 4)}


def best_value_per_match(markets: list[Mapping], s: Mapping) -> Optional[Mapping]:
    cands = [m for m in markets if value_eligible(m, s)]
    return max(cands, key=value_score) if cands else None
