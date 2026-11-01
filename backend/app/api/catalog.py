"""Championnats, équipes et recherche."""
from __future__ import annotations

import unicodedata
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..engine.features import TeamHistory, form_summary, standings
from ..models import Analysis, Competition, Match, Prediction, Team
from ..providers.names import normalize_team
from ..services.analysis import match_summary, match_to_data
from ..services.performance import performance, prediction_row
from .deps import get_db

router = APIRouter(prefix="/api", tags=["catalogue"])
UTC = timezone.utc


def _now() -> datetime:
    return datetime.now(UTC)


def _fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    return "".join(c for c in s if not unicodedata.combining(c)).lower().strip()


def comp_row(c: Competition) -> dict:
    return {"id": c.id, "code": c.code, "name": c.name, "country": c.country}


def _current_season(db: Session, comp_id: int) -> Optional[str]:
    return db.scalar(select(Match.season).where(Match.competition_id == comp_id, Match.season.is_not(None))
                     .order_by(Match.kickoff.desc()).limit(1))


def _picks_for(db: Session, match_ids: list[int]) -> dict[int, dict]:
    """Résumé de l'analyse (pronostics retenus) pour une liste de matchs à venir."""
    if not match_ids:
        return {}
    out = {}
    for a in db.scalars(select(Analysis).where(Analysis.match_id.in_(match_ids))).unique():
        p = a.payload or {}
        picks = []
        for mk in p.get("markets", []):
            if mk.get("available") and mk["key"] in (p.get("picks") or []):
                picks.append({"market_key": mk["key"], "label": mk["label"], "probability": mk["probability"],
                              "tier": mk["tier"], "confidence": mk["confidence"]["score"]})
        out[a.match_id] = {"status": a.status, "picks": picks, "avoid": bool(p.get("avoid_reasons")),
                           "expected_goals": p.get("expected_goals")}
    return out


def _match_with_analysis(m: Match, analyses: dict) -> dict:
    return {"match": match_summary(m), "analysis": analyses.get(m.id)}


@router.get("/competitions")
def competitions(db: Session = Depends(get_db)):
    now = _now()
    comps = db.scalars(select(Competition).where(Competition.enabled.is_(True))).all()
    upcoming = dict(db.execute(select(Match.competition_id, func.count(Match.id)).where(
        Match.status == "SCHEDULED", Match.kickoff >= now, Match.kickoff < now + timedelta(days=3))
        .group_by(Match.competition_id)).all())
    picks = defaultdict(int)
    for a in db.scalars(select(Analysis).join(Match, Analysis.match_id == Match.id).where(
            Match.kickoff >= now, Match.kickoff < now + timedelta(days=3))).unique():
        picks[a.match.competition_id] += a.n_picks
    rows = [{**comp_row(c), "upcoming": upcoming.get(c.id, 0), "picks": picks.get(c.id, 0)} for c in comps]
    rows.sort(key=lambda r: (r["country"], r["name"]))
    return {"items": rows}


@router.get("/competitions/{code}")
def competition_detail(code: str, db: Session = Depends(get_db)):
    c = db.scalar(select(Competition).where(Competition.code == code))
    if c is None or not c.enabled:
        raise HTTPException(404, "Championnat introuvable")
    now = _now()
    season = _current_season(db, c.id)
    finished = db.scalars(select(Match).where(Match.competition_id == c.id, Match.status == "FINISHED",
                                              Match.season == season)).unique().all() if season else []
    data = [match_to_data(m) for m in finished]
    table = standings(data)
    teams = {t.id: t.name for t in db.scalars(select(Team).where(Team.id.in_([r["team_id"] for r in table])))}
    history = TeamHistory(data)
    for r in table:
        r["team"] = teams.get(r["team_id"], "?")
        r["form"] = form_summary(r["team_id"], history.before(r["team_id"], now, 5)).get("sequence", "")
    n = len(data)
    stats = None
    if n:
        corners = [d.total_corners for d in data if d.total_corners is not None]
        cards = [d.total_cards for d in data if d.total_cards is not None]
        stats = {
            "matches": n,
            "avg_goals": round(sum(d.hg + d.ag for d in data) / n, 2),
            "home_win": round(sum(d.hg > d.ag for d in data) / n, 3),
            "draw": round(sum(d.hg == d.ag for d in data) / n, 3),
            "away_win": round(sum(d.hg < d.ag for d in data) / n, 3),
            "over25": round(sum(d.hg + d.ag > 2.5 for d in data) / n, 3),
            "btts": round(sum(d.hg > 0 and d.ag > 0 for d in data) / n, 3),
            "avg_corners": round(sum(corners) / len(corners), 1) if corners else None,
            "avg_cards": round(sum(cards) / len(cards), 1) if cards else None,
        }
    upcoming = db.scalars(select(Match).where(Match.competition_id == c.id, Match.status == "SCHEDULED",
                                              Match.kickoff >= now - timedelta(hours=2))
                          .order_by(Match.kickoff).limit(20)).unique().all()
    recent = db.scalars(select(Match).where(Match.competition_id == c.id, Match.status == "FINISHED")
                        .order_by(Match.kickoff.desc()).limit(12)).unique().all()
    analyses = _picks_for(db, [m.id for m in upcoming])
    perf = performance(db, competition_id=c.id)["overall"]
    return {
        "competition": comp_row(c), "season": season, "standings": table, "stats": stats,
        "upcoming": [_match_with_analysis(m, analyses) for m in upcoming],
        "recent": [match_summary(m) for m in recent],
        "performance": {k: perf[k] for k in ("total", "n", "won", "hit_rate", "avg_probability", "roi")},
    }


