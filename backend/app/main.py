"""Point d'entrée FastAPI de SAM-Prédiction."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from .api.admin import cron_router
from .api.admin import router as admin_router
from .api.public import router as public_router
from .api.catalog import router as catalog_router
from .config import get_settings
from .db import Base, SessionLocal, engine
from .seed import seed_reference_data

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s : %(message)s")
log = logging.getLogger("sam")
_scheduler = None


# Colonnes ajoutées après la première mise en production : (table, colonne, type SQL).
ADDED_COLUMNS = [
    ("predictions", "featured", "BOOLEAN NOT NULL DEFAULT FALSE"),
    ("predictions", "featured_at", "TIMESTAMP WITH TIME ZONE"),
]


def migrate_columns() -> None:
    """Ajoute les colonnes manquantes sans toucher aux données existantes (idempotent)."""
    from sqlalchemy import inspect, text

    insp = inspect(engine)
    with engine.begin() as conn:
        for table, column, ddl in ADDED_COLUMNS:
            if table in insp.get_table_names() and column not in {c["name"] for c in insp.get_columns(table)}:
                if engine.dialect.name == "sqlite":
                    ddl = ddl.replace("TIMESTAMP WITH TIME ZONE", "DATETIME").replace("FALSE", "0")
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
                log.info("Migration : colonne %s.%s ajoutée", table, column)


def init_db() -> None:
    from . import models  # noqa: F401  (enregistre les tables)

    Base.metadata.create_all(engine)
    migrate_columns()
    # Les synchronisations interrompues par un redémarrage restent sinon « en cours » indéfiniment.
    from sqlalchemy import update
    from .models import SyncRun, utcnow
    with engine.begin() as conn:
        conn.execute(update(SyncRun).where(SyncRun.status == "running").values(
            status="error", message="Interrompue par un redémarrage du serveur", finished_at=utcnow()))
    with SessionLocal() as db:
        seed_reference_data(db)


def _scheduled_pipeline() -> None:
    from .services.pipeline import run_pipeline
    from .services.sync import last_successful_sync

    with SessionLocal() as db:
        last = last_successful_sync(db)
        # Après un redémarrage (déploiement), inutile de tout resynchroniser si c'est récent :
        # cela consommerait le quota quotidien des API pour rien.
        if last is not None and datetime.now(timezone.utc) - last < timedelta(minutes=get_settings().sync_interval_minutes - 15):
            log.info("Synchronisation récente (%s) : passage ignoré", last.isoformat())
            return
        res = run_pipeline(db)
        log.info("Synchronisation planifiée : %s", res.get("status"))


def start_scheduler() -> None:
    global _scheduler
    from apscheduler.schedulers.background import BackgroundScheduler

    cfg = get_settings()
    _scheduler = BackgroundScheduler(timezone="UTC")
    _scheduler.add_job(_scheduled_pipeline, "interval", minutes=cfg.sync_interval_minutes, id="pipeline",
                       next_run_time=datetime.now(timezone.utc) + timedelta(seconds=45),
                       max_instances=1, coalesce=True)
    _scheduler.start()
    log.info("Planificateur actif : synchronisation toutes les %s minutes", cfg.sync_interval_minutes)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    if get_settings().enable_scheduler:
        start_scheduler()
    yield
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)


def create_app() -> FastAPI:
    cfg = get_settings()
    app = FastAPI(title="SAM-Prédiction API", description=cfg.slogan, version="1.0.0", lifespan=lifespan)
    app.add_middleware(GZipMiddleware, minimum_size=1000)
    app.add_middleware(CORSMiddleware, allow_origins=[o.strip() for o in cfg.cors_origins.split(",") if o.strip()],
                       allow_methods=["GET", "POST", "PUT"], allow_headers=["*"])
    app.include_router(public_router)
    app.include_router(catalog_router)
    app.include_router(admin_router)
    app.include_router(cron_router)

    @app.get("/")
    def root():
        return {"app": cfg.app_name, "slogan": cfg.slogan, "docs": "/docs", "health": "/api/health"}

    return app


app = create_app()
