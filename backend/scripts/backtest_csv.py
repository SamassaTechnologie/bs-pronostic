"""Backtest hors ligne sur un fichier CSV historique réel.

Formats acceptés :
  * CSV football-data.co.uk (colonnes Div, Date, HomeTeam, AwayTeam, FTHG, FTAG, HTHG, HC, HY, HR, AvgH…)
  * CSV « Club-Football-Match-Data » (github.com/xgabora, licence MIT, dérivé de football-data.co.uk)

Exemple :
    python -m scripts.backtest_csv data/Matches.csv --divisions E0,D1,I1,SP1,F1 \
        --start 2024-07-01 --split 2025-07-01 --end 2026-09-05 --write-default

Le script :
  1. rejoue le moteur semaine par semaine (sans information future) ;
  2. mesure Brier, Log Loss, calibration, fréquences réelles par niveau A/B/C ;
  3. ajuste la calibration sur la période [start, split) et l'évalue sur [split, end) ;
  4. compare au marché (cotes moyennes) quand elles sont présentes ;
  5. avec --write-default, enregistre app/engine/default_calibration.json.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.engine.backtest import (Records, fit_calibrators, market_metrics, reliability_from_metrics,  # noqa: E402
                                 reliability_rows, tier_report, walk_forward)
from app.engine.calibration import CALIBRATED_KEYS, DEFAULT_CALIBRATION_PATH, brier_score, log_loss  # noqa: E402
from app.engine.predictor import EngineParams  # noqa: E402
from app.engine.selection import DEFAULT_SETTINGS  # noqa: E402
from app.engine.types import MatchData  # noqa: E402

UTC = timezone.utc


def _int(v):
    try:
        if v is None or (isinstance(v, float) and math.isnan(v)):
            return None
        return int(v)
    except (TypeError, ValueError):
        return None


def load_matches(path: str, divisions: set[str], since: str) -> tuple[dict, dict]:
    df = pd.read_csv(path, low_memory=False)
    if "Division" in df.columns:  # format xgabora
        df = df.rename(columns={
            "Division": "Div", "MatchDate": "Date", "FTHome": "FTHG", "FTAway": "FTAG", "HTHome": "HTHG",
            "HTAway": "HTAG", "HomeCorners": "HC", "AwayCorners": "AC", "HomeYellow": "HY", "AwayYellow": "AY",
            "HomeRed": "HR", "AwayRed": "AR", "OddHome": "AvgH", "OddDraw": "AvgD", "OddAway": "AvgA",
            "Over25": "Avg>2.5", "Under25": "Avg<2.5"})
        df["Date"] = pd.to_datetime(df["Date"])
    else:
        df["Date"] = pd.to_datetime(df["Date"], dayfirst=True)
    df = df[df["Div"].isin(divisions) & (df["Date"] >= since)]
    by_comp: dict[str, list[MatchData]] = defaultdict(list)
    odds: dict = {}
    for i, d in enumerate(df.to_dict("records")):
        hg, ag = _int(d.get("FTHG")), _int(d.get("FTAG"))
        if hg is None or ag is None:
            continue
        mid = f"{d['Div']}-{i}"
        ko = d["Date"].to_pydatetime().replace(tzinfo=UTC)
        by_comp[d["Div"]].append(MatchData(
            id=mid, competition_id=d["Div"], kickoff=ko, home_id=d["HomeTeam"], away_id=d["AwayTeam"],
            hg=hg, ag=ag, hthg=_int(d.get("HTHG")), htag=_int(d.get("HTAG")), hc=_int(d.get("HC")),
            ac=_int(d.get("AC")), hy=_int(d.get("HY")), ay=_int(d.get("AY")), hr=_int(d.get("HR")),
            ar=_int(d.get("AR"))))
        o = {k: d.get(c) for k, c in (("1", "AvgH"), ("X", "AvgD"), ("2", "AvgA"), ("O2.5", "Avg>2.5"),
                                       ("U2.5", "Avg<2.5"))}
        if all(isinstance(v, (int, float)) and not math.isnan(v) and v > 1 for v in o.values()):
            odds[mid] = o
    return by_comp, odds


def market_benchmark(rec: Records, odds: dict, cals) -> dict:
    """Compare le modèle et les cotes moyennes sur les mêmes matchs (1X2 et +2,5)."""
    from app.engine.calibration import apply_calibration
    out = {}
    for keys in (("1", "X", "2"), ("O2.5", "U2.5")):
        pm, pk, ys = [], [], []
        for r in rec.rows:
            o = odds.get(r["mid"])
            if not o or not all(k in r["y"] for k in keys):
                continue
            q = np.array([1 / o[k] for k in keys])
            q = q / q.sum()
            cal = apply_calibration(r["raw"], cals)
            for k, qi in zip(keys, q):
                pm.append(cal[k])
                pk.append(qi)
                ys.append(r["y"][k])
        if ys:
            name = "1X2" if len(keys) == 3 else "+/-2,5"
            out[name] = {"n": len(ys) // len(keys),
                         "brier_model": round(brier_score(pm, ys), 5), "brier_market": round(brier_score(pk, ys), 5),
                         "logloss_model": round(log_loss(pm, ys), 5), "logloss_market": round(log_loss(pk, ys), 5)}
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("csv")
    ap.add_argument("--divisions", default="E0,E1,D1,D2,I1,I2,SP1,SP2,F1,F2,N1,B1,P1,T1,G1,SC0")
    ap.add_argument("--start", default="2024-07-01")
    ap.add_argument("--split", default="2025-07-01")
    ap.add_argument("--end", default="2026-09-05")
    ap.add_argument("--xi", type=float, default=EngineParams().xi)
    ap.add_argument("--prior-sd", type=float, default=EngineParams().prior_sd_goals)
    ap.add_argument("--write-default", action="store_true")
    ap.add_argument("--json-out", default="")
    args = ap.parse_args()

    divs = set(args.divisions.split(","))
    start = datetime.fromisoformat(args.start).replace(tzinfo=UTC)
    split = datetime.fromisoformat(args.split).replace(tzinfo=UTC)
    end = datetime.fromisoformat(args.end).replace(tzinfo=UTC)
    since = (start - pd.Timedelta(days=EngineParams().window_days + 10)).strftime("%Y-%m-%d")
    t0 = time.time()
    by_comp, odds = load_matches(args.csv, divs, since)
    print(f"Chargé : {sum(len(v) for v in by_comp.values())} matchs, {len(by_comp)} championnats "
          f"({time.time() - t0:.1f}s)")
    params = EngineParams(xi=args.xi, prior_sd_goals=args.prior_sd)
    t0 = time.time()
    rec = walk_forward(by_comp, start, end, params, progress=lambda s: print("  ", s, flush=True))
    print(f"Walk-forward : {len(rec)} matchs prédits en {time.time() - t0:.0f}s")

    fit_part, test_part = rec.split(split)
    cals_train = fit_calibrators(fit_part)
    keys = CALIBRATED_KEYS
    raw_test = market_metrics(test_part, keys)
    cal_test = market_metrics(test_part, keys, cals_train)
    print(f"\nHors échantillon ({args.split} → {args.end}), {len(test_part)} matchs")
    print(f"{'marché':8} {'n':>6} {'fréq':>6} {'brier brut':>11} {'brier cal':>10} {'LL brut':>8} {'LL cal':>8} "
          f"{'ECE brut':>8} {'ECE cal':>8}")
    for k in keys:
        if k in raw_test:
            a, b = raw_test[k], cal_test[k]
            print(f"{k:8} {a['n']:6d} {a['base_rate']:6.3f} {a['brier']:11.5f} {b['brier']:10.5f} "
                  f"{a['log_loss']:8.4f} {b['log_loss']:8.4f} {a['ece']:8.4f} {b['ece']:8.4f}")
    tiers = tier_report(test_part, cals_train, [k for k in keys], DEFAULT_SETTINGS)
    print("\nNiveaux (hors échantillon, calibré) :", json.dumps(tiers, ensure_ascii=False))
    bench = market_benchmark(test_part, odds, cals_train)
    print("Comparaison au marché (cotes moyennes) :", json.dumps(bench, ensure_ascii=False))

    if args.write_default or args.json_out:
        cals_all = fit_calibrators(rec)
        reliability = reliability_from_metrics(cal_test)
        payload = {
            "description": "Calibration de Platt par marché, ajustée par backtest chronologique sur données réelles.",
            "source": "football-data.co.uk (via github.com/xgabora/Club-Football-Match-Data-2000-2025, licence MIT)",
            "divisions": sorted(divs),
            "period": {"start": args.start, "split": args.split, "end": args.end},
            "params": {"xi": params.xi, "prior_sd_goals": params.prior_sd_goals, "window_days": params.window_days},
            "n_matches": len(rec),
            "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "calibrators": {k: {"a": round(v.a, 5), "b": round(v.b, 5), "n": v.n} for k, v in cals_all.items()},
            "out_of_sample": {"raw": raw_test, "calibrated": cal_test, "tiers": tiers, "market_benchmark": bench,
                              "reliability_O2.5": reliability_rows(test_part, "O2.5", cals_train)},
            "reliability": reliability,
        }
        out_path = Path(args.json_out) if args.json_out else DEFAULT_CALIBRATION_PATH
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\nÉcrit : {out_path}")


if __name__ == "__main__":
    main()
