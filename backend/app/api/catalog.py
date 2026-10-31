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