@router.get("/teams/{team_id}")
def team_detail(team_id: int, db: Session = Depends(get_db)):
    t = db.get(Team, team_id)
    if t is None:
        raise HTTPException(404, "Équipe introuvable")
    now = _now()
    ms = db.scalars(select(Match).where(or_(Match.home_team_id == t.id, Match.away_team_id == t.id))
                    .order_by(Match.kickoff.desc()).limit(80)).unique().all()
    finished = [m for m in ms if m.status == "FINISHED"]
    upcoming = sorted([m for m in ms if m.status == "SCHEDULED" and m.kickoff >= now - timedelta(hours=2)],
                      key=lambda m: m.kickoff)[:8]
    data = [match_to_data(m) for m in finished]
    history = TeamHistory(data)
    last10 = history.before(t.id, now, 10)
    home10 = history.before(t.id, now, 10, venue="home")
    away10 = history.before(t.id, now, 10, venue="away")
    # Championnat principal = celui où l'équipe a le plus de matchs récents
    comp_counts = defaultdict(int)
    for m in ms[:40]:
        comp_counts[m.competition_id] += 1
    main_comp = db.get(Competition, max(comp_counts, key=comp_counts.get)) if comp_counts else None
    standing = None
    if main_comp:
        season = _current_season(db, main_comp.id)
        rows = standings([match_to_data(m) for m in db.scalars(select(Match).where(
            Match.competition_id == main_comp.id, Match.status == "FINISHED", Match.season == season)).unique()])
        standing = next(({**r, "teams": len(rows)} for r in rows if r["team_id"] == t.id), None)
    analyses = _picks_for(db, [m.id for m in upcoming])
    preds = db.scalars(select(Prediction).join(Match, Prediction.match_id == Match.id).where(
        or_(Match.home_team_id == t.id, Match.away_team_id == t.id), Prediction.result.in_(["won", "lost"]))
        .order_by(Match.kickoff.desc()).limit(10)).unique().all()
    return {
        "team": {"id": t.id, "name": t.name, "country": t.country},
        "competition": comp_row(main_comp) if main_comp else None,
        "standing": standing,
        "form": {"last10": form_summary(t.id, last10), "last5": form_summary(t.id, last10[:5]),
                 "home10": form_summary(t.id, home10), "away10": form_summary(t.id, away10)},
        "upcoming": [_match_with_analysis(m, analyses) for m in upcoming],
        "recent": [match_summary(m) for m in finished[:10]],
        "predictions": [prediction_row(p) for p in preds],
    }


