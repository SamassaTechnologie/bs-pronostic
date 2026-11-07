"""Alertes (Web Push) : abonnement d'un appareil et préférences. Réservé à l'application (secret partagé + identifiant
membre transmis par le serveur Next.js)."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import PushSubscription
from ..services import push
from .deps import get_db
from .game import member

router = APIRouter(prefix="/api/alertes", tags=["alertes"])


class Keys(BaseModel):
    p256dh: str = Field(max_length=200)
    auth: str = Field(max_length=100)


class Sub(BaseModel):
    endpoint: str = Field(max_length=1000)
    keys: Keys


class SubscribeIn(BaseModel):
    subscription: Sub
    prefs: dict = {}


class EndpointIn(BaseModel):
    endpoint: str = Field(max_length=1000)
    prefs: Optional[dict] = None


def _mine(db: Session, endpoint: str, member_id: str) -> PushSubscription:
    sub = db.scalar(select(PushSubscription).where(PushSubscription.endpoint == endpoint))
    if sub is None or sub.member_id != member_id:
        raise HTTPException(404, "Cet appareil n'est pas abonné aux alertes")
    return sub


@router.get("/cle")
def key():
    return {"enabled": push.enabled(), "public_key": get_settings().vapid_public_key or None}


@router.post("/abonnement")
def subscribe(body: SubscribeIn, who=Depends(member), db: Session = Depends(get_db)):
    if not push.enabled():
        raise HTTPException(503, "Les alertes ne sont pas encore configurées sur le serveur")
    if not body.subscription.endpoint.startswith("https://"):
        raise HTTPException(422, "Abonnement invalide")
    sub = db.scalar(select(PushSubscription).where(PushSubscription.endpoint == body.subscription.endpoint))
    if sub is None:
        sub = PushSubscription(endpoint=body.subscription.endpoint)
        db.add(sub)
    sub.member_id = who[0]
    sub.p256dh, sub.auth = body.subscription.keys.p256dh, body.subscription.keys.auth
    sub.prefs, sub.failures = push.clean_prefs(body.prefs), 0
    db.commit()
    return {"ok": True, "prefs": push.prefs_of(sub)}


@router.post("/etat")
def state(body: EndpointIn, who=Depends(member), db: Session = Depends(get_db)):
    sub = db.scalar(select(PushSubscription).where(PushSubscription.endpoint == body.endpoint))
    if sub is None or sub.member_id != who[0]:
        return {"subscribed": False, "prefs": dict(push.DEFAULT_PREFS)}
    return {"subscribed": True, "prefs": push.prefs_of(sub)}


@router.post("/preferences")
def preferences(body: EndpointIn, who=Depends(member), db: Session = Depends(get_db)):
    sub = _mine(db, body.endpoint, who[0])
    sub.prefs = push.clean_prefs(body.prefs or {})
    db.commit()
    return {"ok": True, "prefs": push.prefs_of(sub)}


@router.post("/desabonnement")
def unsubscribe(body: EndpointIn, who=Depends(member), db: Session = Depends(get_db)):
    sub = db.scalar(select(PushSubscription).where(PushSubscription.endpoint == body.endpoint))
    if sub is not None and sub.member_id == who[0]:
        db.delete(sub)
        db.commit()
    return {"ok": True}


@router.post("/test")
def test(body: EndpointIn, who=Depends(member), db: Session = Depends(get_db)):
    sub = _mine(db, body.endpoint, who[0])
    ok = push.send(sub, {"title": "SAM-Prédiction", "body": "Les alertes fonctionnent sur cet appareil.",
                         "url": "/compte/alertes", "tag": "test"})
    db.commit()
    if not ok:
        raise HTTPException(502, "L'appareil n'a pas accepté l'alerte ; réactivez les notifications puis réessayez")
    return {"ok": True}
