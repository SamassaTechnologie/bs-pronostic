"""Backtest des marchés étendus (catalogue « Jouer ») sur données réelles, sans information future.

Pour chaque match rejoué semaine par semaine, le modèle ajusté sur le passé donne la probabilité de chaque
marché étendu ; on la compare au résultat réel (scores final et mi-temps). Calibration de Platt ajustée sur
[start, split), évaluée sur [split, end). Un marché est déclaré « validé » (utilisable dans les pronostics) s'il
a assez de cas hors échantillon et une calibration fidèle, y compris dans la zone des fortes probabilités.

    python -m scripts.backtest_extended data/Matches.csv --write
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.engine import extended as ext  # noqa: E402
from app.engine.calibration import brier_score, expected_calibration_error, fit_platt  # noqa: E402
from app.engine.features import TeamHistory, h2h_matches  # noqa: E402
from app.engine.predictor import EngineParams, fit_league_models, raw_probabilities  # noqa: E402
from scripts.backtest_csv import load_matches  # noqa: E402

UTC = timezone.utc
OUT = Path(__file__).resolve().parents[1] / "app" / "engine" / "extended_calibration.json"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("csv")
    ap.add_argument("--divisions", default="E0,E1,D1,D2,I1,I2,SP1,SP2,F1,F2,N1,B1,P1,T1,G1,SC0")
    ap.add_argument("--start", default="2024-07-01")
    ap.add_argument("--split", default="2025-07-01")
    ap.add_argument("--end", default="2026-09-05")
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()
    start = datetime.fromisoformat(args.start).replace(tzinfo=UTC)
    split = datetime.fromisoformat(args.split).replace(tzinfo=UTC)
    end = datetime.fromisoformat(args.end).replace(tzinfo=UTC)
    params = EngineParams()
    since = (start - pd.Timedelta(days=params.window_days + 10)).strftime("%Y-%m-%d")
    by_comp, _ = load_matches(args.csv, set(args.divisions.split(",")), since)
    print(f"Chargé : {sum(len(v) for v in by_comp.values())} matchs", flush=True)

    # key -> liste de (date, p, y) ; issues remboursées exclues, probabilité conditionnelle au non-remboursement
    data: dict[str, list] = defaultdict(list)
    t0 = time.time()
    n_pred = 0
    for comp, ms in by_comp.items():
        ms = sorted(ms, key=lambda m: m.kickoff)
        history = TeamHistory(ms)
        warm = None
        t = start
        while t < end:
            t_next = t + timedelta(days=7)
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
                        rows = ext.compute(rp["matrix"], rp["lam"], rp["mu"], rp["ht"])
                        for r in rows:
                            res = ext.settle(r["key"], m.hg, m.ag, m.hthg, m.htag)
                            if res is None or res == "void":
                                continue
                            p = r["probability"] / max(1e-9, 1 - r["void_probability"])
                            data[r["key"]].append((m.kickoff, min(max(p, 1e-4), 1 - 1e-4), 1 if res == "won" else 0))
                        n_pred += 1
            t = t_next
        print(f"   {comp}: fait ({time.time() - t0:.0f}s)", flush=True)
    print(f"{n_pred} matchs rejoués en {time.time() - t0:.0f}s", flush=True)

    report: dict[str, dict] = {}
    for key, rows in data.items():
        fit = [(p, y) for d, p, y in rows if d < split]
        test = [(p, y) for d, p, y in rows if d >= split]
        if len(fit) < 300 or len(test) < 300:
            continue
        cal = fit_platt([p for p, _ in fit], [y for _, y in fit])
        pt = np.array([p for p, _ in test])
        yt = np.array([y for _, y in test])
        pc = np.array([cal(p) for p in pt])
        base = float(yt.mean())
        hi = pc >= 0.70
        hi_n = int(hi.sum())
        rec = {
            "n_test": int(len(yt)), "base_rate": round(base, 4),
            "ece_raw": round(float(expected_calibration_error(pt, yt)), 4),
            "ece_cal": round(float(expected_calibration_error(pc, yt)), 4),
            "brier_cal": round(float(brier_score(pc, yt)), 5),
            "brier_base": round(float(brier_score(np.full_like(yt, base, dtype=float), yt)), 5),
            "high_n": hi_n,
            "high_predicted": round(float(pc[hi].mean()), 4) if hi_n else None,
            "high_observed": round(float(yt[hi].mean()), 4) if hi_n else None,
            "platt": {"a": round(cal.a, 5), "b": round(cal.b, 5), "n": int(len(fit))},
        }
        gap_hi = abs(rec["high_predicted"] - rec["high_observed"]) if hi_n >= 100 else None
        rec["validated"] = bool(rec["ece_cal"] <= 0.02 and rec["brier_cal"] < rec["brier_base"]
                                and (hi_n < 100 or gap_hi <= 0.03))
        report[key] = rec
    ok = sorted(k for k, v in report.items() if v["validated"])
    print(f"{len(report)} marchés évalués, {len(ok)} validés")
    for k in sorted(report, key=lambda k: report[k]["ece_cal"]):
        v = report[k]
        print(f"{k:16s} n={v['n_test']:5d} base={v['base_rate']:.3f} ece {v['ece_raw']:.3f}->{v['ece_cal']:.3f} "
              f"brier {v['brier_cal']:.4f}/{v['brier_base']:.4f} hi={v['high_n']} "
              f"{v['high_predicted']}/{v['high_observed']} {'OK' if v['validated'] else '--'}")
    if args.write:
        OUT.write_text(json.dumps({"description": "Calibration des marchés étendus (backtest walk-forward)",
                                   "period": {"start": args.start, "split": args.split, "end": args.end},
                                   "matches": n_pred, "markets": report}, ensure_ascii=False, indent=1))
        print("Écrit :", OUT)


if __name__ == "__main__":
    main()
