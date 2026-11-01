"""Marchés étendus admis dans les pronostics : uniquement ceux validés par le backtest hors échantillon
(calibration fidèle sur 5 539 matchs), avec la probabilité calibrée. Les marchés à remboursement possible
(lignes asiatiques entières) restent réservés au jeu « Jouer »."""
from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Optional

import numpy as np

from . import extended as ext
from .calibration import PlattCalibrator
from .confidence import level_of
from .markets import score_matrix
from .selection import selection_score, tier_of

PATH = Path(__file__).with_name("extended_calibration.json")


@lru_cache
def validated() -> dict[str, dict]:
    try:
        data = json.loads(PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {k: v for k, v in (data.get("markets") or {}).items() if v.get("validated")}


def calibrate(key: str, p: float) -> Optional[float]:
    v = validated().get(key)
    if not v:
        return None
    c = PlattCalibrator(a=v["platt"]["a"], b=v["platt"]["b"], n=v["platt"]["n"])
    return c(p)


def extended_markets(payload: dict, settings: dict, home: str, away: str) -> list[dict]:
    """Marchés étendus validés, prêts à entrer dans payload["markets"] (forme identique aux marchés principaux)."""
    eg = payload.get("expected_goals")
    if not eg or not validated():
        return []
    rho = (payload.get("league") or {}).get("rho", 0.0) or 0.0
    ht = payload.get("expected_ht_goals")
    rows = ext.compute(score_matrix(eg["home"], eg["away"], rho), eg["home"], eg["away"],
                       (ht["home"], ht["away"]) if ht else None)
    mks = {m["key"]: m for m in payload.get("markets", []) if m.get("available")}
    ref_goals = mks.get("O2.5") or mks.get("1")
    ref_half = mks.get("HT_O0.5") or ref_goals
    if ref_goals is None:
        return []
    meta = json.loads(PATH.read_text(encoding="utf-8")) if PATH.exists() else {}
    n_test = None
    out = []
    for r in rows:
        if r["void_probability"] > 0:
            continue
        p = calibrate(r["key"], r["probability"])
        if p is None:
            continue
        p = float(np.clip(p, 0.001, 0.999))
        if p < float(settings["min_probability"]) or 1 / p < float(settings["min_fair_odds"]):
            continue
        spec = ext.BY_KEY[r["key"]]
        ref = ref_half if spec.halves else ref_goals
        conf = dict(ref["confidence"])
        conf["score"] = max(0, int(conf["score"]) - 5)  # légère prudence : marché dérivé du modèle de buts
        conf["level"] = level_of(conf["score"])
        conf["notes"] = list(conf.get("notes") or []) + ["Marché étendu : probabilité dérivée du modèle de buts, calibrée par backtest"]
        v = validated()[r["key"]]
        n_test = v["n_test"]
        label = r["label"].replace("{E1}", home).replace("{E2}", away)
        m = {"key": r["key"], "label": label, "short": r["label"].replace("{E1}", "1").replace("{E2}", "2"),
             "family": r["family"], "group": f"x:{r['family']}", "available": True, "extended": True,
             "probability": round(p, 4), "raw_probability": r["probability"], "model_probability": round(p, 4),
             "consensus": False, "tier": tier_of(p, settings), "confidence": conf,
             "odds": None, "bookmaker": None, "odds_source": None, "implied_probability": None, "edge": None,
             "fair_odds": round(1 / p, 3), "recent": {},
             "explanation": (f"Marché étendu calculé sur le modèle de buts SAM : probabilité {round(p * 100)} % "
                             f"(niveau {tier_of(p, settings)}). Calibration vérifiée hors échantillon sur "
                             f"{n_test} matchs (écart moyen {round(v['ece_cal'] * 100, 1)} point(s)).").replace(" %", " %"),
             "factors_for": [], "factors_against": []}
        m["score"] = selection_score(m)
        out.append(m)
    return out


def add_to_payload(payload: dict, settings: dict) -> None:
    """Ajoute les marchés étendus validés et autorise au plus UN pronostic étendu par match, retenu seulement s'il
    est plus solide que les pronostics principaux restants."""
    from .selection import eligible

    if payload.get("status") != "ok" or not settings.get("extended_in_picks", True):
        return
    m = payload.get("match") or {}
    home, away = (m.get("home") or {}).get("name", "Équipe 1"), (m.get("away") or {}).get("name", "Équipe 2")
    xs = extended_markets(payload, settings, home, away)
    if not xs:
        return
    payload["markets"].extend(xs)
    s2 = dict(settings)
    s2["enabled_markets"] = list(settings["enabled_markets"]) + [x["key"] for x in xs]
    cands = sorted((x for x in xs if eligible(x, s2)), key=lambda x: x["score"], reverse=True)
    if not cands:
        return
    best = cands[0]
    picks = list(payload.get("picks") or [])
    by_key = {mk["key"]: mk for mk in payload["markets"]}
    if len(picks) < int(settings["max_picks_per_match"]):
        picks.append(best["key"])
    else:
        weakest = min(picks, key=lambda k: by_key[k].get("score") or 0)
        if best["score"] > (by_key[weakest].get("score") or 0) + 0.02:
            picks[picks.index(weakest)] = best["key"]
    payload["picks"] = picks
