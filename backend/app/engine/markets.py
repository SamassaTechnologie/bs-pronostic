"""Catalogue des marchés, calcul des probabilités et règlement des résultats."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, Optional

import numpy as np
from scipy.stats import nbinom, poisson

from .types import MatchData

MAX_GOALS = 10
GOAL_LINES = (0.5, 1.5, 2.5, 3.5)
HT_LINES = (0.5, 1.5)
CORNER_LINES = (6.5, 7.5, 8.5, 9.5, 10.5)
CARD_LINES = (2.5, 3.5, 4.5)


@dataclass(frozen=True)
class MarketSpec:
    key: str
    label: str
    short: str
    family: str  # result | double_chance | goals | btts | halftime | halftime_result | corners | cards
    group: str  # regroupement pour éviter les sélections redondantes d'un même match
    display: bool = True


FAMILY_LABELS = {
    "result": "Résultat 1X2",
    "double_chance": "Double chance",
    "goals": "Buts",
    "btts": "Les deux équipes marquent",
    "halftime": "Buts 1re mi-temps",
    "halftime_result": "Résultat mi-temps",
    "corners": "Corners",
    "cards": "Cartons",
}

MARKETS: list[MarketSpec] = [
    MarketSpec("1", "Victoire domicile (1)", "1", "result", "resultat"),
    MarketSpec("X", "Match nul (X)", "X", "result", "resultat"),
    MarketSpec("2", "Victoire extérieur (2)", "2", "result", "resultat"),
    MarketSpec("1X", "Double chance 1X", "1X", "double_chance", "resultat"),
    MarketSpec("X2", "Double chance X2", "X2", "double_chance", "resultat"),
    MarketSpec("12", "Double chance 12", "12", "double_chance", "resultat"),
    MarketSpec("O0.5", "Plus de 0,5 but", "+0,5", "goals", "buts"),
    MarketSpec("O1.5", "Plus de 1,5 buts", "+1,5", "goals", "buts"),
    MarketSpec("O2.5", "Plus de 2,5 buts", "+2,5", "goals", "buts"),
    MarketSpec("O3.5", "Plus de 3,5 buts", "+3,5", "goals", "buts"),
    MarketSpec("U2.5", "Moins de 2,5 buts", "-2,5", "goals", "buts"),
    MarketSpec("U3.5", "Moins de 3,5 buts", "-3,5", "goals", "buts"),
    MarketSpec("BTTS_Y", "Les deux équipes marquent : Oui", "BTTS Oui", "btts", "btts"),
    MarketSpec("BTTS_N", "Les deux équipes marquent : Non", "BTTS Non", "btts", "btts"),
    MarketSpec("HT_O0.5", "1re mi-temps : plus de 0,5 but", "MT +0,5", "halftime", "mi-temps"),
    MarketSpec("HT_O1.5", "1re mi-temps : plus de 1,5 but", "MT +1,5", "halftime", "mi-temps", display=False),
    MarketSpec("HT_U1.5", "1re mi-temps : moins de 1,5 but", "MT -1,5", "halftime", "mi-temps"),
    MarketSpec("HT_1", "Mi-temps : domicile en tête", "MT 1", "halftime_result", "mi-temps"),
    MarketSpec("HT_X", "Mi-temps : égalité", "MT X", "halftime_result", "mi-temps"),
    MarketSpec("HT_2", "Mi-temps : extérieur en tête", "MT 2", "halftime_result", "mi-temps"),
    MarketSpec("C_O6.5", "Plus de 6,5 corners", "+6,5 corners", "corners", "corners"),
    MarketSpec("C_O7.5", "Plus de 7,5 corners", "+7,5 corners", "corners", "corners"),
    MarketSpec("C_O8.5", "Plus de 8,5 corners", "+8,5 corners", "corners", "corners"),
    MarketSpec("C_O9.5", "Plus de 9,5 corners", "+9,5 corners", "corners", "corners"),
    MarketSpec("C_O10.5", "Plus de 10,5 corners", "+10,5 corners", "corners", "corners", display=False),
    MarketSpec("C_U10.5", "Moins de 10,5 corners", "-10,5 corners", "corners", "corners"),
    MarketSpec("K_O2.5", "Plus de 2,5 cartons", "+2,5 cartons", "cards", "cartons"),
    MarketSpec("K_O3.5", "Plus de 3,5 cartons", "+3,5 cartons", "cards", "cartons"),
    MarketSpec("K_O4.5", "Plus de 4,5 cartons", "+4,5 cartons", "cards", "cartons"),
]
MARKET_BY_KEY = {m.key: m for m in MARKETS}
DISPLAY_MARKETS = [m for m in MARKETS if m.display]
DISPLAY_KEYS = [m.key for m in DISPLAY_MARKETS]
FT_GOAL_FAMILIES = {"result", "double_chance", "goals", "btts"}


def market_label(key: str) -> str:
    spec = MARKET_BY_KEY.get(key)
    return spec.label if spec else key


# ---------------------------------------------------------------------------
# Probabilités
# ---------------------------------------------------------------------------

def score_matrix(lam: float, mu: float, rho: float = 0.0, max_goals: int = MAX_GOALS) -> np.ndarray:
    """Matrice P(score = i-j), Poisson indépendants corrigés Dixon-Coles."""
    g = np.arange(max_goals + 1)
    m = np.outer(poisson.pmf(g, lam), poisson.pmf(g, mu))
    if rho:
        m[0, 0] *= max(1.0 - lam * mu * rho, 0.0)
        m[0, 1] *= max(1.0 + lam * rho, 0.0)
        m[1, 0] *= max(1.0 + mu * rho, 0.0)
        m[1, 1] *= max(1.0 - rho, 0.0)
    return m / m.sum()


def ft_probabilities(m: np.ndarray) -> dict[str, float]:
    i, j = np.indices(m.shape)
    total = i + j
    p1 = float(m[i > j].sum())
    px = float(np.trace(m))
    p2 = float(m[i < j].sum())
    out = {"1": p1, "X": px, "2": p2, "1X": p1 + px, "X2": px + p2, "12": p1 + p2}
    for line in GOAL_LINES:
        out[f"O{line}"] = float(m[total > line].sum())
    out["U2.5"] = 1.0 - out["O2.5"]
    out["U3.5"] = 1.0 - out["O3.5"]
    btts = float(m[(i > 0) & (j > 0)].sum())
    out["BTTS_Y"] = btts
    out["BTTS_N"] = 1.0 - btts
    return out


def ht_probabilities(lam_ht: float, mu_ht: float) -> dict[str, float]:
    m = score_matrix(lam_ht, mu_ht, 0.0, 8)
    i, j = np.indices(m.shape)
    total = i + j
    o05 = float(m[total > 0.5].sum())
    o15 = float(m[total > 1.5].sum())
    return {
        "HT_O0.5": o05,
        "HT_O1.5": o15,
        "HT_U1.5": 1.0 - o15,
        "HT_1": float(m[i > j].sum()),
        "HT_X": float(np.trace(m)),
        "HT_2": float(m[i < j].sum()),
    }


def count_pmf(mean: float, dispersion: float, nmax: int) -> np.ndarray:
    k = np.arange(nmax + 1)
    if dispersion <= 1.02:
        return poisson.pmf(k, mean)
    r = mean / (dispersion - 1.0)
    p = r / (r + mean)
    return nbinom.pmf(k, r, p)


def total_count_pmf(mean_home: float, mean_away: float, dispersion: float, nmax: int = 45) -> np.ndarray:
    pmf = np.convolve(count_pmf(mean_home, dispersion, nmax), count_pmf(mean_away, dispersion, nmax))[: nmax + 1]
    return pmf / pmf.sum()


def _over(pmf: np.ndarray, line: float) -> float:
    return float(pmf[np.arange(len(pmf)) > line].sum())


def corner_probabilities(pmf: np.ndarray) -> dict[str, float]:
    out = {f"C_O{line}": _over(pmf, line) for line in CORNER_LINES}
    out["C_U10.5"] = 1.0 - out["C_O10.5"]
    return out


def card_probabilities(pmf: np.ndarray) -> dict[str, float]:
    return {f"K_O{line}": _over(pmf, line) for line in CARD_LINES}


def top_scores(m: np.ndarray, n: int = 6) -> list[dict]:
    flat = np.argsort(m, axis=None)[::-1][:n]
    out = []
    for f in flat:
        i, j = np.unravel_index(f, m.shape)
        out.append({"score": f"{i}-{j}", "probability": round(float(m[i, j]), 4)})
    return out


# ---------------------------------------------------------------------------
# Probabilité jointe (même match) à partir de la matrice des scores
# ---------------------------------------------------------------------------

def _ft_condition(key: str) -> Callable[[np.ndarray, np.ndarray], np.ndarray]:
    if key == "1":
        return lambda i, j: i > j
    if key == "X":
        return lambda i, j: i == j
    if key == "2":
        return lambda i, j: i < j
    if key == "1X":
        return lambda i, j: i >= j
    if key == "X2":
        return lambda i, j: i <= j
    if key == "12":
        return lambda i, j: i != j
    if key == "BTTS_Y":
        return lambda i, j: (i > 0) & (j > 0)
    if key == "BTTS_N":
        return lambda i, j: (i == 0) | (j == 0)
    if key.startswith("O"):
        line = float(key[1:])
        return lambda i, j: (i + j) > line
    if key.startswith("U"):
        line = float(key[1:])
        return lambda i, j: (i + j) < line
    raise KeyError(key)


def is_ft_goal_market(key: str) -> bool:
    spec = MARKET_BY_KEY.get(key)
    return bool(spec and spec.family in FT_GOAL_FAMILIES)


def joint_ft_probability(keys: Iterable[str], m: np.ndarray) -> float:
    i, j = np.indices(m.shape)
    mask = np.ones(m.shape, dtype=bool)
    for k in keys:
        mask &= _ft_condition(k)(i, j)
    return float(m[mask].sum())


# ---------------------------------------------------------------------------
# Règlement (résultat réel d'un marché)
# ---------------------------------------------------------------------------

def evaluate_market(key: str, r: MatchData) -> Optional[bool]:
    """True/False si le marché est gagné/perdu, None si la donnée n'existe pas."""
    if key.startswith("HT_"):
        if r.hthg is None or r.htag is None:
            return None
        h, a = r.hthg, r.htag
        t = h + a
        sub = key[3:]
        if sub == "1":
            return h > a
        if sub == "X":
            return h == a
        if sub == "2":
            return h < a
        if sub.startswith("O"):
            return t > float(sub[1:])
        if sub.startswith("U"):
            return t < float(sub[1:])
        return None
    if key.startswith("C_"):
        t = r.total_corners
        if t is None:
            return None
        sub = key[2:]
        return t > float(sub[1:]) if sub.startswith("O") else t < float(sub[1:])
    if key.startswith("K_"):
        t = r.total_cards
        if t is None:
            return None
        sub = key[2:]
        return t > float(sub[1:]) if sub.startswith("O") else t < float(sub[1:])
    if r.hg is None or r.ag is None:
        return None
    h, a = r.hg, r.ag
    cond = _ft_condition(key)
    return bool(cond(np.array(h), np.array(a)))
