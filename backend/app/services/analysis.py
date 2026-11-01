"""Analyse des matchs à venir et publication des pronostics retenus."""
from __future__ import annotations

import logging
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..engine.calibration import calibrators_from_dict, load_default_calibration
from ..engine.features import TeamHistory, standings
from ..engine.predictor import ENGINE_VERSION, EngineParams, FixtureContext, analyze_fixture, fit_league_models
from ..engine.types import MatchData, OddsInfo
from ..engine.extended_picks import add_to_payload as add_extended_markets
from ..engine.value import best_value_per_match, value_score
from ..models import Analysis, Calibration, Competition, Injury, Match, OddsQuote, Prediction, utcnow
from .settings_service import get_selection_settings
from .sync import last_successful_sync

log = logging.getLogger("sam.analysis")
UTC = timezone.utc

BOOKMAKER_RANK = {"Moyenne": 0, "Bet365": 1, "Pinnacle": 2}
ODDS_GROUPS = (
    [["1", "X", "2"], ["1X", "X2", "12"], ["BTTS_Y", "BTTS_N"], ["HT_1", "HT_X", "HT_2"]]
    + [[f"O{x}", f"U{x}"] for x in ("0.5", "1.5", "2.5", "3.5", "4.5")]
    + [[f"HT_O{x}", f"HT_U{x}"] for x in ("0.5", "1.5", "2.5")]
    + [[f"C_O{x}", f"C_U{x}"] for x in ("6.5", "7.5", "8.5", "9.5", "10.5", "11.5")]
    + [[f"K_O{x}", f"K_U{x}"] for x in ("2.5", "3.5", "4.5", "5.5")]
)


def match_to_data(m: Match) -> MatchData:
    return MatchData(id=m.id, competition_id=m.competition_id, kickoff=m.kickoff, home_id=m.home_team_id,
                     away_id=m.away_team_id, hg=m.home_goals, ag=m.away_goals, hthg=m.ht_home_goals,
                     htag=m.ht_away_goals, hc=m.home_corners, ac=m.away_corners, hy=m.home_yellow,
                     ay=m.away_yellow, hr=m.home_red, ar=m.away_red, status=m.status, season=m.season)


def match_summary(m: Match) -> dict:
    return {
        "id": m.id, "kickoff": m.kickoff.isoformat(), "status": m.status, "season": m.season,
        "competition": {"id": m.competition.id, "code": m.competition.code, "name": m.competition.name,
                        "country": m.competition.country},
        "home": {"id": m.home_team.id, "name": m.home_team.name},
        "away": {"id": m.away_team.id, "name": m.away_team.name},
        "score": ({"home": m.home_goals, "away": m.away_goals, "ht_home": m.ht_home_goals,
                   "ht_away": m.ht_away_goals}
                  if m.home_goals is not None and m.status in ("FINISHED", "LIVE") else None),
    }


def _book_rank(name: str) -> int:
    if name == "Max":
        return 99
    return BOOKMAKER_RANK.get(name, 10)


def choose_odds(quotes: list[OddsQuote]) -> dict[str, OddsInfo]:
    """Une cote par marché, en privilégiant un même bookmaker pour tout un groupe (1X2, +/-…)."""
    by_book: dict[str, dict[str, OddsQuote]] = defaultdict(dict)
    for q in quotes:
        cur = by_book[q.bookmaker].get(q.market_key)
        if cur is None or q.collected_at > cur.collected_at:
            by_book[q.bookmaker][q.market_key] = q
    ranked = sorted(by_book, key=_book_rank)
    out: dict[str, OddsInfo] = {}
    for group in ODDS_GROUPS:
        chosen = next((b for b in ranked if all(k in by_book[b] for k in group)), None)
        for k in group:
            b = chosen or next((bk for bk in ranked if k in by_book[bk]), None)
            if b and k in by_book[b]:
                q = by_book[b][k]
                out[k] = OddsInfo(price=q.price, bookmaker=q.bookmaker, source=q.source)
    return out


def load_calibration(db: Session) -> dict:
    row = db.scalar(select(Calibration).where(Calibration.active.is_(True)).order_by(Calibration.created_at.desc()))
    if row is not None:
        return row.payload
    return load_default_calibration()


def _standing_context(rows: list[dict], home_id: int, away_id: int) -> tuple[Optional[dict], bool]:
    if not rows:
        return None, False
    pos = {r["team_id"]: r for r in rows}
    n = len(rows)
    rounds = 2 * (n - 1)
    played = max(r["played"] for r in rows)
    late = n >= 10 and played >= rounds - 3

    def pick(t):
        r = pos.get(t)
        return {k: r[k] for k in ("position", "points", "played", "goal_difference")} if r else None

    return {"home": pick(home_id), "away": pick(away_id), "teams": n, "rounds_played": played,
            "season_rounds": rounds}, late