@router.get("/search")
def search(q: str = Query(..., min_length=2, max_length=60), db: Session = Depends(get_db)):
    """Recherche d'équipes, de championnats et de pays (insensible aux accents)."""
    fq = _fold(q)
    norm = normalize_team(q)
    comps = db.scalars(select(Competition).where(Competition.enabled.is_(True))).all()
    comp_hits = [comp_row(c) for c in comps if fq in _fold(c.name) or fq in _fold(c.country) or fq == c.code.lower()]
    countries = {c.country for c in comps}
    country_hits = sorted({c for c in countries if fq in _fold(c)})
    enabled_ids = [c.id for c in comps]
    active_team_ids = select(Match.home_team_id).where(Match.competition_id.in_(enabled_ids)).union(
        select(Match.away_team_id).where(Match.competition_id.in_(enabled_ids)))
    like = f"%{norm or fq}%"
    teams = db.scalars(select(Team).where(Team.id.in_(active_team_ids), or_(
        Team.norm_name.like(like), func.lower(Team.name).like(f"%{q.lower()}%"))).limit(30)).all()
    teams.sort(key=lambda t: (not t.norm_name.startswith(norm or fq), len(t.name)))
    now = _now()
    team_rows = []
    for t in teams[:12]:
        nxt = db.scalar(select(Match).where(or_(Match.home_team_id == t.id, Match.away_team_id == t.id),
                                            Match.status == "SCHEDULED", Match.kickoff >= now)
                        .order_by(Match.kickoff).limit(1))
        team_rows.append({"id": t.id, "name": t.name, "country": t.country,
                          "next": match_summary(nxt) if nxt else None})
    return {"query": q, "teams": team_rows, "competitions": comp_hits, "countries": country_hits}


# ---------------------------------------------------------------------------
# Fiche match avancée : tendances, forme détaillée, confrontations, classement, cotes, direct
# ---------------------------------------------------------------------------

def _team_matches(db: Session, team_id: int, before: datetime, limit: int = 40) -> list[Match]:
    return db.scalars(select(Match).where(or_(Match.home_team_id == team_id, Match.away_team_id == team_id),
                                          Match.status == "FINISHED", Match.kickoff < before)
                      .order_by(Match.kickoff.desc()).limit(limit)).unique().all()


def _form_rows(ms: list[Match], team_id: int) -> list[dict]:
    rows = []
    for m in ms:
        home = m.home_team_id == team_id
        gf, ga = (m.home_goals, m.away_goals) if home else (m.away_goals, m.home_goals)
        rows.append({
            "match_id": m.id, "date": m.kickoff.isoformat(), "competition": m.competition.name,
            "venue": "home" if home else "away", "opponent": {"id": (m.away_team if home else m.home_team).id,
                                                              "name": (m.away_team if home else m.home_team).name},
            "score": f"{m.home_goals}-{m.away_goals}", "goals_for": gf, "goals_against": ga,
            "result": "V" if gf > ga else ("N" if gf == ga else "D"),
            "ht": f"{m.ht_home_goals}-{m.ht_away_goals}" if m.ht_home_goals is not None else None,
            "corners": m.home_corners + m.away_corners if m.home_corners is not None and m.away_corners is not None else None,
            "cards": (sum(x for x in (m.home_yellow, m.away_yellow, m.home_red, m.away_red))
                      if None not in (m.home_yellow, m.away_yellow, m.home_red, m.away_red) else None),
        })
    return rows


MARKET_ORDER = ["1", "X", "2", "1X", "X2", "12", "O0.5", "O1.5", "U1.5", "O2.5", "U2.5", "O3.5", "U3.5", "O4.5", "U4.5",
                "BTTS_Y", "BTTS_N", "HT_1", "HT_X", "HT_2", "HT_O0.5", "HT_U0.5", "HT_O1.5", "HT_U1.5"]


