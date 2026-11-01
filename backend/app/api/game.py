"""API de la section « Jouer » (jetons virtuels). Réservée à l'application : secret partagé + identifiant membre
transmis par le serveur Next.js (jamais par le navigateur)."""
from __future__ import annotations

import hmac
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import Bet, Match
from ..services import game
from ..services.live import match_live_state
from .deps import get_db

router = APIRouter(prefix="/api/jeu", tags=["jouer"])
UTC = timezone.utc


def _now() -> datetime:
    return datetime.now(UTC)


def member(x_app_token: Optional[str] = Header(default=None), x_member_id: Optional[str] = Header(default=None),
           x_member_name: Optional[str] = Header(default=None)) -> tuple[str, Optional[str]]:
    expected = get_settings().assistant_token
    if expected and not hmac.compare_digest(x_app_token or "", expected):
        raise HTTPException(401, "Accès réservé à l'application SAM-Prédiction")
    if not x_member_id:
        raise HTTPException(401, "Connectez-vous pour jouer")
    from urllib.parse import unquote
    return x_member_id[:64], unquote(x_member_name or "").strip()[:60] or None


def _tz(name: Optional[str]) -> ZoneInfo:
    try:
        return ZoneInfo(name or get_settings().default_timezone)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo(get_settings().default_timezone)


def _wallet_row(db: Session, mid: str, name: Optional[str]) -> dict:
    w = game.wallet(db, mid, name, _now().date())
    pending = db.query(Bet).filter(Bet.member_id == mid, Bet.status == "pending").count()
    return {"balance": w.balance, "name": w.display_name, "pending": pending, "daily_bonus": game.DAILY_BONUS,
            **game.member_summary(db, mid)}


@router.get("/board")
def board(jour: str = Query("aujourdhui", pattern="^(aujourdhui|demain|tout|direct)$"), tz: Optional[str] = None,
          db: Session = Depends(get_db), who=Depends(member)):
    now = _now()
    zone = _tz(tz)
    today = now.astimezone(zone).date()
    out = {"wallet": _wallet_row(db, *who), "jour": jour}
    if jour == "direct":
        ms = db.scalars(select(Match).where(Match.kickoff <= now, Match.kickoff >= now - timedelta(minutes=150),
                                            Match.status.in_(("SCHEDULED", "LIVE")))
                        .order_by(Match.kickoff)).unique().all()
        from ..services.analysis import match_summary
        live = []
        for m in ms:
            st = match_live_state(db, m)
            if st.get("state") == "live":
                live.append({"match": match_summary(m), "live": st})
        out["live"] = live
        out["groups"] = []
        return out
    d0 = today + timedelta(days=1 if jour == "demain" else 0)
    start = datetime.combine(d0, time(0), tzinfo=zone).astimezone(UTC)
    end = start + timedelta(days=3 if jour == "tout" else 1)
    out["groups"] = game.board(db, start, end, now)
    return out


@router.get("/matchs/{match_id}")
def match(match_id: int, db: Session = Depends(get_db), who=Depends(member)):
    try:
        res = game.match_markets(db, match_id, _now())
    except game.GameError as exc:
        raise HTTPException(404, str(exc)) from exc
    res["wallet"] = _wallet_row(db, *who)
    return res


class Sel(BaseModel):
    match_id: int
    market_key: str = Field(max_length=16)


class BetRequest(BaseModel):
    selections: list[Sel] = Field(min_length=1, max_length=game.MAX_LEGS)
    stake: int
    mode: str = Field("combine", pattern="^(simple|combine)$")


@router.post("/paris")
def place(req: BetRequest, db: Session = Depends(get_db), who=Depends(member)):
    mid, name = who
    game.wallet(db, mid, name, _now().date())
    try:
        bets = game.place_bets(db, mid, [(s.match_id, s.market_key) for s in req.selections], req.stake, req.mode, _now())
    except game.GameError as exc:
        db.rollback()
        raise HTTPException(422, str(exc)) from exc
    return {"bets": [game.bet_row(b) for b in bets], "wallet": _wallet_row(db, mid, name)}


@router.post("/devis")
def quote(req: BetRequest, db: Session = Depends(get_db), who=Depends(member)):
    """Cotes et probabilité SAM du coupon, relues côté serveur (sans enregistrer de pari)."""
    from .public import evaluate_selections
    now = _now()
    legs, errors = [], []
    for s in req.selections:
        try:
            leg, m = game._leg_for(db, s.match_id, s.market_key, now)
            legs.append({"match_id": s.match_id, "market_key": s.market_key, "label": leg.label, "odds": leg.odds,
                         "odds_source": leg.odds_source, "probability": leg.probability,
                         "match": f"{m.home_team.name} – {m.away_team.name}", "kickoff": m.kickoff.isoformat(),
                         "competition": m.competition.name})
        except game.GameError as exc:
            errors.append({"match_id": s.match_id, "market_key": s.market_key, "error": str(exc)})
    total, sam_p, combo_error = None, None, None
    if len(legs) >= 2:
        ids = [l["match_id"] for l in legs]
        if len(set(ids)) < len(ids):
            combo_error = "Un combiné ne peut contenir qu'une sélection par match"
        else:
            total = 1.0
            for l in legs:
                total *= l["odds"]
            total = round(total, 2)
            try:
                sam_p = evaluate_selections(db, [(l["match_id"], l["market_key"]) for l in legs]).get("probability")
            except ValueError:
                sam_p = None
    return {"legs": legs, "errors": errors, "total_odds": total, "sam_probability": sam_p, "combo_error": combo_error,
            "wallet": _wallet_row(db, *who), "min_stake": game.MIN_STAKE, "max_stake": game.MAX_STAKE}


@router.get("/mes-paris")
def my_bets(statut: str = Query("en-cours", pattern="^(en-cours|termines)$"), db: Session = Depends(get_db),
            who=Depends(member)):
    mid, name = who
    q = select(Bet).where(Bet.member_id == mid)
    q = q.where(Bet.status == "pending") if statut == "en-cours" else q.where(Bet.status != "pending")
    bets = db.scalars(q.order_by(Bet.created_at.desc()).limit(50)).unique().all()
    return {"wallet": _wallet_row(db, mid, name), "bets": [game.bet_row(b) for b in bets],
            "ranking": game.ranking(db, mid, _now())}
