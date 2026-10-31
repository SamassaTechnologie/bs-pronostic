"""API d'administration (jeton X-Admin-Token) et déclenchement externe (X-Cron-Secret)."""
from __future__ import annotations

import threading
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import SessionLocal
from ..models import Analysis, Calibration, Competition, Match, Prediction, SyncRun, Team
from ..providers.registry import PROVIDERS, make_provider, provider_status
from ..services.analysis import run_analysis
from ..services.performance import settle_predictions
from ..services.pipeline import pipeline_state, recalibrate, run_analysis_only, run_pipeline
from ..services.settings_service import (get_selection_settings, set_provider_flag, update_selection_settings)
from .deps import get_db, require_admin, require_cron

router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_admin)])
cron_router = APIRouter(prefix="/api/cron", tags=["cron"], dependencies=[Depends(require_cron)])


def _in_background(fn, *args, **kwargs) -> None:
    def runner():
        db = SessionLocal()
        try:
            fn(db, *args, **kwargs)
        finally:
            db.close()

    threading.Thread(target=runner, daemon=True).start()


@router.get("/status")
def status(db: Session = Depends(get_db)):
    cfg = get_settings()
    counts = {
        "competitions_enabled": db.scalar(select(func.count(Competition.id)).where(Competition.enabled.is_(True))),
        "teams": db.scalar(select(func.count(Team.id))),
        "matches": db.scalar(select(func.count(Match.id))),
        "matches_finished": db.scalar(select(func.count(Match.id)).where(Match.status == "FINISHED")),
        "matches_scheduled": db.scalar(select(func.count(Match.id)).where(Match.status == "SCHEDULED")),
        "analyses": db.scalar(select(func.count(Analysis.id))),
        "predictions": db.scalar(select(func.count(Prediction.id))),
    }
    cal = db.scalar(select(Calibration).where(Calibration.active.is_(True)).order_by(Calibration.created_at.desc()))
    return {
        "providers": provider_status(db), "counts": counts, "pipeline": pipeline_state(),
        "scheduler": {"enabled": cfg.enable_scheduler, "interval_minutes": cfg.sync_interval_minutes},
        "calibration": ({"created_at": cal.created_at.isoformat(), "n_matches": cal.n_matches} if cal
                        else {"created_at": None, "note": "Calibration par défaut (backtest livré avec l'application)"}),
        "database": "postgresql" if "postgres" in cfg.database_url else "sqlite",
    }


@router.post("/providers/{name}/test")
def test_provider(name: str):
    if name not in PROVIDERS:
        raise HTTPException(404, "Fournisseur inconnu")
    p = make_provider(name)
    if p.requires_key and not p.is_configured():
        return {"ok": False, "message": "Clé API non configurée côté serveur"}
    return p.test_connection()


class ProviderToggle(BaseModel):
    enabled: bool


@router.put("/providers/{name}")
def toggle_provider(name: str, body: ProviderToggle, db: Session = Depends(get_db)):
    try:
        return set_provider_flag(db, name, body.enabled)
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.get("/settings")
def get_settings_endpoint(db: Session = Depends(get_db)):
    return get_selection_settings(db)


@router.put("/settings")
def put_settings(changes: dict, db: Session = Depends(get_db)):
    try:
        return update_selection_settings(db, changes)
    except ValueError as exc:
        raise HTTPException(400, str(exc))


def _comp_row(c: Competition, n_matches: int = 0) -> dict:
    return {"id": c.id, "code": c.code, "name": c.name, "country": c.country, "enabled": c.enabled,
            "primary_source": c.primary_source, "fdcuk_code": c.fdcuk_code, "fdcuk_extra": c.fdcuk_extra,
            "api_football_id": c.api_football_id, "fdorg_code": c.fdorg_code, "calendar_year": c.calendar_year,
            "matches": n_matches}


@router.get("/competitions")
def list_competitions(db: Session = Depends(get_db)):
    counts = dict(db.execute(select(Match.competition_id, func.count(Match.id)).group_by(Match.competition_id)).all())
    comps = db.scalars(select(Competition).order_by(Competition.enabled.desc(), Competition.country,
                                                    Competition.name)).all()
    return [_comp_row(c, counts.get(c.id, 0)) for c in comps]


