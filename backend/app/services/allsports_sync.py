"""Synchronisation AllSportsAPI : championnats africains et coupes CAF (historique, calendrier, résultats,
statistiques, cotes) et scores en direct des championnats non couverts par football-data.org.

Économie de requêtes :
* historique : un appel par championnat et par année, seulement tant que l'année manque en base ;
* calendrier et résultats : un appel par championnat (de J-4 à J+n) à chaque synchronisation ;
* cotes : un appel par championnat ;
* direct : un appel au plus toutes les 5 minutes, et seulement si un match suivi est en cours.
Un plafond quotidien (ALLSPORTS_DAILY_BUDGET) arrête tout appel au-delà.

Les corners et cartons d'AllSportsAPI ne sont enregistrés que pour les compétitions dont c'est la source
principale : ailleurs, football-data.co.uk reste la référence (contrôle du 2 novembre 2026 sur 33 matchs
de Premier League et de LaLiga : 30 corners et 27 cartons identiques, les autres à une ou deux unités près).
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import Competition, Match, Setting, SyncRun, utcnow
from ..providers.allsports import AllSports, details_of, minute_of, status_of, kickoff_of, _pair
from ..providers.base import ProviderError
from ..providers.names import similarity

log = logging.getLogger("sam.allsports")
STAT_FIELDS = ("home_corners", "away_corners", "home_yellow", "away_yellow", "home_red", "away_red",
               "home_shots", "away_shots", "home_sot", "away_sot")


def make_provider(db: Session) -> AllSports:
    from .sync import _api_usage_today
    used = _api_usage_today(db, "allsports")
    cap = get_settings().allsports_daily_budget
    p = AllSports(budget_check=lambda _: used + p.requests_made < cap)
    return p


def _comps(db: Session) -> list[Competition]:
    return db.scalars(select(Competition).where(Competition.enabled.is_(True), Competition.primary_source == "allsports",
                                                Competition.allsports_id.is_not(None))).all()


def _account_problem(exc: Exception) -> bool:
    return any(w in str(exc).lower() for w in ("budget", "refusée", "http 401", "http 403", "http 429"))


def _history(db: Session, p: AllSports, comps: list[Competition], now: datetime, force: bool) -> dict:
    """Historique : compétitions AllSportsAPI, plus l'historique ancien des coupes suivies par une autre source
    (Ligue des champions : football-data.org ne fournit qu'une saison et demie)."""
    from .sync import MatchIndex, TeamResolver, _run, upsert_match

    def work(run: SyncRun) -> tuple[int, str]:
        resolver = TeamResolver(db)
        total, errors, years = 0, [], get_settings().history_seasons
        row = db.get(Setting, "allsports_history")
        done: dict = dict(row.value) if row and isinstance(row.value, dict) else {}
        for comp in comps:
            index = MatchIndex(db, comp.id)
            for k in range(years):
                if k in done.get(comp.code, []) and not force:
                    continue  # année déjà importée (même vide) : le calendrier courant prend le relais
                end = now - timedelta(days=365 * k)
                start = end - timedelta(days=365)
                try:
                    rows = p.fixtures(start.date().isoformat(), end.date().isoformat(), comp.allsports_id)
                except ProviderError as exc:
                    db.rollback()
                    errors.append(f"{comp.name} : {exc}")
                    if _account_problem(exc):
                        raise ProviderError("; ".join(errors))
                    continue
                foreign = comp.primary_source != "allsports"
                for x in rows:
                    rec = p.to_record(x, comp.code)
                    if not rec or rec.status != "FINISHED":
                        continue
                    if foreign:
                        rec.home_corners = rec.away_corners = rec.home_yellow = rec.away_yellow = None
                        rec.home_red = rec.away_red = None  # statistiques : seulement pour ses propres compétitions
                        h = resolver.resolve(rec.home_name, comp.country, rec.source)
                        a = resolver.resolve(rec.away_name, comp.country, rec.source)
                        if index.find(h.id, a.id, rec.kickoff, rec.status) is None and any(
                                abs((m.kickoff - rec.kickoff).total_seconds()) < 36 * 3600
                                for pair, ms in index.by_pair.items() if h.id in pair or a.id in pair for m in ms):
                            continue  # même journée déjà en base sous d'autres noms : pas de doublon
                    upsert_match(db, comp, rec, resolver, index)
                    total += 1
                done[comp.code] = sorted(set(done.get(comp.code, [])) | {k})
                row = db.get(Setting, "allsports_history")
                if row is None:
                    db.add(Setting(key="allsports_history", value=done))
                else:
                    row.value = dict(done)
                db.commit()
        msg = f"{total} résultats historiques traités pour {len(comps)} compétitions ({p.requests_made} requêtes)"
        if errors:
            msg += " — " + " | ".join(errors[:3])
        return total, msg

    return _run(db, p.name, "historique", work)


def _upcoming(db: Session, p: AllSports, comps: list[Competition], now: datetime, days_ahead: int) -> dict:
    from .sync import MatchIndex, TeamResolver, _run, save_odds, upsert_match

    def work(run: SyncRun) -> tuple[int, str]:
        resolver = TeamResolver(db)
        d_from = (now - timedelta(days=4)).date().isoformat()
        d_to = (now + timedelta(days=days_ahead + 1)).date().isoformat()
        n, n_odds, errors = 0, 0, []
        for comp in comps:
            index = MatchIndex(db, comp.id)
            try:
                rows = p.fixtures(d_from, d_to, comp.allsports_id)
            except ProviderError as exc:
                db.rollback()
                errors.append(f"{comp.name} : {exc}")
                if _account_problem(exc):
                    break
                continue
            by_ref: dict[str, Match] = {}
            for x in rows:
                rec = p.to_record(x, comp.code)
                if rec is None:
                    continue
                m = upsert_match(db, comp, rec, resolver, index)
                if m is not None:
                    n += 1
                    m.source_ref = rec.source_ref or m.source_ref
                    by_ref[rec.source_ref] = m
                    d = details_of(x) if rec.status in ("FINISHED", "LIVE") else None
                    if d:
                        m.details = d
            db.commit()
            todo = [m for m in by_ref.values() if m.status == "SCHEDULED" and m.kickoff >= now]
            if not todo:
                continue
            try:
                odds = p.odds(now.date().isoformat(), d_to, comp.allsports_id)
            except ProviderError as exc:
                errors.append(f"cotes {comp.name} : {exc}")
                if _account_problem(exc):
                    break
                continue
            for ref, quotes in odds.items():
                m = by_ref.get(str(ref))
                if m is not None and m.status == "SCHEDULED":
                    n_odds += save_odds(db, m.id, p.odds_records(quotes), p.name)
            db.commit()
        msg = f"{n} matchs mis à jour, {n_odds} cotes ({p.requests_made} requêtes)"
        if errors:
            msg += " ; " + " | ".join(errors[:3])
            if n == 0 and len(errors) >= len(comps):
                raise ProviderError(msg)
        return n, msg

    return _run(db, p.name, "calendrier", work)


def _final_details(db: Session, p: AllSports, now: datetime) -> Optional[dict]:
    """Chronologie et statistiques définitives des matchs terminés depuis moins de 30 h (tous championnats suivis) :
    un seul appel « Fixtures » couvrant hier et aujourd'hui."""
    from .sync import _run
    todo = db.scalars(select(Match).join(Competition, Match.competition_id == Competition.id).where(
        Competition.enabled.is_(True), Match.status == "FINISHED", Match.kickoff >= now - timedelta(hours=30),
        Match.kickoff <= now - timedelta(minutes=100))).unique().all()
    todo = [m for m in todo if not (m.details or {}).get("final")]
    if not todo:
        return None

    def work(run: SyncRun) -> tuple[int, str]:
        rows = p.fixtures((now - timedelta(days=1)).date().isoformat(), now.date().isoformat())
        done = 0
        for x in rows:
            if status_of(x) != "FINISHED":
                continue
            m = _find(todo, x)
            if m is None:
                continue
            d = details_of(x)
            if d:
                d["final"] = True
                m.details = d
                done += 1
        db.commit()
        return done, f"{done} match(s) : chronologie et statistiques définitives ({len(todo)} en attente)"

    return _run(db, p.name, "chronologie", work)


def run_allsports(db: Session, kinds: set, now: datetime, force: bool, days_ahead: int) -> list[dict]:
    """Étapes AllSportsAPI de la synchronisation (appelée par run_sync)."""
    from .sync import _add_api_usage
    comps = _comps(db)
    p = make_provider(db)
    hist_comps = db.scalars(select(Competition).where(Competition.enabled.is_(True),
                                                      Competition.allsports_id.is_not(None))).all()
    if not hist_comps or not p.is_configured():
        return []
    out = []
    try:
        if "history" in kinds:
            out.append(_history(db, p, hist_comps, now, force))
        if "upcoming" in kinds and comps:
            out.append(_upcoming(db, p, comps, now, days_ahead))
        if "upcoming" in kinds:
            fin = _final_details(db, p, now)
            if fin:
                out.append(fin)
    finally:
        _add_api_usage(db, p.name, p.requests_made)
    return out


# ---------------------------------------------------------------------------
# Direct
# ---------------------------------------------------------------------------

_lock = threading.Lock()
_cache: dict = {"at": None, "live": [], "error": None}


def _find(cands: list[Match], x: dict) -> Optional[Match]:
    ko = kickoff_of(x)
    home, away = x.get("event_home_team") or "", x.get("event_away_team") or ""
    if ko is None:
        return None
    scored = sorted(((min(similarity(home, m.home_team.name), similarity(away, m.away_team.name)), m)
                     for m in cands if abs((m.kickoff - ko).total_seconds()) <= 3 * 3600),
                    key=lambda t: t[0], reverse=True)
    if not scored:
        return None
    if scored[0][0] >= 78:
        return scored[0][1]
    same = [(s, m) for s, m in scored if abs((m.kickoff - ko).total_seconds()) <= 600]
    if same and same[0][0] >= 50 and (len(same) == 1 or same[0][0] - same[1][0] >= 15):
        return same[0][1]
    return None


def live_candidates(db: Session, now: datetime, skip_comp_ids: set[int], with_finished: bool = False) -> list[Match]:
    """Matchs suivis susceptibles d'être en cours (hors compétitions données dans skip_comp_ids)."""
    statuses = ("SCHEDULED", "LIVE", "FINISHED") if with_finished else ("SCHEDULED", "LIVE")
    cands = db.scalars(select(Match).join(Competition, Match.competition_id == Competition.id).where(
        Competition.enabled.is_(True), Match.status.in_(statuses),
        Match.kickoff >= now - timedelta(minutes=170), Match.kickoff <= now + timedelta(minutes=5))).unique().all()
    return [m for m in cands if m.competition_id not in skip_comp_ids]


def live_scores(db: Session, now: datetime, skip_comp_ids: set[int]) -> dict:
    """Scores en direct AllSportsAPI pour les matchs suivis hors football-data.org ; enregistre aussi les scores
    finaux (et, pour les compétitions dont AllSportsAPI est la source, la mi-temps, les corners et les cartons)."""
    from .settings_service import get_provider_flags
    from .sync import _add_api_usage
    cfg = get_settings()
    if not cfg.allsports_key or not get_provider_flags(db).get("allsports", True):
        return {"ok": False, "live": [], "updated": 0, "error": None}
    every = live_candidates(db, now, set(), with_finished=True)  # chronologie et statistiques : tous les matchs suivis
    cands = [m for m in every if m.competition_id not in skip_comp_ids and m.status != "FINISHED"]
    if not every:
        return {"ok": True, "live": [], "updated": 0, "error": None}
    with _lock:
        if _cache["at"] is not None and time.monotonic() - _cache["at"] < cfg.allsports_live_seconds:
            ids = {m.id for m in every}
            return {"ok": _cache["error"] is None, "live": [x for x in _cache["live"] if x["match_id"] in ids],
                    "updated": 0, "error": _cache["error"]}
        _cache["at"] = time.monotonic()
        p = make_provider(db)
        try:
            rows = p.livescore()
            _cache["error"] = None
        except ProviderError as exc:
            _cache.update(live=[], error=str(exc))
            _add_api_usage(db, p.name, p.requests_made)
            return {"ok": False, "live": [], "updated": 0, "error": str(exc)}
        _add_api_usage(db, p.name, p.requests_made)
        live, updated = [], 0
        for x in rows:
            any_m = _find(every, x)
            if any_m is not None:
                d = details_of(x)
                if d:
                    any_m.details = d
            m = _find(cands, x)
            if m is None:
                continue
            st = status_of(x)
            h, a = _pair(x.get("event_final_result"))
            hh, ha = _pair(x.get("event_halftime_result"))
            if st == "FINISHED":
                rec = p.to_record(x, m.competition.code)
                if rec is None or rec.home_goals is None:
                    continue
                m.home_goals, m.away_goals = rec.home_goals, rec.away_goals
                if rec.ht_home_goals is not None:
                    m.ht_home_goals, m.ht_away_goals = rec.ht_home_goals, rec.ht_away_goals
                if m.competition.primary_source == "allsports":
                    for f in STAT_FIELDS:
                        if getattr(rec, f) is not None and getattr(m, f) is None:
                            setattr(m, f, getattr(rec, f))
                m.status = "FINISHED"
                updated += 1
            elif st == "LIVE":
                paused = (x.get("event_status") or "") == "Half Time"
                live.append({"match_id": m.id, "status": "Mi-temps" if paused else "En cours",
                             "minute": minute_of(x), "home": h, "away": a, "ht_home": hh, "ht_away": ha,
                             "source": "allsports"})
        db.commit()
        _cache["live"] = live
        return {"ok": True, "live": live, "updated": updated, "error": None}
