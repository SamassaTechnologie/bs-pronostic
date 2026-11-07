"""Alertes Web Push (gratuites, sans service tiers) : banker du jour, Sélection SAM, combinés, résultats du banker.

* Chaque alerte n'est envoyée qu'une fois par appareil (table push_log).
* Aucune alerte la nuit (fuseau par défaut, 23 h – 7 h) : elles partent au réveil.
* Les championnats favoris du membre filtrent la Sélection et les combinés ; le banker est envoyé à tous ceux qui l'ont
  demandé.
* Un appareil désinstallé (réponse 404/410) est supprimé ; après 5 échecs consécutifs aussi.
"""
from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import Match, Prediction, PushLog, PushSubscription, utcnow

log = logging.getLogger("sam.push")
UTC = timezone.utc
DEFAULT_PREFS = {"banker": True, "selection": True, "combo": False, "results": True, "competitions": []}
_lock = threading.Lock()


def enabled() -> bool:
    cfg = get_settings()
    return bool(cfg.vapid_public_key and cfg.vapid_private_key)


def prefs_of(sub: PushSubscription) -> dict:
    p = dict(DEFAULT_PREFS)
    p.update({k: v for k, v in (sub.prefs or {}).items() if k in DEFAULT_PREFS})
    return p


def clean_prefs(raw: dict) -> dict:
    p = dict(DEFAULT_PREFS)
    for k in ("banker", "selection", "combo", "results"):
        if k in raw:
            p[k] = bool(raw[k])
    comps = raw.get("competitions") or []
    p["competitions"] = [str(c)[:12] for c in comps if isinstance(c, str)][:20]
    return p


def _quiet(now: datetime) -> bool:
    cfg = get_settings()
    h = now.astimezone(ZoneInfo(cfg.default_timezone)).hour
    s, e = cfg.push_quiet_start, cfg.push_quiet_end
    return h >= s or h < e if s > e else s <= h < e


def send(sub: PushSubscription, payload: dict) -> bool:
    """Envoie une alerte ; retourne False (et compte l'échec) si l'appareil la refuse."""
    from pywebpush import WebPushException, webpush
    cfg = get_settings()
    try:
        webpush(subscription_info={"endpoint": sub.endpoint, "keys": {"p256dh": sub.p256dh, "auth": sub.auth}},
                data=json.dumps(payload, ensure_ascii=False), vapid_private_key=cfg.vapid_private_key,
                vapid_claims={"sub": cfg.vapid_subject}, ttl=6 * 3600, timeout=10)
        sub.failures, sub.last_success_at = 0, utcnow()
        return True
    except WebPushException as exc:
        code = getattr(exc.response, "status_code", None)
        sub.failures = 99 if code in (404, 410) else (sub.failures or 0) + 1
        log.info("Alerte refusée (%s) pour l'abonnement %s", code, sub.id)
    except Exception as exc:  # réseau
        sub.failures = (sub.failures or 0) + 1
        log.info("Alerte non envoyée (%s) pour l'abonnement %s", exc.__class__.__name__, sub.id)
    return False


def _match_txt(m: Match) -> str:
    return f"{m.home_team.name} – {m.away_team.name}"


def _kick(m: Match) -> str:
    return m.kickoff.astimezone(ZoneInfo(get_settings().default_timezone)).strftime("%H:%M")


def _already(db: Session, sub_id: int, kind: str, refs: list[str]) -> set[str]:
    if not refs:
        return set()
    return set(db.scalars(select(PushLog.ref).where(PushLog.subscription_id == sub_id, PushLog.kind == kind,
                                                    PushLog.ref.in_(refs))))


def _mark(db: Session, sub_id: int, kind: str, refs: list[str]) -> None:
    for r in refs:
        db.add(PushLog(subscription_id=sub_id, kind=kind, ref=r))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()