def run_analysis(db: Session, now: Optional[datetime] = None, publish: bool = True) -> dict:
    now = now or utcnow()
    s = get_selection_settings(db)
    params = EngineParams()
    cal_payload = load_calibration(db)
    cals = calibrators_from_dict(cal_payload)
    reliability = cal_payload.get("reliability") or {}
    horizon = now + timedelta(days=int(s["days_ahead"]))
    upcoming = db.scalars(
        select(Match).join(Competition, Match.competition_id == Competition.id).where(
            Competition.enabled.is_(True), Match.status == "SCHEDULED", Match.kickoff >= now,
            Match.kickoff < horizon).order_by(Match.kickoff)).unique().all()
    last_sync = last_successful_sync(db)
    data_age = (now - last_sync).total_seconds() / 3600 if last_sync else None

    by_comp: dict[int, list[Match]] = defaultdict(list)
    for m in upcoming:
        by_comp[m.competition_id].append(m)
    stats = Counter()
    candidates: list[tuple[float, Match, dict]] = []
    value_cands: list[tuple[float, Match, dict]] = []
    for comp_id, ms in by_comp.items():
        since = now - timedelta(days=params.window_days + 30)
        rows = db.scalars(select(Match).where(Match.competition_id == comp_id, Match.status == "FINISHED",
                                              Match.kickoff >= since, Match.kickoff < now)).unique().all()
        data = [match_to_data(r) for r in rows]
        try:
            lm = fit_league_models(comp_id, data, now, params)
        except Exception:  # sécurité : une compétition en erreur ne bloque pas les autres
            log.exception("Ajustement impossible pour la compétition %s", comp_id)
            continue
        history = TeamHistory(data)
        season_tables: dict = {}
        for m in ms:
            season_rows = season_tables.get(m.season)
            if season_rows is None:
                season_rows = standings([d for d in data if d.season == m.season]) if m.season else []
                season_tables[m.season] = season_rows
            st, late = _standing_context(season_rows, m.home_team_id, m.away_team_id)
            quotes = db.scalars(select(OddsQuote).where(OddsQuote.match_id == m.id)).all()
            injuries = None
            if m.enriched_at is not None:
                inj = db.scalars(select(Injury).where(Injury.match_id == m.id)).all()
                injuries = {side: [{"player": i.player, "type": i.kind, "reason": i.reason}
                                   for i in inj if i.team_id == tid]
                            for side, tid in (("home", m.home_team_id), ("away", m.away_team_id))}
            fx = FixtureContext(match_id=m.id, competition_id=comp_id, kickoff=m.kickoff, home_id=m.home_team_id,
                                away_id=m.away_team_id, home_name=m.home_team.name, away_name=m.away_team.name,
                                odds=choose_odds(quotes), injuries=injuries, data_age_hours=data_age,
                                late_season=late, standings=st)
            payload = analyze_fixture(lm, fx, history, cals, reliability, s, params)
            payload["match"] = match_summary(m)
            add_extended_markets(payload, s)
            payload["calibration"] = {"source": cal_payload.get("source") or "aucune",
                                      "generated_at": cal_payload.get("generated_at")}
            a = db.scalar(select(Analysis).where(Analysis.match_id == m.id))
            if a is None:
                a = Analysis(match_id=m.id)
                db.add(a)
            a.computed_at = now
            a.engine_version = payload["engine_version"]
            a.status = payload["status"]
            a.match_confidence = int(payload.get("match_confidence") or 0)
            a.n_picks = len(payload["picks"])
            a.payload = payload
            stats["analysed"] += 1
            stats[payload["status"]] += 1
            for key in payload["picks"]:
                mk = next(x for x in payload["markets"] if x["key"] == key)
                candidates.append((mk["score"], m, mk))
            if payload["status"] == "ok" and not payload.get("avoid_reasons"):
                vmk = best_value_per_match(payload["markets"], s)
                if vmk is not None:
                    value_cands.append((value_score(vmk), m, vmk))
        db.commit()

    published = 0
    if publish and candidates:
        day_counts = Counter()
        for p in db.scalars(select(Prediction).join(Match, Prediction.match_id == Match.id).where(
                Match.kickoff >= now - timedelta(days=1), Match.kickoff < horizon + timedelta(days=1))).unique():
            day_counts[p.match.kickoff.date()] += 1
        existing = {(p.match_id, p.market_key) for p in db.scalars(
            select(Prediction).where(Prediction.match_id.in_([m.id for _, m, _ in candidates]))).unique()}
        for score, m, mk in sorted(candidates, key=lambda t: t[0], reverse=True):
            if (m.id, mk["key"]) in existing or m.kickoff <= now + timedelta(minutes=10):
                continue
            if day_counts[m.kickoff.date()] >= int(s["max_daily_picks"]):
                continue
            db.add(_new_prediction(m, mk, now))
            existing.add((m.id, mk["key"]))
            day_counts[m.kickoff.date()] += 1
            published += 1
        db.commit()
    featured = select_featured(db, candidates, s, now) if publish and candidates else 0
    value = select_value_picks(db, value_cands, s, now) if publish and value_cands else 0
    return {"analysed": stats["analysed"], "ok": stats["ok"], "insufficient": stats["insufficient"],
            "competitions": len(by_comp), "published": published, "featured": featured, "value_picks": value,
            "computed_at": now.isoformat()}


