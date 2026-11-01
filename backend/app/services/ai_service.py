"""Orchestration de l'analyse IA : cache par match, quota quotidien, génération à la demande et en avance."""
from __future__ import annotations

import logging
import threading
from datetime import date, timedelta
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..ai.analyst import (SCHEMA, SYSTEM_PROMPT, build_dossier, check_output, enrich_for_display, sanitize,
                          user_prompt)
from ..ai.providers import AIError, call_with_fallback, configured_providers, provider_info
from ..config import get_settings
from ..models import AiAnalysis, Analysis, ApiUsage, Match, Prediction, utcnow

log = logging.getLogger("sam.ai")
USAGE_KEY = "ia"
_match_locks: dict[int, threading.Lock] = {}
_locks_guard = threading.Lock()


def _lock_for(match_id: int) -> threading.Lock:
    with _locks_guard:
        return _match_locks.setdefault(match_id, threading.Lock())


def usage_today(db: Session) -> int:
    row = db.get(ApiUsage, (USAGE_KEY, date.today().isoformat()))
    return row.requests if row else 0


def _count_call(db: Session) -> None:
    key = (USAGE_KEY, date.today().isoformat())
    row = db.get(ApiUsage, key)
    if row is None:
        db.add(ApiUsage(provider=key[0], day=key[1], requests=1))
    else:
        row.requests += 1
    db.commit()


def status(db: Session) -> dict:
    info = provider_info()
    info.update({"used_today": usage_today(db), "daily_budget": get_settings().ai_daily_budget,
                 "cached": db.query(AiAnalysis).count()})
    return info


def _keys(db: Session, match_id: int) -> tuple[set, set]:
    preds = db.scalars(select(Prediction).where(Prediction.match_id == match_id)).unique().all()
    return ({(p.match_id, p.market_key) for p in preds if p.value_pick},
            {(p.match_id, p.market_key) for p in preds if p.featured})


def _fresh(row: AiAnalysis, m: Match) -> bool:
    if m.kickoff <= utcnow():
        return True  # match commencé : on garde l'analyse rédigée avant le match
    return row.created_at >= utcnow() - timedelta(hours=get_settings().ai_cache_hours)


def _response(row: AiAnalysis, payload: dict) -> dict:
    return {"status": "ok", "provider": row.provider, "model": row.model, "created_at": row.created_at.isoformat(),
            "based_on": row.based_on.isoformat() if row.based_on else None, "removed_sentences": row.removed,
            "analysis": enrich_for_display(row.content, payload)}


def generate(db: Session, m: Match, a: Analysis) -> AiAnalysis:
    """Rédaction (deux essais au plus) puis vérification ; lève AIError en cas d'échec."""
    from ..api.catalog import match_insights
    from .analysis import match_summary

    payload = a.payload
    insights = match_insights(m.id, db)
    value_keys, featured_keys = _keys(db, m.id)
    dossier = build_dossier(payload.get("match") or match_summary(m), payload, insights, value_keys, featured_keys)
    market_keys = {r["cle"] for r in dossier["marches"]}
    feedback: Optional[list[str]] = None
    out, prov = None, None
    for _ in range(2):
        if usage_today(db) >= get_settings().ai_daily_budget:
            raise AIError("Quota quotidien d'analyses IA atteint : nouvelles analyses demain")
        _count_call(db)
        out, prov = call_with_fallback(SYSTEM_PROMPT, user_prompt(dossier, feedback), SCHEMA)
        feedback = check_output(out, dossier, market_keys)
        if not feedback:
            break
        log.info("Analyse IA du match %s refusée : %s", m.id, feedback[:3])
    content, removed = sanitize(out, dossier, market_keys)
    if not content.get("resume") or not content.get("pronostic_principal"):
        raise AIError("L'analyse IA n'a pas passé les contrôles de fiabilité", retryable=True)
    row = db.scalar(select(AiAnalysis).where(AiAnalysis.match_id == m.id))
    if row is None:
        row = AiAnalysis(match_id=m.id)
        db.add(row)
    row.created_at = utcnow()
    row.based_on = a.computed_at
    row.provider = prov.label
    row.model = prov.model
    row.content = content
    row.removed = removed
    db.commit()
    return row


def get_match_ai(db: Session, match_id: int, allow_generate: bool = True) -> dict:
    m = db.get(Match, match_id)
    if m is None:
        return {"status": "not_found", "message": "Match introuvable"}
    a = db.scalar(select(Analysis).where(Analysis.match_id == m.id))
    row = db.scalar(select(AiAnalysis).where(AiAnalysis.match_id == m.id))
    if a is None or a.status != "ok":
        return {"status": "insufficient", "message": "Données insuffisantes : aucune analyse IA possible pour ce match"}
    if row is not None and _fresh(row, m):
        return _response(row, a.payload)
    if not configured_providers():
        return {"status": "not_configured", "message": "L'analyse IA n'est pas encore activée sur ce site"}
    if m.kickoff <= utcnow():
        if row is not None:
            return _response(row, a.payload)
        return {"status": "unavailable", "message": "L'analyse IA est rédigée avant le coup d'envoi uniquement"}
    if not allow_generate:
        return {"status": "pending", "message": "Analyse IA pas encore rédigée"}
    lock = _lock_for(m.id)
    with lock:  # une seule rédaction à la fois par match
        db.expire_all()
        row = db.scalar(select(AiAnalysis).where(AiAnalysis.match_id == m.id))
        if row is not None and _fresh(row, m):
            return _response(row, a.payload)
        try:
            row = generate(db, m, a)
        except AIError as exc:
            db.rollback()
            if row is not None:  # ancienne analyse plutôt que rien
                res = _response(row, a.payload)
                res["stale"] = True
                return res
            return {"status": "error", "message": str(exc), "retryable": exc.retryable}
    return _response(row, a.payload)


def pregenerate(db: Session, hours: int = 36, limit: int = 12) -> dict:
    """Rédige à l'avance les analyses des matchs portant une Sélection SAM ou un pronostic à cote."""
    if not configured_providers():
        return {"generated": 0, "skipped": "non configuré"}
    now = utcnow()
    ids = db.scalars(select(Prediction.match_id).join(Match, Prediction.match_id == Match.id).where(
        (Prediction.featured.is_(True)) | (Prediction.value_pick.is_(True)),
        Match.kickoff > now + timedelta(minutes=30), Match.kickoff < now + timedelta(hours=hours))
        .order_by(Match.kickoff)).all()
    done, errors = 0, 0
    for mid in list(dict.fromkeys(ids)):
        if done >= limit or usage_today(db) >= get_settings().ai_daily_budget * 0.6:
            break  # garder une marge pour les demandes des membres
        row = db.scalar(select(AiAnalysis).where(AiAnalysis.match_id == mid))
        m = db.get(Match, mid)
        if row is not None and _fresh(row, m):
            continue
        res = get_match_ai(db, mid)
        if res["status"] == "ok":
            done += 1
        else:
            errors += 1
            if errors >= 3:
                break
    return {"generated": done, "errors": errors}


def pregenerate_in_background() -> None:
    from ..db import SessionLocal

    def run():
        try:
            with SessionLocal() as db:
                log.info("Analyses IA préparées : %s", pregenerate(db))
        except Exception:
            log.exception("Préparation des analyses IA impossible")

    if configured_providers():
        threading.Thread(target=run, daemon=True, name="ia-pregenerate").start()
