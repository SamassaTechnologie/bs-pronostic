"""Test de bout en bout sur une saison RÉELLE (Premier League 2025-2026) :
import → analyse → publication → résultats → règlement → statistiques → API.

Seul le transport HTTP est remplacé : les fichiers servis sont les vrais résultats
au format football-data.co.uk ; le calendrier « à venir » correspond aux vrais
matchs de la journée suivante, présentés sans score comme dans fixtures.csv.
"""
import csv
import io
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.db import SessionLocal
from app.engine.markets import DISPLAY_KEYS
from app.main import app, init_db
from app.models import Analysis, Competition, Match, OddsQuote, Prediction, SyncRun
from app.providers.base import ProviderError
from app.providers.football_data_co_uk import FootballDataCoUk, parse_kickoff
from app.services.analysis import run_analysis
from app.services.performance import performance, settle_predictions
from app.services.sync import run_sync

UTC = timezone.utc
NOW = datetime(2026, 2, 27, 12, 0, tzinfo=UTC)
ADMIN = {"X-Admin-Token": "jeton-admin-test"}
RESULT_COLS = ("FTHG", "FTAG", "FTR", "HTHG", "HTAG", "HTR", "HS", "AS", "HST", "AST", "HF", "AF", "HC", "AC",
               "HY", "AY", "HR", "AR")


def _csv(header, rows) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=header)
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue()


@pytest.fixture(scope="module")
def season(e0_csv):
    rows = list(csv.DictReader(io.StringIO(e0_csv)))
    header = list(rows[0].keys())
    ko = lambda r: parse_kickoff(r["Date"], r["Time"])  # noqa: E731
    before = [r for r in rows if ko(r) < NOW]
    upcoming = [r for r in rows if NOW <= ko(r) < NOW + timedelta(days=3)]
    assert len(before) > 200 and len(upcoming) >= 5
    fixtures = [{k: ("" if k in RESULT_COLS else v) for k, v in r.items()} for r in upcoming]
    return {"header": header, "before": before, "upcoming": upcoming, "fixtures": fixtures}


@pytest.fixture(scope="module")
def populated(season):
    init_db()
    with SessionLocal() as db:
        for c in db.scalars(select(Competition)).all():
            c.enabled = c.code == "ENG1"
        db.commit()
    state = {"results": season["before"], "fixtures": season["fixtures"]}

    def fake_get_text(self, path):
        if path == "/mmz4281/2526/E0.csv":
            return _csv(season["header"], state["results"])
        if path == "/fixtures.csv":
            return _csv(season["header"], state["fixtures"])
        if path.startswith("/mmz4281/"):
            raise ProviderError(f"football-data.co.uk : fichier introuvable ({path})")
        raise AssertionError(path)

    mp = pytest.MonkeyPatch()
    mp.setattr(FootballDataCoUk, "_get_text", fake_get_text)
    with SessionLocal() as db:
        sync1 = run_sync(db, kinds=("history", "upcoming"), now=NOW)
        analysis = run_analysis(db, now=NOW)
    # La journée se joue : les vrais résultats arrivent.
    state["results"] = season["before"] + season["upcoming"]
    state["fixtures"] = []
    later = NOW + timedelta(days=4)
    with SessionLocal() as db:
        sync2 = run_sync(db, kinds=("history", "upcoming"), now=later)
        settled = settle_predictions(db, now=later)
    yield {"sync1": sync1, "analysis": analysis, "sync2": sync2, "settled": settled, "mp": mp}
    mp.undo()


def test_import_and_analysis(populated, season):
    assert all(r["status"] == "ok" for r in populated["sync1"]), populated["sync1"]
    a = populated["analysis"]
    assert a["analysed"] == len(season["upcoming"]) and a["ok"] == a["analysed"]
    with SessionLocal() as db:
        assert db.scalar(select(func.count(OddsQuote.id))) > 0
        an = db.scalars(select(Analysis)).first()
        p = an.payload
        assert p["status"] == "ok" and len(p["markets"]) == len(DISPLAY_KEYS) and p["expected_goals"]["home"] > 0
        assert p["data_quality"]["corners_available"] and p["data_quality"]["cards_available"]
        one = next(m for m in p["markets"] if m["key"] == "1")
        assert one["odds"] and one["implied_probability"] and one["bookmaker"] == "Moyenne"
        assert not p["data_quality"]["injuries_available"]  # pas de clé API-Football : signalé, pas inventé


def test_results_settlement_and_performance(populated):
    with SessionLocal() as db:
        preds = db.scalars(select(Prediction)).all()
        assert preds, "au moins un pronostic doit être publié"
        assert all(p.result in ("won", "lost") for p in preds)
        perf = performance(db)
        o = perf["overall"]
        assert o["total"] == len(preds) and o["n"] == len(preds) and 0 <= o["hit_rate"] <= 1
        assert perf["calibration"]["brier"] is not None and perf["timeline"]
        ms = db.scalars(select(Match).where(Match.status == "FINISHED")).all()
        assert len(ms) >= 260