def _new_prediction(m: Match, mk: dict, now: datetime) -> Prediction:
    return Prediction(
        created_at=now, match_id=m.id, market_key=mk["key"], market_label=mk["label"],
        probability=mk["probability"], confidence=mk["confidence"]["score"],
        confidence_level=mk["confidence"]["level"], tier=mk["tier"], odds=mk.get("odds"),
        bookmaker=mk.get("bookmaker"), implied_probability=mk.get("implied_probability"),
        engine_version=ENGINE_VERSION, explanation=mk.get("explanation"))


def featured_eligible(mk: dict, s: dict) -> bool:
    if mk.get("extended"):
        return False  # la Sélection SAM reste sur les marchés principaux (historique de calibration le plus long)
    if mk["probability"] < float(s["featured_min_probability"]):
        return False
    if mk["confidence"]["score"] < int(s["featured_min_confidence"]):
        return False
    if (mk.get("odds") or 1 / mk["probability"]) < float(s["featured_min_fair_odds"]):
        return False
    edge = mk.get("edge")
    return edge is None or edge >= -0.03  # pas de cote nettement inférieure à la cote juste


def select_featured(db: Session, candidates: list, s: dict, now: datetime) -> int:
    """Sélection SAM du jour : au plus N pronostics par jour (un par match), critères renforcés.
    Le statut est attribué avant le coup d'envoi et n'est jamais retiré ensuite."""
    best: dict[int, tuple] = {}
    for score, m, mk in candidates:
        if m.kickoff <= now + timedelta(minutes=10) or not featured_eligible(mk, s):
            continue
        if m.id not in best or score > best[m.id][0]:
            best[m.id] = (score, m, mk)
    if not best:
        return 0
    days = {m.kickoff.date() for _, m, _ in best.values()}
    per_day = Counter()
    for p in db.scalars(select(Prediction).join(Match, Prediction.match_id == Match.id).where(
            Prediction.featured.is_(True), Match.kickoff >= now - timedelta(days=2))).unique():
        if p.match.kickoff.date() in days:
            per_day[p.match.kickoff.date()] += 1
    featured_matches = {p.match_id for p in db.scalars(select(Prediction).where(
        Prediction.featured.is_(True), Prediction.match_id.in_(list(best)))).unique()}
    n = 0
    for score, m, mk in sorted(best.values(), key=lambda t: t[0], reverse=True):
        day = m.kickoff.date()
        if m.id in featured_matches or per_day[day] >= int(s["featured_max_per_day"]):
            continue
        pred = db.scalar(select(Prediction).where(Prediction.match_id == m.id, Prediction.market_key == mk["key"]))
        if pred is None:  # la Sélection est toujours publiée, même si le quota quotidien est atteint
            pred = _new_prediction(m, mk, now)
            db.add(pred)
        elif pred.result != "pending":
            continue
        pred.featured = True
        pred.featured_at = now
        per_day[day] += 1
        n += 1
    db.commit()
    return n


def select_value_picks(db: Session, candidates: list, s: dict, now: datetime) -> int:
    """Pronostics à cote : au plus N par jour (un par match), cote 1,40-2,20 environ, figés avant le match."""
    best = {m.id: (score, m, mk) for score, m, mk in candidates if m.kickoff > now + timedelta(minutes=10)}
    if not best:
        return 0
    days = {m.kickoff.date() for _, m, _ in best.values()}
    per_day = Counter()
    for p in db.scalars(select(Prediction).join(Match, Prediction.match_id == Match.id).where(
            Prediction.value_pick.is_(True), Match.kickoff >= now - timedelta(days=2))).unique():
        if p.match.kickoff.date() in days:
            per_day[p.match.kickoff.date()] += 1
    already = {p.match_id for p in db.scalars(select(Prediction).where(
        Prediction.value_pick.is_(True), Prediction.match_id.in_(list(best)))).unique()}
    n = 0
    per_market = Counter()  # diversité : au plus 2 fois le même marché par jour
    for score, m, mk in sorted(best.values(), key=lambda t: t[0], reverse=True):
        day = m.kickoff.date()
        if m.id in already or per_day[day] >= int(s["value_max_per_day"]) or per_market[(day, mk["key"])] >= 2:
            continue
        per_market[(day, mk["key"])] += 1
        pred = db.scalar(select(Prediction).where(Prediction.match_id == m.id, Prediction.market_key == mk["key"]))
        if pred is None:
            pred = _new_prediction(m, mk, now)
            db.add(pred)
        elif pred.result != "pending":
            continue
        pred.value_pick = True
        per_day[day] += 1
        n += 1
    db.commit()
    return n
