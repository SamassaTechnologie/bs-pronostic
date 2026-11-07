"""« Machine SAM » : générateur de pronostics selon les critères du membre (inspiré des générateurs à filtres).

Uniquement des données réelles :
* la probabilité, la confiance et la cote juste viennent de l'analyse SAM du match ;
* la cote bookmaker n'est utilisée que si elle a été relevée (sinon la cote juste SAM, signalée comme telle) ;
* les critères statistiques (pourcentage de l'événement sur les derniers matchs, confrontations directes, moyennes de
  buts) sont calculés sur les matchs terminés de la base ; une équipe sans assez de matchs ne passe pas le filtre
  (« données insuffisantes ») plutôt que d'être estimée.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..engine.features import TeamHistory
from ..engine.markets import evaluate_market
from ..engine.value import reference_odds
from ..models import Analysis, Competition, Match
from ..popular import is_popular
from .analysis import match_summary, match_to_data

# Événements proposés (clé SAM → libellé court)
EVENTS: dict[str, str] = {
    "1": "Victoire domicile", "X": "Match nul", "2": "Victoire extérieur",
    "1X": "Double chance 1X", "X2": "Double chance X2", "12": "Double chance 12",
    "O1.5": "Plus de 1,5 but", "O2.5": "Plus de 2,5 buts", "O3.5": "Plus de 3,5 buts",
    "U2.5": "Moins de 2,5 buts", "U3.5": "Moins de 3,5 buts",
    "BTTS_Y": "Les deux marquent : oui", "BTTS_N": "Les deux marquent : non",
    "HT_O0.5": "But en 1re mi-temps", "HT_U1.5": "Moins de 1,5 but en 1re mi-temps",
    "C_O8.5": "Plus de 8,5 corners", "C_O9.5": "Plus de 9,5 corners", "K_O3.5": "Plus de 3,5 cartons",
}
MIN_SAMPLE = 5


def _rate(key: str, ms: list) -> tuple[Optional[float], int]:
    vals = [v for v in (evaluate_market(key, m) for m in ms) if v is not None]
    return (sum(vals) / len(vals), len(vals)) if vals else (None, 0)


def _avg(ms: list, fn) -> Optional[float]:
    vals = [fn(m) for m in ms]
    return sum(vals) / len(vals) if vals else None


def generate(db: Session, now: datetime, *, events: list[str], days: int = 1, competitions: Optional[list[str]] = None,
             popular_only: bool = False, n_matches: int = 5, min_odds: float = 1.2, max_odds: float = 3.0,
             target_odds: Optional[float] = None, min_probability: float = 0.6, min_confidence: int = 55,
             last10_pct: Optional[float] = None, venue_pct: Optional[float] = None, h2h_pct: Optional[float] = None,
             min_avg_scored: Optional[float] = None, max_avg_conceded: Optional[float] = None,
             sort: str = "probability") -> dict:
    events = [e for e in events if e in EVENTS] or ["O1.5", "1X", "X2"]
    end = now + timedelta(days=days)
    q = select(Analysis).join(Match, Analysis.match_id == Match.id).join(
        Competition, Match.competition_id == Competition.id).where(
        Competition.enabled.is_(True), Match.status == "SCHEDULED", Match.kickoff > now + timedelta(minutes=10),
        Match.kickoff < end)
    if competitions:
        q = q.where(Competition.code.in_(competitions))
    analyses = [a for a in db.scalars(q.order_by(Match.kickoff)).unique()
                if (a.payload or {}).get("status") == "ok" and not (a.payload or {}).get("avoid_reasons")
                and (not popular_only or is_popular(a.match.competition.code))]
    stats_needed = any(v is not None for v in (last10_pct, venue_pct, h2h_pct, min_avg_scored, max_avg_conceded))
    history = None
    if stats_needed and analyses:
        team_ids = {a.match.home_team_id for a in analyses} | {a.match.away_team_id for a in analyses}
        past = db.scalars(select(Match).where(
            Match.status == "FINISHED", Match.kickoff >= now - timedelta(days=500),
            or_(Match.home_team_id.in_(team_ids), Match.away_team_id.in_(team_ids)))).unique().all()
        history = TeamHistory([match_to_data(m) for m in past])

    cands, rejected = [], {"probabilite": 0, "cote": 0, "statistiques": 0, "donnees": 0}
    for a in analyses:
        p, m = a.payload, a.match
        best = None
        for mk in p.get("markets", []):
            if mk["key"] not in events or not mk.get("available"):
                continue
            if mk["probability"] < min_probability or mk["confidence"]["score"] < min_confidence:
                rejected["probabilite"] += 1
                continue
            odds, real = reference_odds(mk)
            if not min_odds <= odds <= max_odds:
                rejected["cote"] += 1
                continue
            facts = {}
            if history is not None:
                h10 = history.before(m.home_team_id, m.kickoff, 10)
                a10 = history.before(m.away_team_id, m.kickoff, 10)
                hv = history.before(m.home_team_id, m.kickoff, 10, venue="home")
                av = history.before(m.away_team_id, m.kickoff, 10, venue="away")
                ok, missing = True, False
                if last10_pct is not None:
                    (rh, nh), (ra, na) = _rate(mk["key"], h10), _rate(mk["key"], a10)
                    facts["last10"] = {"home": rh, "away": ra, "n_home": nh, "n_away": na}
                    missing |= nh < MIN_SAMPLE or na < MIN_SAMPLE
                    ok &= rh is not None and ra is not None and rh >= last10_pct and ra >= last10_pct
                if venue_pct is not None:
                    (rh, nh), (ra, na) = _rate(mk["key"], hv), _rate(mk["key"], av)
                    facts["venue"] = {"home": rh, "away": ra, "n_home": nh, "n_away": na}
                    missing |= nh < MIN_SAMPLE or na < MIN_SAMPLE
                    ok &= rh is not None and ra is not None and rh >= venue_pct and ra >= venue_pct
                if h2h_pct is not None:
                    h2h = [x for x in history.before(m.home_team_id, m.kickoff, 60)
                           if {x.home_id, x.away_id} == {m.home_team_id, m.away_team_id}][:5]
                    r, n = _rate(mk["key"], h2h)
                    facts["h2h"] = {"rate": r, "n": n}
                    missing |= n < 3
                    ok &= r is not None and r >= h2h_pct
                h5, a5 = h10[:5], a10[:5]
                if min_avg_scored is not None or max_avg_conceded is not None:
                    gf = lambda t: (lambda x: x.hg if x.home_id == t else x.ag)
                    ga = lambda t: (lambda x: x.ag if x.home_id == t else x.hg)
                    facts["goals5"] = {"home_scored": _avg(h5, gf(m.home_team_id)), "away_scored": _avg(a5, gf(m.away_team_id)),
                                       "home_conceded": _avg(h5, ga(m.home_team_id)), "away_conceded": _avg(a5, ga(m.away_team_id))}
                    missing |= len(h5) < MIN_SAMPLE or len(a5) < MIN_SAMPLE
                    g = facts["goals5"]
                    if min_avg_scored is not None:
                        ok &= None not in (g["home_scored"], g["away_scored"]) and min(g["home_scored"], g["away_scored"]) >= min_avg_scored
                    if max_avg_conceded is not None:
                        ok &= None not in (g["home_conceded"], g["away_conceded"]) and max(g["home_conceded"], g["away_conceded"]) <= max_avg_conceded
                if missing:
                    rejected["donnees"] += 1
                    continue
                if not ok:
                    rejected["statistiques"] += 1
                    continue
            cand = {"match": match_summary(m), "market_key": mk["key"], "label": mk["label"],
                    "event": EVENTS[mk["key"]], "probability": mk["probability"],
                    "confidence": mk["confidence"]["score"], "odds": round(odds, 2), "bookmaker_odds": real,
                    "bookmaker": mk.get("bookmaker") if real else None, "fair_odds": mk.get("fair_odds"),
                    "is_pick": mk["key"] in (p.get("picks") or []), "facts": facts}
            if best is None or (cand["probability"], cand["odds"]) > (best["probability"], best["odds"]):
                best = cand
        if best:
            cands.append(best)

    keyf = {"odds": lambda c: -c["odds"], "confidence": lambda c: -c["confidence"],
            "kickoff": lambda c: c["match"]["kickoff"]}.get(sort, lambda c: -c["probability"])
    cands.sort(key=keyf)
    n_matches = max(1, min(int(n_matches), 20))
    chosen = []
    if target_odds:
        # combinaison la plus probable qui atteint la cote totale visée, avec le moins de matchs possible
        pool = sorted(cands, key=lambda c: -c["probability"])[:40]
        total = 1.0
        for c in sorted(pool, key=lambda c: (-c["probability"], -c["odds"])):
            if len(chosen) >= n_matches or total >= target_odds:
                break
            chosen.append(c)
            total *= c["odds"]
        if total < target_odds:
            chosen = []
    else:
        chosen = cands[:n_matches]
    prob = math.prod(c["probability"] for c in chosen) if chosen else None
    odds = math.prod(c["odds"] for c in chosen) if chosen else None
    return {"selections": chosen, "count": len(chosen), "candidates": len(cands), "matches_scanned": len(analyses),
            "total_odds": round(odds, 2) if odds else None, "probability": round(prob, 4) if prob else None,
            "all_bookmaker_odds": bool(chosen) and all(c["bookmaker_odds"] for c in chosen),
            "rejected": rejected, "target_reached": None if not target_odds else bool(chosen),
            "events": EVENTS}
