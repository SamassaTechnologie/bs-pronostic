"""SportAPI.ai (offre gratuite : 2 000 requêtes/jour, 14 000/mois ; clé SPORTAPI_KEY côté serveur).

Rôle : source de secours, jamais de référence pour les statistiques.
* Résultats rapides : matchs terminés depuis plus de 2 h 30 encore sans score dans la base (championnats
  européens et sud-américains dont football-data.co.uk publie le résultat avec retard) → score final et
  score à la mi-temps, uniquement pour un match « FT » (temps réglementaire ; prolongations écartées).
* Direct de secours : scores et minute en cours quand AllSportsAPI ne répond pas (ou n'est pas configuré).
Aucun corner ni carton n'est repris (SportAPI ne publie pas les corners).
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import ApiUsage, Competition, Match, SyncRun
from ..providers.names import similarity


def team_similarity(name: str, team) -> float:
    return max(similarity(name, team.name), similarity(name, team.norm_name or ""))

log = logging.getLogger("sam.sportapi")
UTC = timezone.utc
BASE = "https://sportapi.ai/api"
NAME = "sportapi"
_lock = threading.Lock()
_cache: dict = {"at": None, "rows": [], "error": None}


class SportApiError(Exception):
    pass


def _used(db: Session) -> int:
    row = db.get(ApiUsage, (NAME, date.today().isoformat()))
    return row.requests if row else 0


def _count(db: Session, n: int = 1) -> None:
    from .usage import bump_usage
    bump_usage(db, NAME, n)


def _get(db: Session, path: str) -> dict:
    cfg = get_settings()
    if not cfg.sportapi_key:
        raise SportApiError("clé absente (SPORTAPI_KEY)")
    if _used(db) >= cfg.sportapi_daily_budget:
        raise SportApiError("budget quotidien prudent atteint")
    try:
        r = httpx.get(BASE + path, headers={"X-Api-Key": cfg.sportapi_key, "User-Agent": cfg.http_user_agent},
                      timeout=cfg.http_timeout)
    except httpx.HTTPError as exc:
        raise SportApiError(f"erreur réseau ({exc.__class__.__name__})")
    finally:
        _count(db)
    if r.status_code != 200:
        raise SportApiError(f"HTTP {r.status_code}")
    try:
        data = r.json()
    except ValueError:
        raise SportApiError("réponse illisible")
    if not data.get("success"):
        raise SportApiError("requête refusée")
    return data


def fixtures_on(db: Session, day: str) -> list[dict]:
    return _get(db, f"/fixtures/date/{day}").get("data") or []


def _kickoff(x: dict) -> Optional[datetime]:
    try:
        return datetime.fromisoformat((x.get("kickoff_utc") or "").replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None


def find(cands: list[Match], x: dict) -> Optional[Match]:
    ko = _kickoff(x)
    if ko is None:
        return None
    home, away = x.get("home_team") or "", x.get("away_team") or ""
    best, score = None, 0.0
    for m in cands:
        if abs((m.kickoff - ko).total_seconds()) > 3 * 3600:
            continue
        s = min(max(team_similarity(home, m.home_team), similarity(x.get("home_short") or "", m.home_team.name)),
                max(team_similarity(away, m.away_team), similarity(x.get("away_short") or "", m.away_team.name)))
        if s > score:
            best, score = m, s
    return best if score >= 80 else None


def complete_results(db: Session, now: datetime, max_details: int = 8) -> Optional[dict]:
    """Scores finaux (et mi-temps) des matchs terminés encore sans résultat ; journalisé dans sync_runs."""
    from .sync import _run
    cfg = get_settings()
    if not cfg.sportapi_key:
        return None
    todo = db.scalars(select(Match).join(Competition, Match.competition_id == Competition.id).where(
        Competition.enabled.is_(True), Match.status.in_(("SCHEDULED", "LIVE")),
        Match.kickoff <= now - timedelta(minutes=150), Match.kickoff >= now - timedelta(days=3))).unique().all()
    if not todo:
        return None

    def work(run: SyncRun) -> tuple[int, str]:
        done, errors, details = 0, [], 0
        for day in sorted({m.kickoff.date().isoformat() for m in todo})[-3:]:
            try:
                rows = fixtures_on(db, day)
            except SportApiError as exc:
                errors.append(f"{day} : {exc}")
                break
            for x in rows:
                if x.get("status") != "FT" or x.get("home_score") is None:
                    continue
                m = find([t for t in todo if t.status != "FINISHED"], x)
                if m is None:
                    continue
                ht = (None, None)
                if details < max_details:
                    try:
                        fx = _get(db, f"/fixtures/{x['id']}").get("fixture") or {}
                        details += 1
                        ht = (fx.get("ht_home"), fx.get("ht_away"))
                    except SportApiError as exc:
                        errors.append(str(exc))
                m.home_goals, m.away_goals = int(x["home_score"]), int(x["away_score"])
                if None not in ht and m.ht_home_goals is None:
                    m.ht_home_goals, m.ht_away_goals = int(ht[0]), int(ht[1])
                m.status = "FINISHED"
                done += 1
            db.commit()
        msg = f"{done} résultat(s) final(aux) enregistré(s) sur {len(todo)} en attente"
        if errors:
            msg += " ; " + errors[0]
        return done, msg

    return _run(db, NAME, "résultats", work)


def live_fallback(db: Session, now: datetime, cands: list[Match]) -> dict:
    """Scores en direct de secours (cache de 5 minutes, un appel pour tous les matchs du jour)."""
    cfg = get_settings()
    if not cfg.sportapi_key or not cands:
        return {"ok": False, "live": [], "updated": 0, "error": None}
    with _lock:
        if _cache["at"] is None or time.monotonic() - _cache["at"] >= cfg.sportapi_live_seconds:
            _cache["at"] = time.monotonic()
            try:
                _cache.update(rows=fixtures_on(db, now.date().isoformat()), error=None)
            except SportApiError as exc:
                _cache.update(rows=[], error=f"SportAPI : {exc}")
        rows, error = _cache["rows"], _cache["error"]
    live, updated = [], 0
    for x in rows:
        st = x.get("status")
        if st not in ("LIVE", "FT"):
            continue
        m = find(cands, x)
        if m is None or x.get("home_score") is None:
            continue
        if st == "FT":
            if m.status != "FINISHED":
                m.home_goals, m.away_goals = int(x["home_score"]), int(x["away_score"])
                m.status = "FINISHED"
                updated += 1
            continue
        minute = (x.get("minute") or "").replace("'", "")
        paused = minute.upper() in ("HT", "MT")
        live.append({"match_id": m.id, "status": "Mi-temps" if paused else "En cours",
                     "minute": None if paused or not minute else minute, "home": x.get("home_score"),
                     "away": x.get("away_score"), "ht_home": None, "ht_away": None, "source": NAME})
    if updated:
        db.commit()
    return {"ok": error is None, "live": live, "updated": updated, "error": error}
