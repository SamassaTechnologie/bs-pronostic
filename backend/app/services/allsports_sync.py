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
from ..models import ApiUsage, Competition, Match, Setting, SyncRun, utcnow
from ..providers.allsports import AllSports, details_of, merge_details, minute_of, status_of, kickoff_of, _pair
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
                        m.details = merge_details(m.details, d)
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
                m.details = merge_details(m.details, d)
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
    if "upcoming" in kinds and get_provider_flags_safe(db):
        res = odds_popular(db, now, force)
        if res:
            out.append(res)
    errs = [r for r in out if r.get("status") == "error"]
    if errs and len(errs) == len(out):
        note_result(db, False, errs[0].get("message") or "")
    elif out:
        note_result(db, True)
    return out


def get_provider_flags_safe(db: Session) -> bool:
    from .settings_service import get_provider_flags
    return bool(get_provider_flags(db).get("allsports", True))


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
            note_result(db, False, str(exc))
            return {"ok": False, "live": [], "updated": 0, "error": str(exc)}
        _add_api_usage(db, p.name, p.requests_made)
        note_result(db, True)
        live, updated = [], 0
        for x in rows:
            any_m = _find(every, x)
            if any_m is not None:
                d = details_of(x)
                if d:
                    any_m.details = merge_details(any_m.details, d, minute_of(x))
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


_pre: dict = {"at": None}


def prematch_lineups(db: Session, now: datetime, every_seconds: int = 1200) -> int:
    """Compositions officielles des matchs des grands championnats qui commencent dans l'heure : un seul appel
    « Fixtures » du jour, au plus toutes les 20 minutes, et seulement si une composition manque encore."""
    from ..popular import is_popular
    from .settings_service import get_provider_flags
    from .sync import _add_api_usage
    cfg = get_settings()
    if not cfg.allsports_key or not get_provider_flags(db).get("allsports", True):
        return 0
    soon = db.scalars(select(Match).join(Competition, Match.competition_id == Competition.id).where(
        Competition.enabled.is_(True), Match.status == "SCHEDULED", Match.kickoff > now,
        Match.kickoff <= now + timedelta(minutes=70))).unique().all()
    todo = [m for m in soon if is_popular(m.competition.code) and not (m.details or {}).get("lineups")]
    if not todo:
        return 0
    with _lock:
        if _pre["at"] is not None and time.monotonic() - _pre["at"] < every_seconds:
            return 0
        _pre["at"] = time.monotonic()
    p = make_provider(db)
    try:
        rows = p.fixtures(now.date().isoformat(), (now + timedelta(minutes=70)).date().isoformat())
    except ProviderError:
        return 0
    finally:
        _add_api_usage(db, p.name, p.requests_made)
    n = 0
    for x in rows:
        m = _find(todo, x)
        if m is None:
            continue
        from ..providers.allsports import lineups_of
        lu = lineups_of(x)
        if lu:
            d = dict(m.details or {})
            d["lineups"] = lu
            d.setdefault("source", "AllSportsAPI")
            m.details = d
            n += 1
    db.commit()
    return n


# Cotes des grands championnats européens (marchés absents de football-data.co.uk : double chance, +1,5, les deux
# marquent…). Identifiants AllSportsAPI, vérifiés à chaque appel par le nom de la compétition renvoyé.
ODDS_ALLSPORTS = {
    "ENG1": (152, "premier league"), "ESP1": (302, "laliga|primera"), "ITA1": (207, "serie a"), "GER1": (175, "bundesliga"),
    "FRA1": (168, "ligue 1"), "NED1": (244, "eredivisie"), "POR1": (266, "primeira liga|liga portugal|portuguese liga"),
    "UCL": (3, "champions league"), "UEL": (4, "europa league"), "UECL": (683, "conference league"),
}
ODDS_EVERY_HOURS = 12
ODDS_BUDGET_MARGIN = 80


def _league_ok(x: dict, expected: str) -> bool:
    import unicodedata
    norm = lambda s: unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower().replace(" ", "")  # noqa: E731
    return any(norm(e) in norm(x.get("league_name")) for e in expected.split("|"))


