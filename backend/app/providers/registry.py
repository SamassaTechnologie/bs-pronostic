"""Registre des fournisseurs et état (configuré, activé, dernière synchronisation)."""
from __future__ import annotations

from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import ApiUsage, SyncRun
from .api_football import ApiFootball
from .base import Provider
from .football_data_co_uk import FootballDataCoUk
from .football_data_org import FootballDataOrg

PROVIDERS: dict[str, type[Provider]] = {
    "football_data_co_uk": FootballDataCoUk,
    "api_football": ApiFootball,
    "football_data_org": FootballDataOrg,
}

SETUP_HELP = {
    "football_data_co_uk": "Aucune clé nécessaire. Données gratuites (résultats, corners, cartons, cotes 1X2 et +/-2,5).",
    "api_football": "Créez un compte sur dashboard.api-football.com, copiez la clé (Account → My Access) dans "
                    "API_FOOTBALL_KEY côté serveur.",
    "football_data_org": "Inscrivez-vous sur football-data.org/client/register : la clé arrive par e-mail ; "
                         "renseignez FOOTBALL_DATA_ORG_KEY côté serveur.",
}


def make_provider(name: str) -> Provider:
    return PROVIDERS[name]()


def provider_status(db: Session) -> list[dict]:
    from ..services.settings_service import get_provider_flags

    flags = get_provider_flags(db)
    out = []
    for name, cls in PROVIDERS.items():
        p = cls()
        last = db.scalar(select(SyncRun).where(SyncRun.provider == name).order_by(SyncRun.started_at.desc()))
        last_ok = db.scalar(select(func.max(SyncRun.finished_at)).where(SyncRun.provider == name,
                                                                        SyncRun.status == "ok"))
        usage = db.get(ApiUsage, (name, date.today().isoformat()))
        out.append({
            "name": name, "label": p.label, "website": p.website, "requires_key": p.requires_key,
            "configured": p.is_configured(), "enabled": flags.get(name, True),
            "capabilities": list(p.capabilities), "setup": SETUP_HELP[name],
            "last_run": ({"kind": last.kind, "status": last.status, "message": last.message,
                          "started_at": last.started_at.isoformat(),
                          "finished_at": last.finished_at.isoformat() if last.finished_at else None}
                         if last else None),
            "last_ok": last_ok.isoformat() if last_ok else None,
            "requests_today": usage.requests if usage else 0,
        })
    return out