def build_messages(db: Session, sub: PushSubscription, now: datetime) -> list[tuple[str, list[str], dict]]:
    """Messages à envoyer à cet appareil : (type, références, contenu). Rien d'inventé : uniquement des pronostics
    publiés et des résultats réglés."""
    p = prefs_of(sub)
    favs = set(p["competitions"])
    out = []
    upcoming = select(Prediction).join(Match, Prediction.match_id == Match.id).where(
        Prediction.result == "pending", Match.kickoff > now + timedelta(minutes=15), Match.kickoff < now + timedelta(hours=36))

    if p["banker"]:
        for pr in db.scalars(upcoming.where(Prediction.banker.is_(True))).unique():
            ref = str(pr.id)
            if ref in _already(db, sub.id, "banker", [ref]):
                continue
            m = pr.match
            out.append(("banker", [ref], {
                "title": "⭐ Le banker du jour",
                "body": f"{_match_txt(m)} ({_kick(m)}) : {pr.market_label}, {round(pr.probability * 100)} %",
                "url": f"/matchs/{m.id}", "tag": f"banker-{pr.id}"}))

    for kind, col, title in (("selection", Prediction.featured, "Sélection SAM"),
                             ("combo", Prediction.combo_pick, "Pronostics combinés")):
        if not p[kind]:
            continue
        preds = [pr for pr in db.scalars(upcoming.where(col.is_(True))).unique()
                 if not favs or pr.match.competition.code in favs]
        refs = [str(pr.id) for pr in preds]
        done = _already(db, sub.id, kind, refs)
        new = [pr for pr in preds if str(pr.id) not in done]
        if not new:
            continue
        new.sort(key=lambda pr: pr.match.kickoff)
        first = new[0]
        more = f" et {len(new) - 1} autre{'s' if len(new) > 2 else ''}" if len(new) > 1 else ""
        out.append((kind, [str(pr.id) for pr in new], {
            "title": f"{title} : {len(new)} nouveau{'x' if len(new) > 1 else ''} pronostic{'s' if len(new) > 1 else ''}",
            "body": f"{_match_txt(first.match)} ({_kick(first.match)}) : {first.market_label}{more}",
            "url": "/#pronostics", "tag": kind}))

    if p["results"]:
        settled = db.scalars(select(Prediction).join(Match, Prediction.match_id == Match.id).where(
            Prediction.banker.is_(True), Prediction.result.in_(["won", "lost"]),
            Prediction.settled_at >= now - timedelta(hours=24))).unique().all()
        for pr in settled:
            ref = str(pr.id)
            if ref in _already(db, sub.id, "result", [ref]):
                continue
            m = pr.match
            won = pr.result == "won"
            out.append(("result", [ref], {
                "title": "✅ Banker gagné" if won else "❌ Banker perdu",
                "body": f"{_match_txt(m)} {m.home_goals}-{m.away_goals} : {pr.market_label}",
                "url": "/bilan", "tag": f"result-{pr.id}"}))
    return out


def dispatch(db: Session, now: Optional[datetime] = None) -> dict:
    """Envoie les alertes en attente à tous les appareils abonnés."""
    now = now or utcnow()
    if not enabled():
        return {"sent": 0, "skipped": "clés VAPID absentes"}
    if _quiet(now):
        return {"sent": 0, "skipped": "nuit"}
    sent = removed = 0
    for sub in db.scalars(select(PushSubscription)).all():
        for kind, refs, payload in build_messages(db, sub, now):
            if send(sub, payload):
                sent += 1
                _mark(db, sub.id, kind, refs)
            if sub.failures >= 5:
                break
        if sub.failures >= 5:
            db.delete(sub)
            removed += 1
        db.commit()
    return {"sent": sent, "removed": removed}


def dispatch_async() -> None:
    """Déclenché après chaque règlement / analyse ; ne bloque jamais la requête en cours."""
    if not enabled() or not _lock.acquire(blocking=False):
        return

    def run():
        from ..db import SessionLocal
        try:
            with SessionLocal() as db:
                res = dispatch(db)
                if res.get("sent"):
                    log.info("Alertes envoyées : %s", res)
        except Exception:
            log.exception("Échec de l'envoi des alertes")
        finally:
            _lock.release()

    threading.Thread(target=run, daemon=True).start()
