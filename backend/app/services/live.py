"""Scores en direct et résultats rapides via football-data.org.

football-data.co.uk ne publie les résultats que quelques jours après les matchs. Pour
les compétitions couvertes par football-data.org (offre gratuite : scores légèrement
différés), on récupère les scores du jour pour :
  * afficher les matchs en cours (cache de 60 secondes pour respecter 10 appels/minute) ;
  * enregistrer immédiatement le score final et la mi-temps des matchs terminés,
    ce qui permet de régler les pronostics le soir même.
Corners et cartons restent fournis par football-data.co.uk (règlement différé).
"""
from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..engine.markets import evaluate_market
from ..models import Competition, Match, Prediction, utcnow
from ..providers.base import ProviderError
from ..providers.football_data_org import FootballDataOrg
from ..providers.names import similarity
from .analysis import match_summary, match_to_data
from .settings_service import get_provider_flags

UTC = timezone.utc
CACHE_SECONDS = 60
_lock = threading.Lock()
_cache: dict = {"at": 0.0, "items": [], "error": None, "source_ok": None}


def _find_match(db: Session, comps: dict, m: dict) -> Optional[Match]:
    code = (m.get("competition") or {}).get("code")
    comp_ids = comps.get(code)
    if not comp_ids or not m.get("utcDate"):
        return None
    ko = datetime.fromisoformat(m["utcDate"].replace("Z", "+00:00"))
    home, away = (m.get("homeTeam") or {}).get("name", ""), (m.get("awayTeam") or {}).get("name", "")
    cands = db.scalars(select(Match).where(Match.competition_id.in_(comp_ids),
                                           Match.kickoff >= ko - timedelta(hours=30),
                                           Match.kickoff <= ko + timedelta(hours=30))).unique().all()
    scored = sorted(((min(similarity(home, c.home_team.name), similarity(away, c.away_team.name)), c) for c in cands),
                    key=lambda t: t[0], reverse=True)
    if not scored:
        return None
    best_score, best = scored[0]
    if best_score >= 78:
        return best
    # Même compétition, même heure de coup d'envoi : on accepte un nom moins proche s'il se détache nettement.
    same_time = [(sc, c) for sc, c in scored if abs((c.kickoff - ko).total_seconds()) <= 300]
    if same_time and same_time[0][0] >= 45 and (len(same_time) == 1 or same_time[0][0] - same_time[1][0] >= 15):
        return same_time[0][1]
    return None


def refresh_scores(db: Session, now: Optional[datetime] = None, days_back: int = 2) -> dict:
    """Interroge football-data.org et met à jour les matchs terminés. Retourne les matchs en cours."""
    now = now or utcnow()
    fo = FootballDataOrg()
    if not fo.is_configured() or not get_provider_flags(db).get("football_data_org", True):
        return {"ok": False, "error": "football-data.org non configuré", "live": [], "updated": 0}
    comps: dict[str, list[int]] = {}
    for c in db.scalars(select(Competition).where(Competition.enabled.is_(True), Competition.fdorg_code.is_not(None))):
        comps.setdefault(c.fdorg_code, []).append(c.id)
    if not comps:
        return {"ok": True, "live": [], "updated": 0}
    try:
        # dateTo est exclusif côté football-data.org : on demande jusqu'au lendemain.
        rows = fo.matches_between((now - timedelta(days=days_back)).date().isoformat(),
                                  (now + timedelta(days=1)).date().isoformat())
    except ProviderError as exc:
        return {"ok": False, "error": str(exc), "live": [], "updated": 0}
    updated, live = 0, []
    for r in rows:
        status = r.get("status")
        if status not in ("IN_PLAY", "PAUSED", "LIVE", "FINISHED"):
            continue
        m = _find_match(db, comps, r)
        if m is None:
            continue
        score = r.get("score") or {}
        cur = score.get("regularTime") or score.get("fullTime") or {}
        half = score.get("halfTime") or {}
        if status == "FINISHED":
            if m.status != "FINISHED" and cur.get("home") is not None:
                m.home_goals, m.away_goals = cur.get("home"), cur.get("away")
                if half.get("home") is not None:
                    m.ht_home_goals, m.ht_away_goals = half.get("home"), half.get("away")
                m.status = "FINISHED"
                updated += 1
        else:
            live.append({"match_id": m.id, "status": "Mi-temps" if status == "PAUSED" else "En cours",
                         "minute": r.get("minute"), "home": cur.get("home"), "away": cur.get("away"),
                         "ht_home": half.get("home"), "ht_away": half.get("away")})
    db.commit()
    if updated:
        from .performance import settle_predictions
        settle_predictions(db, now)
    return {"ok": True, "live": live, "updated": updated}