class CompetitionUpdate(BaseModel):
    enabled: Optional[bool] = None
    primary_source: Optional[str] = Field(None, pattern="^(football_data_co_uk|api_football|football_data_org)$")
    api_football_id: Optional[int] = None
    fdorg_code: Optional[str] = None
    fdcuk_code: Optional[str] = None
    calendar_year: Optional[bool] = None


@router.put("/competitions/{comp_id}")
def update_competition(comp_id: int, body: CompetitionUpdate, db: Session = Depends(get_db)):
    c = db.get(Competition, comp_id)
    if c is None:
        raise HTTPException(404, "Compétition introuvable")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(c, k, v)
    if c.primary_source == "football_data_co_uk" and not c.fdcuk_code:
        raise HTTPException(400, "Code football-data.co.uk requis pour cette source")
    if c.primary_source == "api_football" and not c.api_football_id:
        raise HTTPException(400, "Identifiant de ligue API-Football requis pour cette source")
    if c.primary_source == "football_data_org" and not c.fdorg_code:
        raise HTTPException(400, "Code football-data.org requis pour cette source")
    db.commit()
    return _comp_row(c)


class CompetitionCreate(BaseModel):
    code: str = Field(min_length=2, max_length=32)
    name: str = Field(min_length=2, max_length=120)
    country: str = Field(min_length=2, max_length=80)
    api_football_id: int
    calendar_year: bool = False
    enabled: bool = True


@router.post("/competitions")
def create_competition(body: CompetitionCreate, db: Session = Depends(get_db)):
    if db.scalar(select(Competition).where(Competition.code == body.code)):
        raise HTTPException(409, "Ce code existe déjà")
    c = Competition(code=body.code, name=body.name, country=body.country, enabled=body.enabled,
                    api_football_id=body.api_football_id, calendar_year=body.calendar_year,
                    primary_source="api_football")
    db.add(c)
    db.commit()
    return _comp_row(c)


class SyncRequest(BaseModel):
    kinds: list[str] = Field(default_factory=lambda: ["history", "upcoming", "enrich"])
    force: bool = False


@router.post("/sync")
def trigger_sync(body: SyncRequest):
    if pipeline_state()["running"]:
        return {"status": "busy", "message": "Une synchronisation est déjà en cours"}
    kinds = [k for k in body.kinds if k in ("history", "upcoming", "enrich")] or ["history", "upcoming", "enrich"]
    _in_background(run_pipeline, kinds, body.force)
    return {"status": "started", "message": "Synchronisation lancée (suivez l'avancement dans le journal)"}


@router.get("/pipeline")
def get_pipeline():
    return pipeline_state()


@router.post("/analyze")
def trigger_analysis():
    if pipeline_state()["running"]:
        return {"status": "busy", "message": "Une synchronisation est en cours : l'analyse sera faite à la fin automatiquement"}
    _in_background(run_analysis_only)
    return {"status": "started", "message": "Analyse lancée : les pronostics seront à jour d'ici une à deux minutes"}


@router.post("/settle")
def trigger_settle(db: Session = Depends(get_db)):
    return settle_predictions(db)


@router.post("/calibrate")
def trigger_calibration():
    _in_background(recalibrate)
    return {"status": "started", "message": "Recalibrage lancé : backtest sur les 12 derniers mois en base"}


@router.get("/sync-runs")
def sync_runs(limit: int = 40, db: Session = Depends(get_db)):
    rows = db.scalars(select(SyncRun).order_by(SyncRun.started_at.desc()).limit(min(limit, 200))).all()
    return [{"id": r.id, "provider": r.provider, "kind": r.kind, "status": r.status, "items": r.items,
             "message": r.message, "started_at": r.started_at.isoformat(),
             "finished_at": r.finished_at.isoformat() if r.finished_at else None} for r in rows]


@cron_router.post("/run")
def cron_run():
    if pipeline_state()["running"]:
        return {"status": "busy"}
    _in_background(run_pipeline)
    return {"status": "started"}