def odds_popular(db: Session, now: datetime, force: bool = False) -> Optional[dict]:
    """Cotes bookmaker (AllSportsAPI) des matchs à venir des grands championnats : 2 requêtes par championnat,
    au plus toutes les 12 heures, seulement s'il reste de la marge sur le budget quotidien."""
    from .settings_service import get_provider_flags
    from .sync import _add_api_usage, _run, save_odds
    cfg = get_settings()
    if not cfg.allsports_key or not get_provider_flags(db).get("allsports", True):
        return None
    memo = db.get(Setting, "allsports_odds") or Setting(key="allsports_odds", value={})
    last = (memo.value or {}).get("at")
    if not force and last and now - datetime.fromisoformat(last) < timedelta(hours=ODDS_EVERY_HOURS):
        return None
    used = db.get(ApiUsage, ("allsports", now.date().isoformat()))
    if (used.requests if used else 0) > cfg.allsports_daily_budget - ODDS_BUDGET_MARGIN:
        return None
    comps = {c.code: c for c in db.scalars(select(Competition).where(
        Competition.enabled.is_(True), Competition.code.in_(list(ODDS_ALLSPORTS)))).all()}
    if not comps or not db.scalar(select(func.count(Match.id)).where(
            Match.competition_id.in_([c.id for c in comps.values()]), Match.status == "SCHEDULED",
            Match.kickoff > now, Match.kickoff < now + timedelta(days=3))):
        return None
    p = make_provider(db)

    def work(run: SyncRun) -> tuple[int, str]:
        d_from, d_to = now.date().isoformat(), (now + timedelta(days=3)).date().isoformat()
        n_matches, n_odds, errors = 0, 0, []
        for code, comp in comps.items():
            league_id, expected = ODDS_ALLSPORTS[code]
            todo = db.scalars(select(Match).where(Match.competition_id == comp.id, Match.status == "SCHEDULED",
                                                  Match.kickoff > now, Match.kickoff < now + timedelta(days=3))).unique().all()
            if not todo:
                continue
            try:
                raw = p.fixtures(d_from, d_to, league_id)
                rows = [x for x in raw if _league_ok(x, expected)]
                if not rows:
                    seen = sorted({f"{x.get('country_name')}/{x.get('league_name')}" for x in raw})[:2]
                    errors.append(f"{comp.name} : compétition non reconnue ({', '.join(seen) or 'aucun match'})")
                    continue
                odds = p.odds(d_from, d_to, league_id)
            except ProviderError as exc:
                errors.append(f"{comp.name} : {exc}")
                if _account_problem(exc):
                    break
                continue
            for x in rows:
                quotes = odds.get(str(x.get("event_key")))
                m = _find(todo, x) if quotes else None
                if m is not None:
                    k = save_odds(db, m.id, p.odds_records(quotes), p.name)
                    n_odds += k
                    n_matches += 1 if k else 0
            db.commit()
        memo.value = {"at": now.isoformat()}
        db.merge(memo)
        db.commit()
        msg = f"cotes de {n_matches} match(s) des grands championnats, {n_odds} cotes ({p.requests_made} requêtes)"
        if errors:
            msg += " ; " + " | ".join(errors[:3])
        return n_matches, msg

    try:
        return _run(db, p.name, "cotes", work)
    finally:
        _add_api_usage(db, p.name, p.requests_made)


# --- Fin d'abonnement : arrêt automatique et mise en pause des championnats qui en dépendent ----------------------
REFUSALS_BEFORE_SHUTDOWN = 3


def _key_refused(msg: str) -> bool:
    """Refus de la clé par AllSportsAPI (abonnement terminé, clé invalide) — pas notre propre budget prudent."""
    m = (msg or "").lower()
    return "budget" not in m and any(w in m for w in ("refusée", "http 401", "http 403", "expired", "invalid"))


def note_result(db: Session, ok: bool, message: str = "") -> bool:
    """Compte les refus consécutifs de la clé ; au 3e, coupe la source et met en pause ses championnats.
    Retourne True si la source vient d'être coupée."""
    row = db.get(Setting, "allsports_refusals")
    n = int((row.value or {}).get("n", 0)) if row else 0
    if ok:
        if n:
            row.value = {"n": 0}
            db.commit()
        return False
    if not _key_refused(message):
        return False
    n += 1
    if row is None:
        db.add(Setting(key="allsports_refusals", value={"n": n, "last": message[:200]}))
    else:
        row.value = {"n": n, "last": message[:200]}
    db.commit()
    if n >= REFUSALS_BEFORE_SHUTDOWN:
        shutdown(db, message)
        return True
    return False


def shutdown(db: Session, reason: str = "") -> list[str]:
    """Coupe AllSportsAPI et met en pause (sans rien supprimer) les championnats dont c'est la seule source."""
    from .settings_service import set_provider_flag
    set_provider_flag(db, "allsports", False)
    comps = db.scalars(select(Competition).where(Competition.enabled.is_(True),
                                                 Competition.primary_source == "allsports")).all()
    codes = [c.code for c in comps]
    for c in comps:
        c.enabled = False
    memo = db.get(Setting, "allsports_paused") or Setting(key="allsports_paused", value={})
    memo.value = {"codes": sorted(set((memo.value or {}).get("codes", [])) | set(codes)), "reason": (reason or "")[:200],
                  "at": utcnow().isoformat()}
    db.merge(memo)
    db.add(SyncRun(provider="allsports", kind="sécurité", status="error", items=len(codes), finished_at=utcnow(),
                   message=f"AllSportsAPI désactivé automatiquement (clé refusée) ; {len(codes)} championnat(s) mis "
                           f"en pause : {', '.join(codes) or 'aucun'}. Le direct passe par SportAPI.ai."))
    db.commit()
    log.warning("AllSportsAPI désactivé automatiquement : %s", reason)
    return codes


def resume(db: Session) -> list[str]:
    """Réactivation (abonnement repris) : la source et les championnats mis en pause reviennent."""
    memo = db.get(Setting, "allsports_paused")
    codes = (memo.value or {}).get("codes", []) if memo else []
    for c in db.scalars(select(Competition).where(Competition.code.in_(codes))).all():
        c.enabled = True
    if memo:
        memo.value = {"codes": []}
    row = db.get(Setting, "allsports_refusals")
    if row:
        row.value = {"n": 0}
    db.commit()
    return codes
