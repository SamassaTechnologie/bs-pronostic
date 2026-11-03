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
from ..models import AiAnalysis, Analysis, ApiUsage, Match, Prediction, Wallet, utcnow
from .ai_settings import get_ai_settings, member_allowed

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


def _usage(db: Session, key: str) -> int:
    row = db.get(ApiUsage, (key, date.today().isoformat()))
    return row.requests if row else 0


def _count_call(db: Session, kind: str = "analyse") -> None:
    """Un appel au fournisseur d'IA : compteur global « ia » et compteur par fonction (analyse / assistant)."""
    day = date.today().isoformat()
    for k in (USAGE_KEY, f"{USAGE_KEY}-{kind}"):
        row = db.get(ApiUsage, (k, day))
        if row is None:
            db.add(ApiUsage(provider=k, day=day, requests=1))
        else:
            row.requests += 1
    db.commit()


def _budget(db: Session) -> int:
    return int(get_ai_settings(db)["daily_budget"])


def status(db: Session) -> dict:
    info = provider_info()
    cfg = get_ai_settings(db)
    day = date.today().isoformat()
    rows = db.query(ApiUsage).filter(ApiUsage.day == day, ApiUsage.provider.like("as:%")).all()
    names = {w.member_id: w.display_name for w in db.query(Wallet).all()}
    members = sorted(({"member": names.get(r.provider[3:]) or f"Membre {r.provider[3:7].upper()}",
                       "questions": r.requests} for r in rows), key=lambda x: x["questions"], reverse=True)
    info.update({"used_today": usage_today(db), "daily_budget": cfg["daily_budget"],
                 "used_analyses": _usage(db, f"{USAGE_KEY}-analyse"),
                 "used_assistant": _usage(db, f"{USAGE_KEY}-assistant"),
                 "cached": db.query(AiAnalysis).count(), "settings": cfg,
                 "members_today": members[:15], "questions_today": sum(r.requests for r in rows)})
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
    web = (row.content or {}).get("_web") or {}
    return {"status": "ok", "provider": row.provider, "model": row.model, "created_at": row.created_at.isoformat(),
            "based_on": row.based_on.isoformat() if row.based_on else None, "removed_sentences": row.removed,
            "analysis": enrich_for_display(row.content, payload),
            "web_sources": web.get("sources") or [], "web_at": web.get("at")}


def _web_context(db: Session, dossier: dict) -> Optional[dict]:
    """Recherche Google récente sur le match (si autorisée et dans le quota du jour) ; None sinon."""
    from ..ai.providers import web_brief
    cfg = get_ai_settings(db)
    if not cfg.get("web_search") or _usage(db, f"{USAGE_KEY}-web") >= int(cfg.get("web_daily", 0)):
        return None
    if usage_today(db) >= _budget(db):
        return None
    m = dossier.get("match") or {}
    prompt = (f"Recherche les informations les plus récentes (7 derniers jours) sur le match de football "
              f"{m.get('domicile')} – {m.get('exterieur')} ({m.get('competition')}, {m.get('pays')}, le {m.get('date_utc')}). "
              "Donne en français 5 puces au maximum, factuelles et sourcées : joueurs blessés, suspendus ou incertains, "
              "retours de blessure, changement d'entraîneur, enjeu ou contexte particulier. Aucun pronostic, aucune "
              "cote, aucune statistique. Si rien de fiable et récent n'est trouvé, réponds seulement : "
              "« Aucune information récente fiable. »")
    try:
        _count_call(db, "web")
        res = web_brief(prompt)
    except AIError as exc:
        log.info("Recherche web impossible : %s", exc)
        return None
    if not res["sources"] or not res["text"] or "Aucune information récente fiable" in res["text"]:
        return None
    return res


def generate(db: Session, m: Match, a: Analysis) -> AiAnalysis:
    """Rédaction (deux essais au plus) puis vérification ; lève AIError en cas d'échec."""
    from ..api.catalog import match_insights
    from .analysis import match_summary

    payload = a.payload
    insights = match_insights(m.id, db)
    value_keys, featured_keys = _keys(db, m.id)
    dossier = build_dossier(payload.get("match") or match_summary(m), payload, insights, value_keys, featured_keys)
    market_keys = {r["cle"] for r in dossier["marches"]}
    web = _web_context(db, dossier)
    if web:
        dossier["actualites_web"] = {"texte": web["text"], "sources": [x["title"] for x in web["sources"]]}
    feedback: Optional[list[str]] = None
    out, prov = None, None
    for _ in range(2):
        if usage_today(db) >= _budget(db):
            raise AIError("Quota quotidien d'analyses IA atteint : nouvelles analyses demain")
        _count_call(db, "analyse")
        out, prov = call_with_fallback(SYSTEM_PROMPT, user_prompt(dossier, feedback), SCHEMA)
        feedback = check_output(out, dossier, market_keys)
        if not feedback:
            break
        log.info("Analyse IA du match %s refusée : %s", m.id, feedback[:3])
    content, removed = sanitize(out, dossier, market_keys)
    if web and content.get("actualites"):
        content["_web"] = {"sources": web["sources"], "queries": web["queries"], "at": utcnow().isoformat()}
    else:
        content["actualites"] = []  # jamais d'« actualité » sans source
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


