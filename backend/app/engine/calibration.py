"""Calibration des probabilités et métriques (Brier, Log Loss, fiabilité).

Méthode : régression logistique de Platt par marché, p' = σ(a·logit(p) + b),
ajustée sur des prédictions « hors échantillon » (backtest chronologique).
Un a priori (pénalité L2 vers a=1, b=0) évite le sur-ajustement quand peu de
données sont disponibles.

L'application conserve la cohérence entre marchés :
  * 1X2 renormalisé (somme = 1) puis double chance déduite ;
  * lignes « plus de » forcées décroissantes (P(+1,5) ≥ P(+2,5) …) ;
  * marchés complémentaires déduits (Moins de = 1 − Plus de, BTTS Non = 1 − Oui).
"""
from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Mapping, Optional

import numpy as np
from scipy.optimize import minimize
from scipy.special import expit

EPS = 1e-6

# Marchés effectivement calibrés ; les autres sont déduits.
CALIBRATED_KEYS = [
    "1", "X", "2",
    "O0.5", "O1.5", "O2.5", "O3.5",
    "BTTS_Y",
    "HT_O0.5", "HT_O1.5", "HT_1", "HT_X", "HT_2",
    "C_O6.5", "C_O7.5", "C_O8.5", "C_O9.5", "C_O10.5",
    "K_O2.5", "K_O3.5", "K_O4.5",
]


@dataclass
class PlattCalibrator:
    a: float = 1.0
    b: float = 0.0
    n: int = 0

    def __call__(self, p: float) -> float:
        p = min(max(float(p), EPS), 1 - EPS)
        z = self.a * math.log(p / (1 - p)) + self.b
        return float(expit(z))


def fit_platt(p: Iterable[float], y: Iterable[float], l2: float = 2.0) -> PlattCalibrator:
    p = np.clip(np.asarray(list(p), dtype=float), EPS, 1 - EPS)
    y = np.asarray(list(y), dtype=float)
    x = np.log(p / (1 - p))

    def f(theta: np.ndarray) -> tuple[float, np.ndarray]:
        a, b = theta
        q = np.clip(expit(a * x + b), EPS, 1 - EPS)
        nll = -float(np.sum(y * np.log(q) + (1 - y) * np.log(1 - q)))
        nll += l2 * ((a - 1.0) ** 2 + b ** 2)
        r = q - y
        grad = np.array([float(np.sum(r * x)) + 2 * l2 * (a - 1.0), float(np.sum(r)) + 2 * l2 * b])
        return nll, grad

    res = minimize(f, np.array([1.0, 0.0]), jac=True, method="L-BFGS-B",
                   bounds=[(0.3, 2.5), (-2.0, 2.0)])
    return PlattCalibrator(a=float(res.x[0]), b=float(res.x[1]), n=int(len(y)))


def _monotone(values: list[float]) -> list[float]:
    out: list[float] = []
    for v in values:
        out.append(min(v, out[-1]) if out else v)
    return out