def _pick_state(p: Prediction, m: Match, live: Optional[dict]) -> str:
    """État d'un pronostic pendant le match (score actuel), sans préjuger de la fin."""
    data = match_to_data(m)
    if live:
        data.hg, data.ag = live.get("home"), live.get("away")
        data.hthg, data.htag = live.get("ht_home"), live.get("ht_away")
    if data.hg is None:
        return "Coup d'envoi imminent"
    key = p.market_key
    res = evaluate_market(key, data)
    if res is None:
        return "Suivi au coup de sifflet final"
    if key.startswith(("O", "HT_O")) and not res:
        return "En attente de buts"
    if key.startswith("O") and res:
        return "Déjà validé"
    if key.startswith("U") and not res:
        return "Perdu"
    if key == "BTTS_Y" and res:
        return "Déjà validé"
    return "Gagnant si le score ne bouge plus" if res else "Perdant si le score ne bouge plus"


RESULT_STATE = {"won": "Gagné", "lost": "Perdu", "void": "Annulé", "unverifiable": "Non vérifiable",
                "pending": "Résultat en attente"}


def _picks(preds: list, m: Match, lv: Optional[dict], finished: bool) -> list[dict]:
    out = []
    for p in preds:
        state = RESULT_STATE.get(p.result, p.result) if finished else _pick_state(p, m, lv)
        out.append({"market_key": p.market_key, "market_label": p.market_label, "probability": p.probability,
                    "featured": bool(p.featured), "state": state, "result": p.result})
    return out


def _live_items(db: Session) -> tuple[dict, Optional[str], Optional[str]]:
    """Scores en direct (cache de 60 s partagé avec la page Direct)."""
    with _lock:
        if time.monotonic() - _cache["at"] >= CACHE_SECONDS:
            res = refresh_scores(db)
            _cache.update(at=time.monotonic(), items=res.get("live", []), error=res.get("error"),
                          source_ok=res.get("ok"), refreshed_at=utcnow().isoformat())
        return {x["match_id"]: x for x in _cache["items"]}, _cache.get("error"), _cache.get("refreshed_at")


def estimated_minute(kickoff: datetime, now: datetime, paused: bool = False) -> Optional[str]:
    """Minute approximative à partir de l'heure du coup d'envoi (la source gratuite ne la fournit pas toujours)."""
    elapsed = (now - kickoff).total_seconds() / 60
    if elapsed < 0:
        return None
    if paused or 47 <= elapsed < 62:
        return "Mi-temps"
    if elapsed < 47:
        return f"{max(1, int(elapsed))}'" if elapsed < 45 else "45+'"
    minute = int(elapsed - 15)
    return f"{minute}'" if minute <= 90 else "90+'"


