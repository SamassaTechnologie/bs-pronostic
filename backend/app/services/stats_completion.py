"""Complément des statistiques de match terminés (corners, cartons, score à la mi-temps) à partir de sources
gratuites rapides, pour régler pronostics et paris sans attendre la mise à jour de football-data.co.uk.

* footballdata.io (offre gratuite, 1 000 requêtes/mois) : Premier League, LaLiga, Ligue des champions,
  Ligue Europa ; une requête par championnat renvoie les derniers résultats avec corners et cartons.
* Sportmonks (offre gratuite) : Premiership écossaise et Superliga danoise ; scores par mi-temps, corners,
  cartons.

Seuls les matchs déjà terminés dans la base et auxquels il manque une donnée sont complétés ; les valeurs
existantes ne sont jamais écrasées. Clés : FOOTBALLDATA_IO_KEY, SPORTMONKS_KEY (serveur uniquement).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import Competition, Match, SyncRun, utcnow
from ..providers.names import similarity

log = logging.getLogger("sam.stats")

FDIO_LEAGUES = {"ENG1": 15, "ESP1": 10, "UCL": 45, "UEL": 46}
SPORTMONKS_LEAGUES = {"SCO1": 501, "DEN1": 271}
FDIO_DAILY_CAP = 25  # ≈ 750/mois sur 1 000 : marge pour les tests et les reprises
SM_STAT_CORNERS, SM_STAT_YELLOW, SM_STAT_RED = 34, 84, 83


def _missing(m: Match) -> bool:
    return m.home_corners is None or m.home_yellow is None or m.ht_home_goals is None


def _find(candidates: list[Match], home: str, away: str, when: datetime) -> Optional[Match]:
    best, score = None, 0.0
    for m in candidates:
        if abs((m.kickoff - when).total_seconds()) > 36 * 3600:
            continue
        s = min(similarity(home, m.home_team.name), similarity(away, m.away_team.name))
        if s > score:
            best, score = m, s
    return best if score >= 78 else None


def _todo(db: Session, code: str, now: datetime) -> list[Match]:
    comp = db.scalar(select(Competition).where(Competition.code == code, Competition.enabled.is_(True)))
    if comp is None:
        return []
    ms = db.scalars(select(Match).where(Match.competition_id == comp.id, Match.status == "FINISHED",
                                        Match.kickoff >= now - timedelta(days=5))).unique().all()
    return [m for m in ms if _missing(m)]


def _fill(m: Match, ht: Optional[tuple], corners: Optional[tuple], yellow: Optional[tuple], red: Optional[tuple]) -> bool:
    changed = False
    if ht and None not in ht and m.ht_home_goals is None:
        m.ht_home_goals, m.ht_away_goals = ht
        changed = True
    if corners and None not in corners and m.home_corners is None:
        m.home_corners, m.away_corners = corners
        changed = True
    if yellow and None not in yellow and m.home_yellow is None:
        m.home_yellow, m.away_yellow = yellow
        m.home_red, m.away_red = red if red and None not in red else (0, 0)
        changed = True
    return changed


def _fdio(db: Session, now: datetime, key: str) -> tuple[int, int, list[str]]:
    from .sync import _add_api_usage, _api_usage_today
    done, calls, errors = 0, 0, []
    for code, league in FDIO_LEAGUES.items():
        todo = _todo(db, code, now)
        if not todo:
            continue
        if _api_usage_today(db, "footballdata_io") + calls >= FDIO_DAILY_CAP:
            errors.append("quota quotidien prudent atteint")
            break
        try:
            r = httpx.get("https://footballdata.io/api/v1/fixtures/results", params={"league_id": league},
                          headers={"Authorization": f"Bearer {key}"}, timeout=get_settings().http_timeout)
            calls += 1
            if r.status_code != 200:
                errors.append(f"{code} : HTTP {r.status_code}")
                continue
            matches = ((r.json().get("data") or {}).get("matches")) or []
        except (httpx.HTTPError, ValueError) as exc:
            errors.append(f"{code} : {exc.__class__.__name__}")
            continue
        for x in matches:
            if x.get("status") != "complete":
                continue
            try:
                when = datetime.fromisoformat(x["match_date"]).replace(tzinfo=now.tzinfo)
            except (KeyError, ValueError):
                continue
            m = _find(todo, (x.get("home_team") or {}).get("team_name", ""), (x.get("away_team") or {}).get("team_name", ""), when)
            if m is None:
                continue
            st = x.get("stats") or {}
            c, cards = st.get("corners") or {}, st.get("cards") or {}
            y, rd = cards.get("yellow") or {}, cards.get("red") or {}
            if _fill(m, None, (c.get("home"), c.get("away")), (y.get("home"), y.get("away")), (rd.get("home"), rd.get("away"))):
                done += 1
        db.commit()
    _add_api_usage(db, "footballdata_io", calls)
    db.commit()
    return done, calls, errors


def _sportmonks(db: Session, now: datetime, key: str) -> tuple[int, int, list[str]]:
    done, calls, errors = 0, 0, []
    todo_by = {code: _todo(db, code, now) for code in SPORTMONKS_LEAGUES}
    if not any(todo_by.values()):
        return 0, 0, []
    start = (now - timedelta(days=5)).date().isoformat()
    end = now.date().isoformat()
    try:
        r = httpx.get(f"https://api.sportmonks.com/v3/football/fixtures/between/{start}/{end}",
                      params={"api_token": key, "include": "participants;scores;statistics",
                              "filters": f"fixtureStatisticTypes:{SM_STAT_CORNERS},{SM_STAT_YELLOW},{SM_STAT_RED}",
                              "per_page": 50}, timeout=get_settings().http_timeout)
        calls += 1
        if r.status_code != 200:
            return 0, calls, [f"HTTP {r.status_code}"]
        fixtures = r.json().get("data") or []
    except (httpx.HTTPError, ValueError) as exc:
        return 0, calls, [exc.__class__.__name__]
    league_code = {v: k for k, v in SPORTMONKS_LEAGUES.items()}
    for fx in fixtures:
        code = league_code.get(fx.get("league_id"))
        todo = todo_by.get(code) or []
        if not todo or fx.get("state_id") != 5:  # 5 = terminé
            continue
        side = {p["id"]: (p.get("meta") or {}).get("location") for p in fx.get("participants") or []}
        names = {(p.get("meta") or {}).get("location"): p.get("name", "") for p in fx.get("participants") or []}
        try:
            when = datetime.fromisoformat(fx["starting_at"]).replace(tzinfo=now.tzinfo)
        except (KeyError, ValueError):
            continue
        m = _find(todo, names.get("home", ""), names.get("away", ""), when)
        if m is None:
            continue
        ht = {"home": None, "away": None}
        for s in fx.get("scores") or []:
            if s.get("description") == "1ST_HALF":
                ht[(s.get("score") or {}).get("participant")] = (s.get("score") or {}).get("goals")
        stats: dict[int, dict] = {}
        for s in fx.get("statistics") or []:
            loc = s.get("location") or side.get(s.get("participant_id"))
            stats.setdefault(s.get("type_id"), {})[loc] = (s.get("data") or {}).get("value")

        def pair(t):
            v = stats.get(t)
            return (v.get("home"), v.get("away")) if v else None
        red = pair(SM_STAT_RED) or ((0, 0) if pair(SM_STAT_YELLOW) else None)
        if _fill(m, (ht["home"], ht["away"]), pair(SM_STAT_CORNERS), pair(SM_STAT_YELLOW), red):
            done += 1
    db.commit()
    return done, calls, errors


def complete_stats(db: Session, now: Optional[datetime] = None) -> list[dict]:
    """Complète les statistiques manquantes ; un journal par source dans sync_runs."""
    from .sync import _run
    now = now or utcnow()
    cfg = get_settings()
    out = []
    for name, key, fn in (("footballdata_io", cfg.footballdata_io_key, _fdio),
                          ("sportmonks", cfg.sportmonks_key, _sportmonks)):
        if not key:
            continue

        def work(run: SyncRun, fn=fn, key=key) -> tuple[int, str]:
            done, calls, errors = fn(db, now, key)
            msg = f"{done} match(s) complété(s) : corners, cartons, mi-temps ({calls} requête(s))"
            if errors:
                msg += " ; " + " ; ".join(errors[:2])
            return done, msg

        out.append(_run(db, name, "statistiques", work))
    return out