def apply_calibration(raw: Mapping[str, float], cals: Mapping[str, PlattCalibrator]) -> dict[str, float]:
    out = dict(raw)

    def c(k: str) -> float:
        return cals[k](raw[k]) if k in cals else float(raw[k])

    if all(k in raw for k in ("1", "X", "2")):
        v = np.array([c("1"), c("X"), c("2")])
        v = v / v.sum()
        out["1"], out["X"], out["2"] = (float(x) for x in v)
        out["1X"] = out["1"] + out["X"]
        out["X2"] = out["X"] + out["2"]
        out["12"] = out["1"] + out["2"]

    def lines(prefix: str, ls: Iterable[str]) -> None:
        keys = [f"{prefix}{x}" for x in ls if f"{prefix}{x}" in raw]
        for k, v in zip(keys, _monotone([c(k) for k in keys])):
            out[k] = v

    lines("O", ["0.5", "1.5", "2.5", "3.5"])
    if "O2.5" in out:
        out["U2.5"] = 1.0 - out["O2.5"]
    if "O3.5" in out:
        out["U3.5"] = 1.0 - out["O3.5"]
    if "BTTS_Y" in raw:
        out["BTTS_Y"] = c("BTTS_Y")
        out["BTTS_N"] = 1.0 - out["BTTS_Y"]

    lines("HT_O", ["0.5", "1.5"])
    if "HT_O0.5" in out and "O0.5" in out:
        out["HT_O0.5"] = min(out["HT_O0.5"], out["O0.5"])
    if "HT_O1.5" in out:
        out["HT_O1.5"] = min(out["HT_O1.5"], out.get("HT_O0.5", 1.0))
        out["HT_U1.5"] = 1.0 - out["HT_O1.5"]
    if all(k in raw for k in ("HT_1", "HT_X", "HT_2")):
        v = np.array([c("HT_1"), c("HT_X"), c("HT_2")])
        v = v / v.sum()
        out["HT_1"], out["HT_X"], out["HT_2"] = (float(x) for x in v)

    lines("C_O", ["6.5", "7.5", "8.5", "9.5", "10.5"])
    if "C_O10.5" in out:
        out["C_U10.5"] = 1.0 - out["C_O10.5"]
    lines("K_O", ["2.5", "3.5", "4.5"])
    return out


# ---------------------------------------------------------------------------
# Métriques
# ---------------------------------------------------------------------------

def brier_score(p: Iterable[float], y: Iterable[float]) -> float:
    p = np.asarray(list(p), dtype=float)
    y = np.asarray(list(y), dtype=float)
    return float(np.mean((p - y) ** 2)) if len(p) else float("nan")


def log_loss(p: Iterable[float], y: Iterable[float]) -> float:
    p = np.clip(np.asarray(list(p), dtype=float), EPS, 1 - EPS)
    y = np.asarray(list(y), dtype=float)
    if not len(p):
        return float("nan")
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def reliability_table(p: Iterable[float], y: Iterable[float], edges: Optional[list[float]] = None) -> list[dict]:
    p = np.asarray(list(p), dtype=float)
    y = np.asarray(list(y), dtype=float)
    edges = edges or [0.0, 0.5, 0.6, 0.7, 0.78, 0.85, 0.9, 0.95, 1.0001]
    rows = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (p >= lo) & (p < hi)
        n = int(m.sum())
        rows.append({
            "low": round(lo, 3), "high": round(min(hi, 1.0), 3), "n": n,
            "mean_predicted": float(p[m].mean()) if n else None,
            "observed_frequency": float(y[m].mean()) if n else None,
        })
    return rows


def expected_calibration_error(p: Iterable[float], y: Iterable[float], n_bins: int = 10) -> float:
    p = np.asarray(list(p), dtype=float)
    y = np.asarray(list(y), dtype=float)
    if not len(p):
        return float("nan")
    bins = np.minimum((p * n_bins).astype(int), n_bins - 1)
    ece = 0.0
    for b in range(n_bins):
        m = bins == b
        if m.any():
            ece += m.mean() * abs(p[m].mean() - y[m].mean())
    return float(ece)


# ---------------------------------------------------------------------------
# Sérialisation
# ---------------------------------------------------------------------------

DEFAULT_CALIBRATION_PATH = Path(__file__).with_name("default_calibration.json")


def calibrators_from_dict(d: Mapping) -> dict[str, PlattCalibrator]:
    cals = {}
    for k, v in (d.get("calibrators") or {}).items():
        cals[k] = PlattCalibrator(a=float(v["a"]), b=float(v["b"]), n=int(v.get("n", 0)))
    return cals


def calibrators_to_dict(cals: Mapping[str, PlattCalibrator]) -> dict:
    return {k: asdict(v) for k, v in cals.items()}


def load_default_calibration() -> dict:
    """Charge la calibration par défaut (issue d'un backtest réel), si présente."""
    if DEFAULT_CALIBRATION_PATH.exists():
        return json.loads(DEFAULT_CALIBRATION_PATH.read_text(encoding="utf-8"))
    return {}
