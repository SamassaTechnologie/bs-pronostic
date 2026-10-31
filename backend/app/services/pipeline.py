"""Chaîne complète (synchronisation → analyse → règlement) et recalibrage par backtest."""
from __future__ import annotations

import logging
import threading
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..engine.backtest import (fit_calibrators, market_metrics, reliability_from_metrics, tier_report,
                               walk_forward)
from ..engine.calibration import CALIBRATED_KEYS, calibrators_to_dict
from ..engine.predictor import EngineParams
from ..models import Calibration, Competition, Match, SyncRun, utcnow
from .analysis import match_to_data, run_analysis
from .performance import settle_predictions
from .settings_service import get_selection_settings
from .sync import run_sync

log = logging.getLogger("sam.pipeline")
UTC = timezone.utc
_lock = threading.Lock()
_state = {"running": False, "step": None, "started_at": None, "last_result": None}


def pipeline_state() -> dict:
    return dict(_state)


def run_pipeline(db: Session, kinds=("history", "upcoming", "enrich"), force: bool = False) -> dict:
    if not _lock.acquire(blocking=False):
        return {"status": "busy", "message": "Une synchronisation est déjà en cours"}
    try:
        _state.update(running=True, started_at=utcnow().isoformat(), step="synchronisation")
        sync = run_sync(db, kinds, force=force)
        _state["step"] = "scores du jour"
        from .live import refresh_scores
        scores = refresh_scores(db)
        sync.append({"provider": "football_data_org", "kind": "scores", "status": "ok" if scores.get("ok") else "error",
                     "items": scores.get("updated", 0), "message": scores.get("error") or
                     f"{scores.get('updated', 0)} résultat(s) final(aux) enregistré(s)"})
        _state["step"] = "analyse"
        analysis = run_analysis(db)
        _state["step"] = "règlement"
        settled = settle_predictions(db)
        result = {"status": "ok", "sync": sync, "analysis": analysis, "settled": settled,
                  "finished_at": utcnow().isoformat()}
        _state["last_result"] = result
        return result
    except Exception as exc:
        log.exception("Échec de la chaîne de traitement")
        _state["last_result"] = {"status": "error", "message": str(exc)}
        return {"status": "error", "message": str(exc)}
    finally:
        _state.update(running=False, step=None)
        _lock.release()


def run_analysis_only(db: Session) -> dict:
    """Relance l'analyse seule (sans synchronisation), avec le même verrou que la chaîne complète."""
    if not _lock.acquire(blocking=False):
        return {"status": "busy", "message": "Une synchronisation ou une analyse est déjà en cours"}
    try:
        _state.update(running=True, started_at=utcnow().isoformat(), step="analyse")
        res = run_analysis(db)
        settled = settle_predictions(db)
        _state["last_result"] = {"status": "ok", "analysis": res, "settled": settled, "finished_at": utcnow().isoformat()}
        return _state["last_result"]
    except Exception as exc:
        log.exception("Échec de l'analyse")
        _state["last_result"] = {"status": "error", "message": str(exc), "finished_at": utcnow().isoformat()}
        return _state["last_result"]
    finally:
        _state.update(running=False, step=None)
        _lock.release()


def recalibrate(db: Session, months: int = 12, min_n: int = 300) -> dict:
    """Backtest chronologique sur les données en base, puis nouvelle calibration (si assez de données)."""
    now = utcnow()
    params = EngineParams()
    start = now - timedelta(days=30 * months)
    split = start + (now - start) / 2
    since = start - timedelta(days=params.window_days + 10)
    comps = db.scalars(select(Competition).where(Competition.enabled.is_(True))).all()
    run = SyncRun(provider="moteur", kind="calibration", status="running")
    db.add(run)
    db.commit()
    by_comp = defaultdict(list)
    for c in comps:
        rows = db.scalars(select(Match).where(Match.competition_id == c.id, Match.status == "FINISHED",
                                              Match.kickoff >= since)).unique().all()
        if rows:
            by_comp[c.id] = [match_to_data(r) for r in rows]
    rec = walk_forward(by_comp, start, now, params)
    first, second = rec.split(split)
    cals_first = fit_calibrators(first, min_n=min_n)
    oos = market_metrics(second, CALIBRATED_KEYS, cals_first)
    cals_all = fit_calibrators(rec, min_n=min_n)
    run.finished_at = utcnow()
    if not cals_all:
        run.status = "skipped"
        run.message = f"Données insuffisantes pour recalibrer ({len(rec)} matchs rejoués, minimum {min_n})"
        db.commit()
        return {"status": "skipped", "message": run.message}
    payload = {
        "description": "Calibration de Platt par marché, ajustée par backtest chronologique sur la base.",
        "source": "Données synchronisées dans SAM-Prédiction",
        "generated_at": now.isoformat(timespec="seconds"), "n_matches": len(rec),
        "period": {"start": start.date().isoformat(), "split": split.date().isoformat(), "end": now.date().isoformat()},
        "calibrators": calibrators_to_dict(cals_all),
        "out_of_sample": {"calibrated": oos,
                          "tiers": tier_report(second, cals_first, CALIBRATED_KEYS, get_selection_settings(db))},
        "reliability": reliability_from_metrics(oos),
    }
    db.execute(update(Calibration).values(active=False))
    db.add(Calibration(method="platt", n_matches=len(rec), active=True, payload=payload))
    run.status = "ok"
    run.items = len(rec)
    run.message = f"Calibration mise à jour ({len(rec)} matchs rejoués, {len(cals_all)} marchés calibrés)"
    db.commit()
    return {"status": "ok", "message": run.message, "out_of_sample": oos}
