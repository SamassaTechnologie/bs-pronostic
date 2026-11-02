"""Réglages d'utilisation de l'IA, modifiables dans l'administration (stockés en base, réglage « ai »).

* analyses : « auto » (préparées à l'avance + rédigées à la demande), « preparees » (seulement celles préparées
  à l'avance pour la Sélection SAM et les pronostics à cote ; aucune rédaction déclenchée par un membre), « off ».
* assistant : « tous » (tous les membres connectés), « liste » (seulement les adresses e-mail autorisées), « off ».
* plafonds : appels IA par jour (toutes fonctions), questions par membre et par jour, analyses préparées par
  synchronisation, étapes de recherche par question.
"""
from __future__ import annotations

import re
from typing import Optional

from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import Setting

KEY = "ai"
MODES_ANALYSES = ("auto", "preparees", "off")
MODES_ASSISTANT = ("tous", "liste", "off")
BOUNDS = {
    "daily_budget": (0, 2000),
    "member_daily": (0, 100),
    "pregenerate_limit": (0, 40),
    "max_steps": (1, 6),
}
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def defaults() -> dict:
    s = get_settings()
    return {"analyses": "auto", "assistant": "tous", "daily_budget": s.ai_daily_budget,
            "member_daily": s.assistant_member_daily, "pregenerate_limit": 12,
            "max_steps": s.assistant_max_steps, "allowed_emails": []}


def get_ai_settings(db: Session) -> dict:
    out = defaults()
    row = db.get(Setting, KEY)
    if row and isinstance(row.value, dict):
        out.update({k: v for k, v in row.value.items() if k in out})
    return out


def update_ai_settings(db: Session, changes: dict) -> dict:
    cur = get_ai_settings(db)
    for k, v in changes.items():
        if k not in cur:
            raise ValueError(f"Réglage inconnu : {k}")
        if k == "analyses":
            if v not in MODES_ANALYSES:
                raise ValueError("Mode d'analyse IA invalide")
        elif k == "assistant":
            if v not in MODES_ASSISTANT:
                raise ValueError("Mode de l'assistant invalide")
        elif k == "allowed_emails":
            items = v if isinstance(v, list) else re.split(r"[\s,;]+", str(v or ""))
            emails = sorted({e.strip().lower() for e in items if e and e.strip()})
            bad = [e for e in emails if not EMAIL_RE.match(e)]
            if bad:
                raise ValueError(f"Adresse e-mail invalide : {bad[0]}")
            v = emails[:500]
        else:
            lo, hi = BOUNDS[k]
            try:
                v = int(v)
            except (TypeError, ValueError):
                raise ValueError(f"Valeur numérique attendue pour {k}")
            if not lo <= v <= hi:
                raise ValueError(f"{k} doit être compris entre {lo} et {hi}")
        cur[k] = v
    row = db.get(Setting, KEY)
    if row is None:
        db.add(Setting(key=KEY, value=cur))
    else:
        row.value = dict(cur)
    db.commit()
    return cur


def member_allowed(cfg: dict, email: Optional[str]) -> bool:
    if cfg["assistant"] == "off":
        return False
    if cfg["assistant"] == "tous":
        return True
    return bool(email) and email.strip().lower() in set(cfg.get("allowed_emails") or [])


def public_flags(db: Session) -> dict:
    cfg = get_ai_settings(db)
    return {"analyses": cfg["analyses"] != "off", "assistant": cfg["assistant"] != "off",
            "assistant_restricted": cfg["assistant"] == "liste"}
