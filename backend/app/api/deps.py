"""Dépendances communes : session DB et contrôle d'accès administrateur."""
from __future__ import annotations

import hmac
from typing import Optional

from fastapi import Header, HTTPException

from ..config import get_settings
from ..db import get_db  # noqa: F401  (ré-export)


def require_admin(x_admin_token: Optional[str] = Header(default=None)) -> None:
    expected = get_settings().admin_api_token
    if not expected:
        raise HTTPException(503, "Administration désactivée : définissez ADMIN_API_TOKEN côté serveur")
    if not x_admin_token or not hmac.compare_digest(x_admin_token, expected):
        raise HTTPException(401, "Accès administrateur refusé")


def require_cron(x_cron_secret: Optional[str] = Header(default=None)) -> None:
    expected = get_settings().cron_secret
    if not expected:
        raise HTTPException(503, "Déclenchement externe désactivé : définissez CRON_SECRET")
    if not x_cron_secret or not hmac.compare_digest(x_cron_secret, expected):
        raise HTTPException(401, "Secret invalide")