@router.get("/matches/{match_id}/insights")
def match_insights(match_id: int, db: Session = Depends(get_db)):
    from ..engine.markets import MARKET_BY_KEY, market_label
    from ..engine.trends import h2h_trends, team_trends
    from ..models import OddsQuote
    from ..services.live import match_live_state

    m = db.get(Match, match_id)
    if m is None:
        raise HTTPException(404, "Match introuvable")
    ref = min(m.kickoff, _now() + timedelta(days=1))
    home_ms = _team_matches(db, m.home_team_id, ref)
    away_ms = _team_matches(db, m.away_team_id, ref)
    hd = [match_to_data(x) for x in home_ms]
    ad = [match_to_data(x) for x in away_ms]
    h2h = db.scalars(select(Match).where(
        or_((Match.home_team_id == m.home_team_id) & (Match.away_team_id == m.away_team_id),
            (Match.home_team_id == m.away_team_id) & (Match.away_team_id == m.home_team_id)),
        Match.status == "FINISHED", Match.kickoff < ref).order_by(Match.kickoff.desc()).limit(10)).unique().all()
    h2d = [match_to_data(x) for x in h2h]
    a = db.scalar(select(Analysis).where(Analysis.match_id == m.id))
    probs = {mk["key"]: mk["probability"] for mk in (a.payload.get("markets", []) if a else []) if mk.get("available")}

    trends = (team_trends(m.home_team.name, m.home_team_id, hd, "home", "à domicile",
                          [x for x in hd if x.home_id == m.home_team_id])
              + team_trends(m.away_team.name, m.away_team_id, ad, "away", "à l'extérieur",
                            [x for x in ad if x.away_id == m.away_team_id])
              + h2h_trends(m.home_team.name, m.away_team.name, m.home_team_id, h2d[:6]))
    for t in trends:
        t["probability"] = probs.get(t["market"]) if t.get("market") else None
        t["market_label"] = market_label(t["market"]) if t.get("market") else None
    trends.sort(key=lambda t: t["strength"], reverse=True)

    # Classement complet de la saison du match
    table = []
    if m.season:
        rows = standings([match_to_data(x) for x in db.scalars(select(Match).where(
            Match.competition_id == m.competition_id, Match.status == "FINISHED", Match.season == m.season,
            Match.kickoff < ref)).unique()])
        names = {t.id: t.name for t in db.scalars(select(Team).where(Team.id.in_([r["team_id"] for r in rows])))}
        table = [{**r, "team": names.get(r["team_id"], "?")} for r in rows]

    # Cotes : toutes les offres par marché (moyenne, meilleure), comparées à nos probabilités
    quotes = db.scalars(select(OddsQuote).where(OddsQuote.match_id == m.id)).all()
    by_market: dict[str, list] = defaultdict(list)
    for q in quotes:
        if q.bookmaker != "Max":
            by_market[q.market_key].append(q)
    odds = []
    for key, qs in by_market.items():
        prices = [q.price for q in qs]
        best = max(qs, key=lambda q: q.price)
        p = probs.get(key)
        spec = MARKET_BY_KEY.get(key)
        odds.append({"market_key": key, "label": market_label(key), "short": spec.short if spec else key,
                     "family": MARKET_BY_KEY[key].family if key in MARKET_BY_KEY else "autre",
                     "bookmakers": len(qs), "average": round(sum(prices) / len(prices), 2), "best": best.price,
                     "best_bookmaker": best.bookmaker, "probability": p,
                     "fair_odds": round(1 / p, 2) if p else None,
                     "value": round(p * best.price - 1, 3) if p else None})
    odds.sort(key=lambda o: (MARKET_ORDER.index(o["market_key"]) if o["market_key"] in MARKET_ORDER else 99, o["market_key"]))

    hw = sum(x.goals_for(m.home_team_id) > x.goals_against(m.home_team_id) for x in h2d)
    dr = sum(x.hg == x.ag for x in h2d)
    return {
        "live": match_live_state(db, m),
        "trends": trends,
        "form": {"home": _form_rows(home_ms[:10], m.home_team_id), "away": _form_rows(away_ms[:10], m.away_team_id)},
        "h2h": {
            "n": len(h2d), "home_wins": hw, "draws": dr, "away_wins": len(h2d) - hw - dr,
            "avg_goals": round(sum(x.hg + x.ag for x in h2d) / len(h2d), 2) if h2d else None,
            "over25": round(sum(x.hg + x.ag > 2.5 for x in h2d) / len(h2d), 3) if h2d else None,
            "btts": round(sum(x.hg > 0 and x.ag > 0 for x in h2d) / len(h2d), 3) if h2d else None,
            "matches": [{"match_id": x.id, "date": x.kickoff.isoformat(), "competition": x.competition.name,
                         "home": x.home_team.name, "away": x.away_team.name, "score": f"{x.home_goals}-{x.away_goals}",
                         "ht": f"{x.ht_home_goals}-{x.ht_away_goals}" if x.ht_home_goals is not None else None}
                        for x in h2h],
        },
        "standings": table,
        "odds": odds,
    }


@router.get("/matches/{match_id}/live")
def match_live(match_id: int, db: Session = Depends(get_db)):
    from ..services.live import match_live_state
    m = db.get(Match, match_id)
    if m is None:
        raise HTTPException(404, "Match introuvable")
    return match_live_state(db, m)


@router.get("/matches/{match_id}/ai")
def match_ai(match_id: int, db: Session = Depends(get_db)):
    """Analyse rédigée par IA à partir du seul dossier SAM (générée à la demande, puis mise en cache)."""
    from ..services.ai_service import get_match_ai
    res = get_match_ai(db, match_id)
    if res["status"] == "not_found":
        raise HTTPException(404, res["message"])
    return res
