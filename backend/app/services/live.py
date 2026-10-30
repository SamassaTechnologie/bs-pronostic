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
    best, score = None, 0.0
    for c in cands:
        s = min(similarity(home, c.home_team.name), similarity(away, c.away_team.name))
        if s > score:
            best, score = c, s
    return best if score >= 78 else None


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
        rows = fo.matches_between((now - timedelta(days=days_back)).date().isoformat(), now.date().isoformat())
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


def live_board(db: Session, force: bool = False) -> dict:
    """Matchs en cours + pronostics concernés. Les appels externes sont limités à 1 par minute."""
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
    # Matchs commencés depuis moins de 2 h 30 sans résultat final (couverts ou non par le direct).
    started = db.scalars(select(Match).join(Competition, Match.competition_id == Competition.id).where(
        Competition.enabled.is_(True), Match.kickoff <= now, Match.kickoff >= now - timedelta(minutes=150),
        Match.status != "FINISHED").order_by(Match.kickoff)).unique().all()
    ids = {m.id for m in started} | set(live)
    if not ids:
        return {"items": [], "refreshed_at": refreshed, "error": error}
    matches = {m.id: m for m in db.scalars(select(Match).where(Match.id.in_(ids))).unique().all()}
    preds = db.scalars(select(Prediction).where(Prediction.match_id.in_(ids))).unique().all()
    by_match: dict[int, list] = {}
    for p in preds:
        by_match.setdefault(p.match_id, []).append(p)
    items = []
    for mid, m in sorted(matches.items(), key=lambda kv: kv[1].kickoff):
        lv = live.get(mid)
        items.append({
            "match": match_summary(m),
            "live": lv,
            "covered": lv is not None,
            "picks": [{"market_key": p.market_key, "market_label": p.market_label, "probability": p.probability,
                       "featured": bool(p.featured), "state": _pick_state(p, m, lv)} for p in by_match.get(mid, [])],
        })
    return {"items": items, "refreshed_at": refreshed, "error": error}