def test_history_is_immutable(populated):
    with SessionLocal() as db:
        p = db.scalars(select(Prediction)).first()
        p.probability = 0.99
        with pytest.raises(ValueError, match="immuable"):
            db.commit()
        db.rollback()


def test_provider_failure_keeps_data(populated, monkeypatch):
    def boom(self, path):
        raise ProviderError("football-data.co.uk : HTTP 503 sur " + path)

    monkeypatch.setattr(FootballDataCoUk, "_get_text", boom)
    with SessionLocal() as db:
        before = db.scalar(select(func.count(Match.id)))
        res = run_sync(db, kinds=("upcoming",), now=NOW + timedelta(days=5))
        assert res[0]["status"] == "error" and "503" in res[0]["message"]
        assert db.scalar(select(func.count(Match.id))) == before
        assert db.scalar(select(SyncRun).order_by(SyncRun.id.desc())).status == "error"


@pytest.fixture()
def client(populated, monkeypatch):
    import app.api.public as public

    monkeypatch.setattr(public, "_now", lambda: NOW)
    with TestClient(app) as c:
        yield c


def test_public_endpoints(client):
    assert client.get("/api/health").json()["database"] == "ok"
    meta = client.get("/api/meta").json()
    assert meta["app"]["name"] == "SAM-Prédiction" and meta["providers"]
    assert meta["calibration"]["tiers"]["A"]["n"] > 0
    dash = client.get("/api/dashboard", params={"tz": "Africa/Bamako"}).json()
    assert dash["stats"]["matches_analysed"] > 0
    assert len(dash["top5"]) <= 5 and len({c["match"]["id"] for c in dash["top5"]}) == len(dash["top5"])
    preds = client.get("/api/predictions", params={"all_markets": True, "min_prob": 0.7}).json()
    assert preds["count"] > 0 and all(c["probability"] >= 0.7 for c in preds["items"])
    best = client.get("/api/predictions", params={"best": True}).json()
    assert len({c["match"]["id"] for c in best["items"]}) == len(best["items"])
    team = preds["items"][0]["match"]["home"]["name"]
    filt = client.get("/api/predictions", params={"all_markets": True, "team": team}).json()
    assert all(team in (c["match"]["home"]["name"], c["match"]["away"]["name"]) for c in filt["items"])
    mid = preds["items"][0]["match"]["id"]
    detail = client.get(f"/api/matches/{mid}").json()
    assert detail["analysis"]["status"] == "ok" and detail["odds"]
    assert client.get("/api/matches/999999").status_code == 404
    hist = client.get("/api/history").json()
    assert hist["total"] >= 1 and hist["items"][0]["result"] in ("won", "lost")
    perf = client.get("/api/performance").json()
    assert perf["overall"]["n"] >= 1
    day = client.get("/api/matches", params={"day": NOW.date().isoformat()}).json()
    assert "items" in day


def test_combo_endpoints(client):
    gen = client.post("/api/combos/generate", json={"legs": 2, "mode": "prudent", "min_confidence": 0}).json()
    if gen["combos"]:
        c = gen["combos"][0]
        assert c["valid"] and len({leg["match_id"] for leg in c["legs"]}) == 2
    preds = client.get("/api/predictions", params={"all_markets": True}).json()["items"]
    mid = preds[0]["match"]["id"]
    same = client.post("/api/combos/evaluate", json={"selections": [
        {"match_id": mid, "market_key": "1X"}, {"match_id": mid, "market_key": "O1.5"}]}).json()
    assert same["valid"] and same["independent"] is False and same["total_odds"] is None
    corr = client.post("/api/combos/evaluate", json={"selections": [
        {"match_id": mid, "market_key": "1X"}, {"match_id": mid, "market_key": "C_O8.5"}]}).json()
    assert corr["valid"] is False


def test_admin_security_and_settings(client):
    assert client.get("/api/admin/status").status_code == 401
    assert client.get("/api/admin/status", headers={"X-Admin-Token": "mauvais"}).status_code == 401
    st = client.get("/api/admin/status", headers=ADMIN).json()
    assert st["counts"]["matches"] > 0
    bad = client.put("/api/admin/settings", headers=ADMIN, json={"tier_a": 0.7, "tier_b": 0.8})
    assert bad.status_code == 400
    ok = client.put("/api/admin/settings", headers=ADMIN, json={"min_confidence": 60}).json()
    assert ok["min_confidence"] == 60
    comps = client.get("/api/admin/competitions", headers=ADMIN).json()
    eng = next(c for c in comps if c["code"] == "ENG1")
    assert eng["matches"] > 0
    r = client.put(f"/api/admin/competitions/{eng['id']}", headers=ADMIN, json={"primary_source": "api_football",
                                                                                  "api_football_id": None})
    assert r.status_code == 400
    test = client.post("/api/admin/providers/api_football/test", headers=ADMIN).json()
    assert test["ok"] is False and "non configurée" in test["message"]
    assert client.post("/api/cron/run").status_code == 401
    runs = client.get("/api/admin/sync-runs", headers=ADMIN).json()
    assert runs and {"provider", "status", "message"} <= set(runs[0])