def match_live_state(db: Session, m: Match) -> dict:
    """État d'un match pour la fiche : à venir, en cours (score, minute), terminé."""
    now = utcnow()
    if m.status == "FINISHED":
        return {"state": "finished", "label": "Terminé", "home": m.home_goals, "away": m.away_goals,
                "ht_home": m.ht_home_goals, "ht_away": m.ht_away_goals, "minute": None, "covered": True}
    started = m.kickoff <= now <= m.kickoff + timedelta(minutes=150)
    live, error, refreshed = _live_items(db) if started else ({}, None, None)
    lv = live.get(m.id)
    if lv:
        paused = lv.get("status") == "Mi-temps"
        minute = f"{lv['minute']}'" if lv.get("minute") else estimated_minute(m.kickoff, now, paused)
        return {"state": "live", "label": "Mi-temps" if paused else "En cours", "home": lv.get("home"),
                "away": lv.get("away"), "ht_home": lv.get("ht_home"), "ht_away": lv.get("ht_away"),
                "minute": minute, "minute_estimated": not lv.get("minute"), "covered": True, "refreshed_at": refreshed}
    if started:
        return {"state": "live", "label": "En cours", "home": None, "away": None, "minute": estimated_minute(m.kickoff, now),
                "minute_estimated": True, "covered": False, "refreshed_at": refreshed,
                "note": "Score en direct non disponible pour ce championnat (source gratuite)" if not error else error}
    if m.status in ("POSTPONED", "CANCELLED"):
        return {"state": "postponed", "label": "Reporté" if m.status == "POSTPONED" else "Annulé", "covered": False}
    return {"state": "scheduled", "label": "À venir", "covered": False}


def live_board(db: Session, force: bool = False, tz_name: Optional[str] = None) -> dict:
    """Journée en un coup d'œil : matchs en cours, à venir aujourd'hui, terminés aujourd'hui.
    Les appels externes sont limités à 1 par minute (cache)."""
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    with _lock:
        fresh = time.monotonic() - _cache["at"] < CACHE_SECONDS
        if force or not fresh:
            res = refresh_scores(db)
            _cache.update(at=time.monotonic(), items=res.get("live", []), error=res.get("error"),
                          source_ok=res.get("ok"), refreshed_at=utcnow().isoformat())
        live = {x["match_id"]: x for x in _cache["items"]}
        error = _cache.get("error")
        refreshed = _cache.get("refreshed_at")
    now = utcnow()
    try:
        tz = ZoneInfo(tz_name or "Africa/Bamako")
    except (ZoneInfoNotFoundError, ValueError):
        tz = ZoneInfo("Africa/Bamako")
    local = now.astimezone(tz)
    day_start = local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(UTC)
    day_end = day_start + timedelta(days=1)
    rows = db.scalars(select(Match).join(Competition, Match.competition_id == Competition.id).where(
        Competition.enabled.is_(True),
        Match.kickoff >= min(day_start, now - timedelta(minutes=150)),
        Match.kickoff < max(day_end, now + timedelta(hours=6))).order_by(Match.kickoff)).unique().all()
    extra = set(live) - {m.id for m in rows}
    if extra:
        rows += db.scalars(select(Match).where(Match.id.in_(extra))).unique().all()
    preds = db.scalars(select(Prediction).where(Prediction.match_id.in_([m.id for m in rows]))).unique().all() if rows else []
    by_match: dict[int, list] = {}
    for p in preds:
        by_match.setdefault(p.match_id, []).append(p)
    in_play, upcoming, finished = [], [], []
    for m in sorted(rows, key=lambda x: x.kickoff):
        lv = live.get(m.id)
        if m.status == "FINISHED":
            if m.kickoff >= day_start:
                finished.append({"match": match_summary(m), "live": None, "covered": True,
                                 "picks": _picks(by_match.get(m.id, []), m, None, True)})
        elif lv is not None or (m.kickoff <= now and m.kickoff >= now - timedelta(minutes=150)):
            in_play.append({"match": match_summary(m), "live": lv, "covered": lv is not None,
                            "picks": _picks(by_match.get(m.id, []), m, lv, False)})
        elif m.kickoff > now and m.status == "SCHEDULED":
            upcoming.append({"match": match_summary(m), "live": None, "covered": False,
                             "picks": _picks(by_match.get(m.id, []), m, None, False)})
    finished.reverse()
    return {"items": in_play, "live": in_play, "upcoming": upcoming, "finished": finished,
            "refreshed_at": refreshed, "error": error}
