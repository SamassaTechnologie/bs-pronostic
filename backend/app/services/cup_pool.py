"""Coupes internationales (Ligue des champions, Ligue Europa, coupes CAF…) : historique commun.

Problème : une coupe seule ne contient que quelques matchs par équipe (3 en début de phase de ligue), d'où
« Données insuffisantes » pour la plupart des affiches. Solution classique (cf. classements Elo des clubs) :
ajuster le modèle de buts sur les matchs de la coupe ET les matchs de championnat des clubs engagés ; les matchs
de coupe relient les championnats entre eux et rendent les forces comparables.

Activation : réglage « cup_pooling » (désactivé par défaut) après un backtest hors échantillon (cup_backtest) qui
compare, sur les matchs de coupe passés, le modèle « coupe seule » et le modèle « historique commun ».
"""
from __future__ import annotations

import logging
import math
import threading
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..engine.markets import score_matrix
from ..engine.predictor import EngineParams, fit_league_models
from ..engine.types import MatchData
from ..models import Competition, Match, Setting, utcnow

log = logging.getLogger("sam.cups")
INTERNATIONAL = {"Europe", "Afrique", "Monde", "Amérique du Sud", "Asie"}
KEY = "cup_backtest"


def is_cup(comp: Competition) -> bool:
    return comp.country in INTERNATIONAL


def enabled(db: Session) -> bool:
    row = db.get(Setting, "cup_pooling")
    return bool(row and isinstance(row.value, dict) and row.value.get("enabled"))


def pooled_matches(db: Session, comp: Competition, since: datetime, until: datetime) -> tuple[list[Match], list[Match]]:
    """(matchs de la coupe, matchs de la coupe + championnats complets des clubs engagés) sur la fenêtre."""
    cup = db.scalars(select(Match).where(Match.competition_id == comp.id, Match.status == "FINISHED",
                                         Match.kickoff >= since, Match.kickoff < until)).unique().all()
    upcoming = db.scalars(select(Match).where(Match.competition_id == comp.id, Match.kickoff >= until - timedelta(days=1),
                                              Match.kickoff < until + timedelta(days=30))).unique().all()
    teams = {m.home_team_id for m in cup + upcoming} | {m.away_team_id for m in cup + upcoming}
    if not teams:
        return cup, cup
    leagues = set(db.scalars(select(Match.competition_id).join(Competition, Match.competition_id == Competition.id).where(
        Match.status == "FINISHED", Match.kickoff >= since, Match.kickoff < until,
        Competition.country.not_in(INTERNATIONAL),
        (Match.home_team_id.in_(teams)) | (Match.away_team_id.in_(teams)))).all())
    domestic = db.scalars(select(Match).where(Match.competition_id.in_(leagues), Match.status == "FINISHED",
                                              Match.kickoff >= since, Match.kickoff < until)).unique().all() if leagues else []
    return cup, cup + domestic


def _probs(lm, h, a) -> Optional[tuple[float, float, float]]:
    """(victoire domicile, nul, victoire extérieur) selon le modèle de buts."""
    import numpy as np
    g = lm.goals
    if g is None or not g.has_team(h) or not g.has_team(a):
        return None
    lam, mu = g.rates(h, a)
    m = score_matrix(lam, mu, g.rho)
    return float(np.tril(m, -1).sum()), float(np.trace(m)), float(np.triu(m, 1).sum())