def get_match_ai(db: Session, match_id: int, allow_generate: bool = True, internal: bool = False) -> dict:
    """internal=True : préparation automatique (seule autorisée à rédiger en mode « preparees »)."""
    mode = get_ai_settings(db)["analyses"]
    if mode == "off":
        return {"status": "disabled", "message": "L'analyse IA est désactivée pour le moment"}
    if mode == "preparees" and not internal:
        allow_generate = False
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
        return {"status": "pending", "message": "Analyse IA rédigée uniquement pour les matchs de la Sélection SAM et "
                                                "les pronostics à cote" if mode == "preparees" else "Analyse IA pas encore rédigée"}
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


def pregenerate(db: Session, hours: int = 36, limit: Optional[int] = None) -> dict:
    """Rédige à l'avance les analyses des matchs portant une Sélection SAM ou un pronostic à cote."""
    if not configured_providers():
        return {"generated": 0, "skipped": "non configuré"}
    cfg = get_ai_settings(db)
    if cfg["analyses"] == "off":
        return {"generated": 0, "skipped": "désactivé"}
    limit = int(cfg["pregenerate_limit"]) if limit is None else limit
    if limit <= 0:
        return {"generated": 0, "skipped": "préparation désactivée"}
    now = utcnow()
    ids = db.scalars(select(Prediction.match_id).join(Match, Prediction.match_id == Match.id).where(
        (Prediction.featured.is_(True)) | (Prediction.value_pick.is_(True)),
        Match.kickoff > now + timedelta(minutes=30), Match.kickoff < now + timedelta(hours=hours))
        .order_by(Match.kickoff)).all()
    done, errors = 0, 0
    for mid in list(dict.fromkeys(ids)):
        if done >= limit or usage_today(db) >= _budget(db) * 0.6:
            break  # garder une marge pour les demandes des membres
        row = db.scalar(select(AiAnalysis).where(AiAnalysis.match_id == mid))
        m = db.get(Match, mid)
        if row is not None and _fresh(row, m):
            continue
        res = get_match_ai(db, mid, internal=True)
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


# ---------------------------------------------------------------------------
# Assistant conversationnel

def _member_usage(db: Session, member: str) -> int:
    row = db.get(ApiUsage, (f"as:{member}"[:40], date.today().isoformat()))
    return row.requests if row else 0


def _count_member(db: Session, member: str) -> None:
    key = (f"as:{member}"[:40], date.today().isoformat())
    row = db.get(ApiUsage, key)
    if row is None:
        db.add(ApiUsage(provider=key[0], day=key[1], requests=1))
    else:
        row.requests += 1
    db.commit()


def ask_assistant(db: Session, question: str, history: list[dict], member: Optional[str],
                  match_id: Optional[int] = None, email: Optional[str] = None) -> dict:
    from ..ai.assistant import SYSTEM, TOOLS, Toolbox, check_answer, references
    from ..ai.providers import chat_with_tools

    cfg = get_ai_settings(db)
    if not configured_providers():
        return {"status": "not_configured", "message": "L'assistant IA n'est pas encore activé sur ce site"}
    if cfg["assistant"] == "off":
        return {"status": "disabled", "message": "L'assistant IA est désactivé pour le moment."}
    if not member_allowed(cfg, email):
        return {"status": "forbidden", "message": "L'assistant IA est réservé aux membres autorisés par l'administrateur."}
    who = member or "anonyme"
    daily = int(cfg["member_daily"])
    if _member_usage(db, who) >= daily:
        return {"status": "quota", "message": (f"Limite de {daily} questions par jour atteinte : revenez demain."
                                               if daily else "L'assistant IA est suspendu pour le moment.")}
    if usage_today(db) >= int(cfg["daily_budget"]):
        return {"status": "quota", "message": "L'assistant a atteint son quota du jour : revenez demain."}
    _count_member(db, who)

    box = Toolbox(db)
    context = [question] + [h["text"] for h in history]
    hist = [h for h in history if h.get("text")][-8:]
    q = question
    if match_id:
        a = db.scalar(select(Analysis).where(Analysis.match_id == match_id))
        if a is not None and a.status == "ok":
            info = box._remember(a)
            q = (f"(Le membre consulte la fiche du match {info['home']} – {info['away']}, match_id {match_id}.)\n"
                 + question)
    hist.append({"role": "user", "text": q})

    def on_call() -> None:
        if usage_today(db) >= int(cfg["daily_budget"]):
            raise AIError("Quota quotidien de l'IA atteint : revenez demain")
        _count_call(db, "assistant")

    try:
        text, prov = chat_with_tools(SYSTEM, hist, TOOLS, box.run, on_call, max_steps=int(cfg["max_steps"]))
    except AIError as exc:
        db.rollback()
        return {"status": "error", "message": str(exc), "retryable": exc.retryable}
    clean, dropped = check_answer(text, box, context)
    if dropped:
        log.info("Assistant : %d passage(s) écarté(s) : %s", len(dropped), dropped[:3])
    if not clean:
        return {"status": "error", "message": "La réponse de l'IA n'a pas passé les contrôles de fiabilité, "
                                              "reformulez la question.", "retryable": True}
    refs = references(clean, box)
    return {"status": "ok", "answer": clean, "combos": refs["combos"], "matches": refs["matches"],
            "provider": prov.label, "model": prov.model, "removed": len(dropped),
            "remaining_today": max(0, daily - _member_usage(db, who))}
