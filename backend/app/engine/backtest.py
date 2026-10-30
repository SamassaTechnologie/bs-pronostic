"""Backtest chronologique (walk-forward) et ajustement de la calibration.

Principe : pour chaque semaine, le modèle est ajusté UNIQUEMENT sur les matchs
joués avant cette semaine, puis il prédit les matchs de la semaine. On compare
ensuite les probabilités annoncées aux résultats réels. Aucune information
future n'est utilisée.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Callable, Hashable, Iterable, Mapping, Optional

import numpy as np

from .calibration import (CALIBRATED_KEYS, PlattCalibrator, apply_calibration, brier_score,
                          expected_calibration_error, fit_platt, log_loss, reliability_table)
from .features import TeamHistory, h2h_matches
from .markets import evaluate_market
from .predictor import EngineParams, LeagueModels, fit_league_models, raw_probabilities
from .types import MatchData


class Records:
    """Stockage compact des prédictions hors échantillon."""

    def __init__(self) -> None:
        self.rows: list[dict] = []  # une ligne par match : {"mid", "comp", "date", "raw": {...}, "y": {...}}

    def add(self, mid: Hashable, comp: Hashable, date: datetime, raw: Mapping[str, float], ys: Mapping[str, int]):
        self.rows.append({"mid": mid, "comp": comp, "date": date, "raw": dict(raw), "y": dict(ys)})

    def __len__(self) -> int:
        return len(self.rows)

    def split(self, when: datetime) -> tuple["Records", "Records"]:
        a, b = Records(), Records()
        for r in self.rows:
            (a if r["date"] < when else b).rows.append(r)
        return a, b

    def arrays(self, key: str, calibrators: Optional[Mapping[str, PlattCalibrator]] = None):
        ps, ys = [], []
        for r in self.rows:
            if key not in r["y"]:
                continue
            probs = apply_calibration(r["raw"], calibrators) if calibrators else r["raw"]
            if key in probs:
                ps.append(probs[key])
                ys.append(r["y"][key])
        return np.array(ps, dtype=float), np.array(ys, dtype=float)


def walk_forward(matches_by_comp: Mapping[Hashable, list[MatchData]], start: datetime, end: datetime,
                 params: EngineParams = EngineParams(), step_days: int = 7,
                 progress: Optional[Callable[[str], None]] = None) -> Records:
    rec = Records()
    for comp, ms in matches_by_comp.items():
        ms = sorted(ms, key=lambda m: m.kickoff)
        history = TeamHistory(ms)
        warm: Optional[LeagueModels] = None
        t = start
        n_pred = 0
        while t < end:
            t_next = t + timedelta(days=step_days)
            test = [m for m in ms if t <= m.kickoff < t_next and m.finished]
            if test:
                lm = fit_league_models(comp, ms, t, params, warm)
                if lm.goals is not None:
                    warm = lm
                    for m in test:
                        rp = raw_probabilities(lm, m.home_id, m.away_id, params,
                                               h2h_matches(history, m.home_id, m.away_id, m.kickoff))
                        if rp is None:
                            continue
                        ys = {}
                        for k in rp["raw"]:
                            y = evaluate_market(k, m)
                            if y is not None:
                                ys[k] = int(y)
                        rec.add(m.id, comp, m.kickoff, rp["raw"], ys)
                        n_pred += 1
            t = t_next
        if progress:
            progress(f"{comp}: {n_pred} matchs prédits")
    return rec


def fit_calibrators(rec: Records, min_n: int = 300, keys: Iterable[str] = CALIBRATED_KEYS) -> dict[str, PlattCalibrator]:
    cals = {}
    for k in keys:
        p, y = rec.arrays(k)
        if len(p) >= min_n:
            cals[k] = fit_platt(p, y)
    return cals


def market_metrics(rec: Records, keys: Iterable[str],
                   calibrators: Optional[Mapping[str, PlattCalibrator]] = None) -> dict[str, dict]:
    out = {}
    for k in keys:
        p, y = rec.arrays(k, calibrators)
        if len(p) == 0:
            continue
        base = float(y.mean())
        ref = base * (1 - base)
        b = brier_score(p, y)
        out[k] = {
            "n": int(len(p)), "base_rate": round(base, 4), "mean_predicted": round(float(p.mean()), 4),
            "brier": round(b, 5), "log_loss": round(log_loss(p, y), 5),
            "brier_skill": round(1 - b / ref, 4) if ref > 0 else None,
            "ece": round(expected_calibration_error(p, y), 4),
        }
    return out


def tier_report(rec: Records, calibrators: Mapping[str, PlattCalibrator], keys: Iterable[str],
                thresholds: Mapping[str, float]) -> dict:
    """Fréquence réelle observée par niveau (A/B/C) sur toutes les prédictions."""
    buckets = {"A": [], "B": [], "C": []}
    for k in keys:
        p, y = rec.arrays(k, calibrators)
        for pi, yi in zip(p, y):
            if pi >= thresholds["tier_a"]:
                buckets["A"].append((pi, yi))
            elif pi >= thresholds["tier_b"]:
                buckets["B"].append((pi, yi))
            elif pi >= thresholds["tier_c"]:
                buckets["C"].append((pi, yi))
    out = {}
    for t, vals in buckets.items():
        if vals:
            arr = np.array(vals)
            out[t] = {"n": int(len(arr)), "mean_predicted": round(float(arr[:, 0].mean()), 4),
                      "observed_frequency": round(float(arr[:, 1].mean()), 4)}
    return out


def reliability_from_metrics(metrics: Mapping[str, dict]) -> dict[str, float]:
    """Fiabilité (0-1) par marché utilisée dans l'indice de confiance."""
    rel = {}
    for k, m in metrics.items():
        ece = m.get("ece") or 0.0
        bss = m.get("brier_skill") or 0.0
        score = 0.6 * max(0.0, 1 - ece / 0.05) + 0.4 * max(0.0, min(1.0, bss / 0.15))
        rel[k] = round(float(np.clip(score, 0.3, 0.95)), 3)
    return rel


def reliability_rows(rec: Records, key: str, calibrators: Optional[Mapping[str, PlattCalibrator]] = None):
    p, y = rec.arrays(key, calibrators)
    return reliability_table(p, y)