def cup_backtest(db: Session, code: str = "UCL", months: int = 18, params: EngineParams = EngineParams()) -> dict:
    """Backtest chronologique (hors échantillon) sur les matchs de coupe des derniers mois : log loss et Brier 1X2,
    nombre de matchs pronostiquables (chaque équipe ≥ min_team_matches) pour les deux variantes."""
    from ..services.analysis import match_to_data
    comp = db.scalar(select(Competition).where(Competition.code == code))
    if comp is None:
        return {"status": "error", "message": f"Compétition {code} introuvable"}
    now = utcnow()
    since = now - timedelta(days=30 * months)
    window = timedelta(days=params.window_days + 30)
    cup_all = db.scalars(select(Match).where(Match.competition_id == comp.id, Match.status == "FINISHED",
                                             Match.kickoff >= since - window, Match.kickoff < now)).unique().all()
    evals = sorted((m for m in cup_all if m.kickoff >= since and m.home_goals is not None), key=lambda m: m.kickoff)
    weeks: dict[str, list[Match]] = defaultdict(list)
    for m in evals:
        weeks[m.kickoff.strftime("%G-%V")].append(m)
    res = {v: {"n": 0, "ll": 0.0, "brier": 0.0} for v in ("coupe", "commun")}
    common = {v: {"n": 0, "ll": 0.0, "brier": 0.0} for v in ("coupe", "commun")}
    for wk, ms in sorted(weeks.items()):
        as_of = min(m.kickoff for m in ms) - timedelta(hours=1)
        cup, pooled = pooled_matches(db, comp, as_of - window, as_of)
        fits = {}
        for v, rows in (("coupe", cup), ("commun", pooled)):
            data: list[MatchData] = [match_to_data(r) for r in rows]
            for d in data:
                d.competition_id = comp.id
            try:
                fits[v] = fit_league_models(comp.id, data, as_of, params)
            except Exception:
                log.exception("Backtest coupes : ajustement impossible (%s, %s)", v, wk)
                fits[v] = None
        for m in ms:
            y = 0 if m.home_goals > m.away_goals else (1 if m.home_goals == m.away_goals else 2)
            got = {}
            for v, lm in fits.items():
                if lm is None or lm.goals is None:
                    continue
                g = lm.goals
                if min(g.team_matches(m.home_team_id), g.team_matches(m.away_team_id)) < params.min_team_matches:
                    continue
                p = _probs(lm, m.home_team_id, m.away_team_id)
                if p is None:
                    continue
                got[v] = p
                r = res[v]
                r["n"] += 1
                r["ll"] += -math.log(max(p[y], 1e-9))
                r["brier"] += sum((p[k] - (1 if k == y else 0)) ** 2 for k in range(3))
            if len(got) == 2:
                for v, p in got.items():
                    c = common[v]
                    c["n"] += 1
                    c["ll"] += -math.log(max(p[y], 1e-9))
                    c["brier"] += sum((p[k] - (1 if k == y else 0)) ** 2 for k in range(3))

    def fmt(d):
        return {v: {"matchs": x["n"], "log_loss": round(x["ll"] / x["n"], 4) if x["n"] else None,
                    "brier": round(x["brier"] / x["n"], 4) if x["n"] else None} for v, x in d.items()}
    out = {"status": "ok", "competition": code, "evalues": len(evals), "semaines": len(weeks),
           "toutes_couvertures": fmt(res), "matchs_communs": fmt(common), "generated_at": now.isoformat()}
    cc, cp = out["matchs_communs"]["coupe"], out["matchs_communs"]["commun"]
    out["verdict"] = ("commun_meilleur" if cc["log_loss"] is not None and cp["log_loss"] is not None
                      and cp["log_loss"] <= cc["log_loss"] + 0.002 else "a_verifier")
    return out


def run_backtest_in_background(code: str = "UCL", months: int = 18) -> None:
    from ..db import SessionLocal

    def job():
        with SessionLocal() as db:
            try:
                r = cup_backtest(db, code, months)
            except Exception as exc:
                log.exception("Backtest coupes")
                r = {"status": "error", "message": str(exc)}
            row = db.get(Setting, KEY)
            if row is None:
                db.add(Setting(key=KEY, value=r))
            else:
                row.value = r
            db.commit()
            log.info("Backtest coupes : %s", r)

    threading.Thread(target=job, daemon=True, name="cup-backtest").start()
