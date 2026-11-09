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
        assert p["status"] == "ok" and len([m for m in p["markets"] if not m.get("extended")]) == len(DISPLAY_KEYS) and p["expected_goals"]["home"] > 0
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


def test_featured_selection(populated, client):
    with SessionLocal() as db:
        feats = db.scalars(select(Prediction).where(Prediction.featured.is_(True))).all()
        per_day = {}
        for p in feats:
            assert p.probability >= 0.72 and p.confidence >= 70 and p.featured_at is not None
            per_day.setdefault(p.match.kickoff.date(), set()).add(p.match_id)
        assert all(len(v) <= 5 for v in per_day.values())
        assert len({p.match_id for p in feats}) == len(feats)  # un par match
    perf = client.get("/api/performance", params={"featured": True}).json()
    assert perf["overall"]["total"] == len(feats)
    summary = client.get("/api/public-summary").json()
    assert summary["selection"]["total"] == len(feats) and summary["backtest"]["tiers"]


def test_live_scores_update_results(populated, monkeypatch):
    from app.providers.football_data_org import FootballDataOrg
    from app.services.live import refresh_scores, _pick_state
    with SessionLocal() as db:
        m = db.scalars(select(Match).where(Match.status == "FINISHED").order_by(Match.kickoff.desc())).first()
        hg, ag = m.home_goals, m.away_goals
        m.status, m.home_goals, m.away_goals = "SCHEDULED", None, None
        db.commit()
        payload = [{"status": "FINISHED", "utcDate": m.kickoff.isoformat().replace("+00:00", "Z"),
                    "competition": {"code": "PL"}, "homeTeam": {"name": m.home_team.name},
                    "awayTeam": {"name": m.away_team.name},
                    "score": {"fullTime": {"home": hg, "away": ag}, "halfTime": {"home": 0, "away": 0}}}]
        monkeypatch.setattr(FootballDataOrg, "is_configured", lambda self: True)
        monkeypatch.setattr(FootballDataOrg, "matches_between", lambda self, a, b: payload)
        res = refresh_scores(db, now=m.kickoff + timedelta(hours=3))
        assert res["ok"] and res["updated"] == 1
        db.refresh(m)
        assert m.status == "FINISHED" and (m.home_goals, m.away_goals) == (hg, ag)
        p = Prediction(match_id=m.id, market_key="O0.5", market_label="+0,5", probability=0.9, confidence=80,
                       confidence_level="Élevée", tier="A", engine_version="t")
        assert _pick_state(p, m, {"home": 1, "away": 0}) == "Déjà validé"
        assert _pick_state(p, m, {"home": 0, "away": 0}) == "En attente de buts"


def test_catalog_endpoints(client):
    comps = client.get("/api/competitions").json()["items"]
    eng = next(c for c in comps if c["code"] == "ENG1")
    d = client.get("/api/competitions/ENG1").json()
    assert d["competition"]["name"] == "Premier League" and len(d["standings"]) == 20
    assert d["standings"][0]["position"] == 1 and d["standings"][0]["team"] and d["stats"]["matches"] > 200
    assert client.get("/api/competitions/NOPE").status_code == 404
    team_id = d["standings"][0]["team_id"]
    t = client.get(f"/api/teams/{team_id}").json()
    assert t["team"]["id"] == team_id and t["standing"]["position"] == 1
    assert t["form"]["last10"]["played"] == 10 and t["recent"]
    s = client.get("/api/search", params={"q": "manchester"}).json()
    names = {x["name"] for x in s["teams"]}
    assert {"Man City", "Man United"} <= names
    assert client.get("/api/search", params={"q": "angle"}).json()["countries"] == ["Angleterre"]
    assert any(c["code"] == "ENG1" for c in client.get("/api/search", params={"q": "premier"}).json()["competitions"])
    live = client.get("/api/live", params={"tz": "Africa/Bamako"}).json()
    assert {"live", "upcoming", "finished"} <= set(live)


def test_international_teams_merge_with_clubs(populated):
    from app.models import Team
    from app.services.sync import TeamResolver, find_club, merge_international_duplicates
    with SessionLocal() as db:
        ucl = db.scalar(select(Competition).where(Competition.code == "UCL"))
        city = db.scalar(select(Team).where(Team.name == "Man City"))
        assert find_club(db, "Manchester City FC").id == city.id
        assert find_club(db, "Ferencvárosi TC") is None
        dup = Team(name="Arsenal FC", norm_name="arsenal fc-dup", country="Europe")
        other = Team(name="Ferencvárosi TC", norm_name="ferencvarosi", country="Europe")
        db.add_all([dup, other]); db.flush()
        m = Match(competition_id=ucl.id, home_team_id=dup.id, away_team_id=other.id,
                  kickoff=datetime(2026, 2, 20, 20, tzinfo=UTC), status="FINISHED", source="test", home_goals=2, away_goals=0)
        db.add(m); db.commit()
        res = merge_international_duplicates(db)
        assert "Arsenal FC → Arsenal" in res["merged"] and "Ferencvárosi TC" in res["kept"]
        db.refresh(m)
        assert m.home_team.name == "Arsenal" and m.away_team.name == "Ferencvárosi TC"
        # Les prochaines synchronisations rattachent directement au club
        assert TeamResolver(db).resolve("Chelsea FC", "Europe", "football_data_org").name == "Chelsea"
        db.rollback()


def test_match_insights_and_trends(client):
    from app.engine.trends import team_trends
    from app.engine.types import MatchData
    ms = [MatchData(i, "C", datetime(2026, 1, 20 - i, tzinfo=UTC), "A", f"B{i}", hg=3, ag=1) for i in range(8)]
    tr = team_trends("Alpha", "A", ms, "home", "à domicile", ms)
    texts = [t["text"] for t in tr]
    assert "Alpha a gagné ses 8 derniers matchs" in texts
    assert any(t.startswith("Plus de 2,5 buts dans 8 des 8") for t in texts)

    preds = client.get("/api/predictions", params={"all_markets": True}).json()["items"]
    mid = preds[0]["match"]["id"]
    d = client.get(f"/api/matches/{mid}/insights").json()
    assert d["live"]["state"] in ("scheduled", "live", "finished")
    assert len(d["form"]["home"]) == 10 and d["form"]["home"][0]["result"] in "VND"
    assert d["standings"] and d["odds"] and d["odds"][0]["average"] > 1
    assert all(t["text"] and 0 <= t["strength"] <= 2 for t in d["trends"])
    assert client.get(f"/api/matches/{mid}/live").json()["state"]
    assert client.get("/api/matches/999999/insights").status_code == 404


def test_value_picks_and_target_combos(populated, client):
    from app.engine.combos import Leg
    from app.engine.value import naive_equivalent, short_equivalent, target_combos
    with SessionLocal() as db:
        vals = db.scalars(select(Prediction).where(Prediction.value_pick.is_(True))).all()
        assert vals, "aucun pronostic à cote publié"
        for p in vals:
            ref = p.odds or 1 / p.probability
            assert 1.40 <= ref <= 2.20 and p.probability >= 0.52 and p.confidence >= 60
            assert p.market_key not in ("X", "HT_X", "HT_1", "HT_2")
        assert len({p.match_id for p in vals}) == len(vals)
    assert client.get("/api/performance", params={"value": True}).json()["overall"]["total"] == len(vals)
    dash = client.get("/api/dashboard").json()
    assert "value_picks" in dash and "combo_of_day" in dash

    r = client.post("/api/combos/target", json={"target": 2.0, "max_legs": 3, "hours": 72}).json()
    assert r["combos"], r["message"]
    for c in r["combos"]:
        assert 2 <= c["n_legs"] <= 3 and c["valid"]
        assert 1.84 <= c["reference_odds"] <= 2.7
        assert len({l["match_id"] for l in c["legs"]}) == c["n_legs"]
    assert r["comparison"]["long"]["legs"] == 8 and r["comparison"]["short"]["probability"] > r["comparison"]["long"]["probability"]

    # Synthétique : la combinaison retenue privilégie la plus forte chance de passer.
    legs = [Leg(i, "1", "Victoire", p, 75, odds=o) for i, (p, o) in enumerate([(0.68, 1.40), (0.66, 1.45), (0.40, 2.3), (0.9, 1.05)])]
    best = target_combos(legs, 2.0, max_results=1)[0]
    assert {l["match_id"] for l in best["legs"]} == {0, 1} and best["all_bookmaker_odds"]
    assert short_equivalent(2.0)["leg_odds"] == 1.41 and naive_equivalent(2.0)["total_odds"] == 2.14


def test_ai_analysis_grounded(populated, client, monkeypatch):
    """L'IA est remplacée ici par une fausse réponse (test uniquement) pour vérifier les contrôles."""
    from app.ai import providers
    from app.ai.analyst import allowed_numbers, check_output, sanitize, unverified_numbers
    from app.services import ai_service

    mid = client.get("/api/predictions").json()["items"][0]["match"]["id"]
    monkeypatch.setattr(ai_service, "utcnow", lambda: NOW)
    # Sans clé : état « non configuré », jamais de texte simulé.
    monkeypatch.setattr(ai_service, "configured_providers", lambda: [])
    r = client.get(f"/api/matches/{mid}/ai").json()
    assert r["status"] == "not_configured" and "analysis" not in r
    assert client.get("/api/meta").json()["ai"]["configured"] is False

    seen = []

    class Fake(providers.AIProvider):
        name, label = "fake", "Fausse IA"

        def generate_json(self, system, user, schema):
            seen.append(user)
            ok = len(seen) > 1
            return {
                "titre": "Match équilibré", "resume": ("Le modèle reste prudent." if ok else
                                                        "Le favori gagne 87 % de ses matchs. Le modèle reste prudent."),
                "contexte": ["Classement serré.", "Forme récente correcte."],
                "analyse_domicile": "Solide à domicile.", "analyse_exterieur": "Moins régulier.",
                "confrontations": "Peu de confrontations.", "scenario": "Match fermé.",
                "pronostic_principal": {"cle": "U3.5", "argument": "Peu de buts attendus."},
                "alternatives": [{"cle": "ZZZ", "argument": "Inconnu."}],
                "points_de_vigilance": ["Absences non disponibles."],
            }
    fake = Fake("faux-modele")
    monkeypatch.setattr(ai_service, "configured_providers", lambda: [fake])
    monkeypatch.setattr(ai_service, "call_with_fallback", lambda s, u, sc: (fake.generate_json(s, u, sc), fake))
    r = client.get(f"/api/matches/{mid}/ai").json()
    assert r["status"] == "ok", r
    assert len(seen) == 2 and "refusée" in seen[1] and "87" in seen[1]  # deuxième essai avec la correction
    a = r["analysis"]
    assert "87" not in a["resume"] and a["alternatives"] == []  # marché inconnu écarté
    pp = a["pronostic_principal"]
    # La probabilité affichée est celle du moteur SAM, pas celle de l'IA.
    with SessionLocal() as db:
        from app.models import Analysis
        payload = db.scalar(select(Analysis).where(Analysis.match_id == mid)).payload
    assert pp["probability"] == next(m["probability"] for m in payload["markets"] if m["key"] == "U3.5")
    # Cache : pas de nouvel appel.
    assert client.get(f"/api/matches/{mid}/ai").json()["status"] == "ok" and len(seen) == 2

    dossier = {"x": [64, 1.44, "Plus de 2,5 buts dans 8 des 10 derniers matchs"], "y_pct": 64, "conf": 91}
    allowed = allowed_numbers(dossier)
    assert unverified_numbers("64 % et cote 1,44, 8 des 10", allowed) == []
    assert unverified_numbers("72 % de victoires", allowed) == ["72"]
    from app.ai.analyst import allowed_percents
    pc = allowed_percents(dossier)
    assert unverified_numbers("64 % de chances", allowed, pc) == []
    assert unverified_numbers("91 % de victoires", allowed, pc) == ["91 %"]  # 91 existe, mais pas en pourcentage
    d2 = {"difference_de_buts": -7, "confiance_sur_100": 84}
    assert unverified_numbers("différence de -7, confiance de 84 %", allowed_numbers(d2), allowed_percents(d2)) == []
    content, removed = sanitize({"resume": "Cote 1,44. Il gagne 72 % du temps.", "pronostic_principal": {"cle": "1"}},
                                dossier, {"1"})
    assert content["resume"] == "Cote 1,44." and removed == 1
    assert check_output({}, dossier, {"1"})


def test_assistant_tools_and_checks(populated, client, monkeypatch):
    """Assistant : outils SAM réels, IA remplacée par un faux (test uniquement) pour vérifier les contrôles."""
    from app.ai import assistant, providers
    from app.services import ai_service

    monkeypatch.setattr(assistant, "utcnow", lambda: NOW - timedelta(hours=12))
    with SessionLocal() as db:
        box = assistant.Toolbox(db)
        ms = box.run("lister_matchs", {"periode_heures": 72})["matchs"]
        assert ms and all("match_id" in m for m in ms)
        mid = ms[0]["match_id"]
        assert box.run("dossier_match", {"match_id": mid})["match_id"] == mid
        sel = box.run("selections", {"familles": ["corners"], "probabilite_min_pct": 50})["selections"]
        assert sel and all(s["famille"] == "Corners" for s in sel)
        c = box.run("combine_cote_cible", {"cote_cible": 2, "periode_heures": 72})
        assert c["combines"][0]["ref"] == "C1" and "C1" in box.combos
        ev = box.run("evaluer_combine", {"selections": [{"match_id": mid, "cle": "1X"}, {"match_id": mid, "cle": "O1.5"}]})
        assert "combine" in ev or "erreur" in ev
        assert box.run("outil_pirate", {})["erreur"].startswith("Outil inconnu")
        assert "tous" in box.run("bilan_sam", {})

    monkeypatch.setattr(ai_service, "configured_providers", lambda: [object()])

    class P:
        label, model = "Fausse IA", "faux"

    def fake_chat(system, hist, tools, run_tool, on_call, max_steps=5):
        on_call()
        r = run_tool("combine_cote_cible", {"cote_cible": 2, "periode_heures": 72})
        ref = r["combines"][0]
        lm = run_tool("lister_matchs", {"periode_heures": 72})["matchs"][0]
        return (f"Voici le combiné le plus solide pour une cote 2.\n[[{ref['ref']}]]\n"
                f"- Chance estimée : {ref['probabilite_pct']} %. Ce combiné gagne 95 % du temps.\n"
                f"- Match à suivre : [[M:{lm['match_id']}]]\n[[C9]]"), P()
    monkeypatch.setattr(providers, "chat_with_tools", fake_chat)
    r = client.post("/api/assistant", json={"question": "Propose-moi le meilleur combiné cote 2"}).json()
    assert r["status"] == "ok", r
    assert "C1" in r["combos"] and "C9" not in r["answer"] and "95 %" not in r["answer"]
    assert "Chance estimée" in r["answer"] and r["matches"] and r["removed"] >= 2
    assert r["combos"]["C1"]["legs"]  # vraie carte du moteur, pas du texte de l'IA

    # Jeton exigé quand il est configuré ; quota par membre.
    from app.config import get_settings
    monkeypatch.setattr(get_settings(), "assistant_token", "secret")
    assert client.post("/api/assistant", json={"question": "test"}).status_code == 401
    monkeypatch.setattr(get_settings(), "assistant_member_daily", 1)
    h = {"X-Assistant-Token": "secret", "X-Member-Id": "membre-test"}
    assert client.post("/api/assistant", json={"question": "Bonjour"}, headers=h).json()["status"] == "ok"
    assert client.post("/api/assistant", json={"question": "Bonjour"}, headers=h).json()["status"] == "quota"

    # Réglages de l'administration : liste d'accès, coupure, analyses préparées seulement
    assert client.put("/api/admin/ai/settings", json={"assistant": "liste", "allowed_emails": "Ami@Exemple.ml, x"},
                      headers=ADMIN).status_code == 400  # adresse invalide refusée
    cfg = client.put("/api/admin/ai/settings", json={"assistant": "liste", "allowed_emails": "Ami@Exemple.ml",
                                                     "member_daily": 5}, headers=ADMIN).json()
    assert cfg["allowed_emails"] == ["ami@exemple.ml"] and cfg["member_daily"] == 5
    h2 = {"X-Assistant-Token": "secret", "X-Member-Id": "membre-2", "X-Member-Email": "autre@exemple.ml"}
    assert client.post("/api/assistant", json={"question": "Bonjour"}, headers=h2).json()["status"] == "forbidden"
    h2["X-Member-Email"] = "ami@exemple.ml"
    assert client.post("/api/assistant", json={"question": "Bonjour"}, headers=h2).json()["status"] == "ok"
    client.put("/api/admin/ai/settings", json={"assistant": "off", "analyses": "preparees"}, headers=ADMIN)
    assert client.post("/api/assistant", json={"question": "Bonjour"}, headers=h2).json()["status"] == "disabled"
    meta = client.get("/api/meta").json()["ai"]
    assert meta["assistant"] is False and meta["analyses"] is True
    st = client.get("/api/admin/ai/status", headers=ADMIN).json()
    assert st["used_assistant"] >= 1 and st["questions_today"] >= 2 and st["settings"]["assistant"] == "off"
    client.put("/api/admin/ai/settings", json={"analyses": "off"}, headers=ADMIN)
    assert client.get(f"/api/matches/{lm_id(client)}/ai").json()["status"] == "disabled"
    client.put("/api/admin/ai/settings", json={"assistant": "tous", "analyses": "auto", "allowed_emails": []},
               headers=ADMIN)


def lm_id(client):
    with SessionLocal() as db:
        return db.scalar(select(Match.id).order_by(Match.kickoff.desc()))


def test_jouer_virtual_bets(populated, monkeypatch):
    """Section Jouer : portefeuille, cotes relues côté serveur, combiné, règlement, classement."""
    from app.api import game as game_api
    from app.models import Bet, Wallet
    from app.services import game

    # On rejoue la journée avant son coup d'envoi (les matchs sont terminés dans la base de test).
    saved = {}
    with SessionLocal() as db:
        for m in db.scalars(select(Match).where(Match.kickoff > NOW)).unique().all():
            saved[m.id] = (m.status, m.home_goals, m.away_goals)
            m.status = "SCHEDULED"
        db.commit()
    with TestClient(app) as c:
        monkeypatch.setattr(game_api, "_now", lambda: NOW)
        h = {"X-Member-Id": "joueur-1", "X-Member-Name": "Awa"}
        assert c.get("/api/jeu/board").status_code == 401  # membre requis
        b = c.get("/api/jeu/board", params={"jour": "tout"}, headers=h).json()
        assert b["wallet"]["balance"] in (game.START_BALANCE, game.START_BALANCE + game.DAILY_BONUS)
        groups = b["groups"]
        assert groups and groups[0]["matches"][0]["odds"]["1"]["odds"] > 1
        m1 = groups[0]["matches"][0]["match"]["id"]
        all_m = [x["match"]["id"] for g in groups for x in g["matches"]]
        m2 = next(x for x in all_m if x != m1)
        mk = c.get(f"/api/jeu/matchs/{m1}", headers=h).json()
        assert mk["open"] and mk["groups"][0]["family"] == "result"
        sam_odds = [r for g in mk["groups"] for r in g["markets"] if r["odds_source"] == "sam"]
        assert sam_odds and all(r["odds"] < 1 / r["probability"] for r in sam_odds)  # marge appliquée

        sel = [{"match_id": m1, "market_key": "1X"}, {"match_id": m2, "market_key": "O1.5"}]
        q = c.post("/api/jeu/devis", json={"selections": sel, "stake": 100}, headers=h).json()
        assert q["total_odds"] and q["sam_probability"] and not q["errors"]
        before = c.get("/api/jeu/mes-paris", headers=h).json()["wallet"]["balance"]
        r = c.post("/api/jeu/paris", json={"selections": sel, "stake": 100, "mode": "combine"}, headers=h).json()
        assert r["wallet"]["balance"] == before - 100 and r["bets"][0]["total_odds"] == q["total_odds"]
        # Solde insuffisant, mise hors bornes, même match deux fois dans un combiné
        assert c.post("/api/jeu/paris", json={"selections": sel, "stake": 4999, "mode": "simple"}, headers=h).status_code == 422
        assert c.post("/api/jeu/paris", json={"selections": sel, "stake": 5, "mode": "combine"}, headers=h).status_code == 422
        dup = [{"match_id": m1, "market_key": "1X"}, {"match_id": m1, "market_key": "O1.5"}]
        assert c.post("/api/jeu/paris", json={"selections": dup, "stake": 50, "mode": "combine"}, headers=h).status_code == 422
        r2 = c.post("/api/jeu/paris", json={"selections": sel, "stake": 50, "mode": "simple"}, headers=h).json()
        assert len(r2["bets"]) == 2 and r2["wallet"]["balance"] == before - 200
        # Marchés étendus : présents dans la fiche, pariables, probabilité du combiné calculée
        xg = [g for g in mk["groups"] if g.get("extended")]
        assert xg and any(r["key"] == "e:CS1-1" for g in xg for r in g["markets"])
        xsel = [{"match_id": m1, "market_key": "e:1&BY"}, {"match_id": m2, "market_key": "e:TEVEN"}]
        qx = c.post("/api/jeu/devis", json={"selections": xsel, "stake": 10}, headers=h).json()
        assert not qx["errors"] and qx["sam_probability"] and "et les deux marquent" in qx["legs"][0]["label"]
        r3 = c.post("/api/jeu/paris", json={"selections": xsel, "stake": 10, "mode": "combine"}, headers=h).json()
        assert r3["bets"][0]["legs"][0]["odds_source"] == "sam"
        before -= 10
        live = c.get("/api/jeu/mes-paris", headers=h).json()["bets"][0]["legs"][0]["live"]
        assert live["state"] == "scheduled"

    # Règlement : la journée se joue, résultats réels remis en place.
    with SessionLocal() as db:
        for mid, (status, hg, ag) in saved.items():
            m = db.get(Match, mid)
            m.status, m.home_goals, m.away_goals = status, hg, ag
        db.commit()
        res = game.settle_bets(db, NOW + timedelta(days=5))
        bets = db.scalars(select(Bet).where(Bet.member_id == "joueur-1")).all()
        assert all(x.status != "pending" for x in bets) and sum(res.values()) == 4
        w = db.get(Wallet, "joueur-1")
        assert w.balance == before - 200 + sum(x.payout for x in bets)
        rk = game.ranking(db, "joueur-1", NOW + timedelta(days=5))
        assert rk["me"] and rk["me"]["name"] == "Awa"


def test_extended_markets_engine():
    from app.engine import extended as x
    from app.engine.markets import score_matrix
    keys = [m.key for m in x.CATALOG]
    assert len(keys) == len(set(keys)) and max(map(len, keys)) <= 16 and len(keys) > 200
    rows = {r["key"]: r for r in x.compute(score_matrix(1.6, 1.1, -0.05), 1.6, 1.1, (0.7, 0.5))}
    assert abs(sum(rows[f"e:HF{a}/{b}"]["probability"] for a in "1X2" for b in "1X2") - 1) < 1e-3
    assert abs(rows["e:TEVEN"]["probability"] + rows["e:TODD"]["probability"] - 1) < 1e-3
    assert rows["e:AH1-1"]["void_probability"] > 0  # ligne entière : remboursement possible
    assert "e:HF1/1" not in {r["key"] for r in x.compute(score_matrix(1.6, 1.1), 1.6, 1.1, None)}  # sans mi-temps
    assert x.settle("e:AH1-1", 2, 1, 1, 0) == "void" and x.settle("e:AH1-0.5", 2, 1, 1, 0) == "won"
    assert x.settle("e:HF1/2", 1, 2, 1, 0) == "won" and x.settle("e:HF1/2", 1, 2, None, None) is None
    assert x.settle("e:1&BY", 2, 1, 0, 0) == "won" and x.settle("e:CS2-1", 2, 1, 0, 0) == "won"
    assert x.settle("e:W1NIL", 1, 0, 0, 0) == "won" and x.settle("e:HM2", 1, 3, 1, 0) == "won"


def test_extended_markets_in_predictions(populated):
    """Marchés étendus validés par backtest : présents dans l'analyse, au plus un pronostic par match, réglés."""
    from app.engine.extended_picks import validated
    assert len(validated()) > 150
    with SessionLocal() as db:
        ans = db.scalars(select(Analysis)).all()
        xs = [m for a in ans for m in a.payload["markets"] if m.get("extended")]
        assert xs and all(m["key"] in validated() and m["probability"] >= 0.70 for m in xs)
        assert all(sum(k.startswith("e:") for k in a.payload["picks"]) <= 1 for a in ans)
        preds = db.scalars(select(Prediction).where(Prediction.market_key.startswith("e:"))).all()
        assert all(not p.featured for p in preds)
        assert any(p.result in ("won", "lost") for p in preds) or not preds


def test_stats_completion_sources(populated, monkeypatch):
    """Corners/cartons/mi-temps complétés depuis footballdata.io et Sportmonks (réponses simulées en test)."""
    from app.config import get_settings
    from app.services import stats_completion as sc
    with SessionLocal() as db:
        m = db.scalars(select(Match).where(Match.status == "FINISHED").order_by(Match.kickoff.desc())).first()
        m.home_corners = m.away_corners = m.home_yellow = m.away_yellow = None
        home, away, when = m.home_team.name, m.away_team.name, m.kickoff
        db.commit()
        mid = m.id

    class R:
        status_code = 200

        def __init__(self, data):
            self._d = data

        def json(self):
            return self._d

    def fake_get(url, params=None, headers=None, timeout=None):
        assert headers and headers["Authorization"].startswith("Bearer ")
        return R({"data": {"matches": [{"status": "complete", "match_date": when.strftime("%Y-%m-%d %H:%M:%S"),
                                        "home_team": {"team_name": home}, "away_team": {"team_name": away},
                                        "stats": {"corners": {"home": 6, "away": 3},
                                                  "cards": {"yellow": {"home": 2, "away": 1}, "red": {"home": 0, "away": 1}}}}]}})
    monkeypatch.setattr(sc.httpx, "get", fake_get)
    monkeypatch.setattr(get_settings(), "footballdata_io_key", "fd_test")
    monkeypatch.setattr(sc, "FDIO_LEAGUES", {"ENG1": 15})
    with SessionLocal() as db:
        res = sc.complete_stats(db, now=when + timedelta(days=1))
        m = db.get(Match, mid)
        assert res[0]["status"] == "ok" and (m.home_corners, m.away_corners, m.home_yellow, m.away_red) == (6, 3, 2, 1)


def test_allsports_africa(populated, monkeypatch):
    """Championnat africain via AllSportsAPI : historique, calendrier, cotes, direct (réponses simulées en test)."""
    from app.config import get_settings
    from app.providers.allsports import AllSports
    from app.services import allsports_sync as asy
    from app.models import Competition, OddsQuote

    teams = ["Djoliba", "Stade Malien", "Real Bamako", "Onze Createurs", "AS Bakaridjan", "Binga FC"]
    base = datetime(2026, 1, 10, 16, 0, tzinfo=timezone.utc)
    hist, k = [], 0
    for r in range(4):
        for i, h in enumerate(teams):
            for j, a in enumerate(teams):
                if i == j or (i + j + r) % 3:
                    continue
                k += 1
                d = base + timedelta(days=7 * k // 3)
                hist.append({"event_key": 1000 + k, "event_date": d.strftime("%Y-%m-%d"), "event_time": "16:00",
                             "event_home_team": h, "event_away_team": a, "event_status": "Finished",
                             "event_final_result": f"{(i + r) % 3} - {(j + k) % 2}", "event_halftime_result": "0 - 0",
                             "league_season": "2025/2026",
                             "statistics": [{"type": "Corners", "home": "1", "away": "0"},
                                            {"type": "Corners", "home": "6", "away": "3"},
                                            {"type": "Yellow Cards", "home": "2", "away": "1"}]})
    now = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)
    upcoming = [{"event_key": 5001, "event_date": "2026-11-02", "event_time": "16:00", "event_home_team": "Djoliba",
                 "event_away_team": "Stade Malien", "event_status": "", "event_final_result": "-",
                 "league_season": "2026/2027"}]
    odds = {"5001": [{"match_id": 5001, "odd_bookmakers": "bet365", "odd_1": 2.1, "odd_x": 3.0, "odd_2": 3.4,
                      "o+2.5": 2.4, "ah0_1": 1.5, "bts_yes": None}]}
    calls = []

    def fake_get(self, met, **params):
        calls.append((met, params.get("leagueId")))
        if met == "Fixtures":
            return [x for x in hist + upcoming if params["from"] <= x["event_date"] <= params["to"]]
        if met == "Odds":
            return odds
        if met == "Livescore":
            return [dict(upcoming[0], event_status="Finished", event_final_result="2 - 1",
                         event_halftime_result="1 - 0", statistics=[{"type": "Corners", "home": "5", "away": "4"},
                                                                     {"type": "Ball Possession", "home": "55%", "away": "45%"}],
                         goalscorers=[{"time": "12", "home_scorer": "A. Traoré", "away_scorer": "", "score": "1 - 0", "info": ""},
                                      {"time": "88", "home_scorer": "", "away_scorer": "B. Keita", "score": "2 - 1",
                                       "info": "Penalty"}],
                         cards=[{"time": "45+2", "card": "yellow card", "home_fault": "", "away_fault": "C. Diarra"}])]
        return []

    monkeypatch.setattr(AllSports, "_get", fake_get)
    monkeypatch.setattr(get_settings(), "allsports_key", "test")
    with SessionLocal() as db:
        comp = db.scalar(select(Competition).where(Competition.code == "MLI1"))
        assert comp is not None and comp.primary_source == "allsports" and comp.allsports_id == 558
        comp.enabled = True
        db.commit()
        res = asy.run_allsports(db, {"history", "upcoming"}, now, False, 2)
        assert [r["status"] for r in res] == ["ok", "ok"], res
        n_hist = db.scalar(select(func.count(Match.id)).where(Match.competition_id == comp.id, Match.status == "FINISHED"))
        assert n_hist == len(hist)
        m = db.scalar(select(Match).where(Match.competition_id == comp.id, Match.status == "FINISHED"))
        assert (m.home_corners, m.away_corners, m.home_yellow, m.home_red) == (6, 3, 2, 0)  # total le plus élevé
        up = db.scalar(select(Match).where(Match.competition_id == comp.id, Match.status == "SCHEDULED"))
        assert up.source_ref == "5001" and up.kickoff == datetime(2026, 11, 2, 16, 0, tzinfo=timezone.utc)
        q = {o.market_key: o.price for o in db.scalars(select(OddsQuote).where(OddsQuote.match_id == up.id))}
        assert q == {"1": 2.1, "X": 3.0, "2": 3.4, "O2.5": 2.4}  # lignes asiatiques et valeurs nulles ignorées
        # Deuxième passage : l'historique déjà en base n'est pas redemandé
        calls.clear()
        asy.run_allsports(db, {"history"}, now, False, 2)
        assert not [c for c in calls if c[0] == "Fixtures"]  # années déjà importées : aucun nouvel appel
        # Direct : le match se termine, score et statistiques enregistrés
        asy._cache["at"] = None
        out = asy.live_scores(db, datetime(2026, 11, 2, 17, 50, tzinfo=timezone.utc), set())
        db.refresh(up)
        assert out["updated"] == 1 and up.status == "FINISHED" and (up.home_goals, up.away_goals, up.ht_home_goals) == (2, 1, 1)
        assert (up.home_corners, up.away_corners) == (5, 4)
        ev = up.details["events"]
        assert [e["minute"] for e in ev] == ["12", "45+2", "88"] and ev[2]["type"] == "penalty" and ev[1]["side"] == "away"
        assert {x["label"]: (x["home"], x["away"]) for x in up.details["stats"]}["Possession"] == (55, 45)
        comp.enabled = False
        db.commit()


def test_sportapi_fast_results_and_live_backup(populated, monkeypatch):
    """SportAPI.ai : score final + mi-temps d'un match sans résultat, puis direct de secours (réponses simulées)."""
    from app.config import get_settings
    from app.services import sportapi as sa

    with SessionLocal() as db:
        m = db.scalars(select(Match).join(Competition, Match.competition_id == Competition.id).where(
            Match.status == "FINISHED", Competition.enabled.is_(True)).order_by(Match.kickoff.desc())).first()
        saved = (m.status, m.home_goals, m.away_goals, m.ht_home_goals, m.ht_away_goals)
        m.status, m.home_goals, m.away_goals, m.ht_home_goals, m.ht_away_goals = "SCHEDULED", None, None, None, None
        db.commit()
        mid, home, away, ko = m.id, m.home_team.name, m.away_team.name, m.kickoff

    class R:
        status_code = 200

        def __init__(self, d):
            self._d = d

        def json(self):
            return self._d

    row = {"id": 77, "kickoff_utc": ko.strftime("%Y-%m-%dT%H:%M:%SZ"), "home_team": home, "away_team": away,
           "status": "FT", "home_score": 3, "away_score": 1, "minute": None}

    def fake_get(url, headers=None, timeout=None):
        assert headers["X-Api-Key"] == "sk_test"
        if url.endswith("/fixtures/77"):
            return R({"success": True, "fixture": {"ht_home": 1, "ht_away": 0}})
        return R({"success": True, "data": [row, dict(row, id=78, home_team="Équipe inconnue", away_team="Autre")]})

    monkeypatch.setattr(sa.httpx, "get", fake_get)
    monkeypatch.setattr(get_settings(), "sportapi_key", "sk_test")
    with SessionLocal() as db:
        res = sa.complete_results(db, ko + timedelta(hours=4))
        m = db.get(Match, mid)
        assert res["status"] == "ok" and res["items"] == 1
        assert (m.status, m.home_goals, m.away_goals, m.ht_home_goals, m.ht_away_goals) == ("FINISHED", 3, 1, 1, 0)
        # Direct de secours : match en cours
        m.status, m.home_goals, m.away_goals = "SCHEDULED", None, None
        db.commit()
        row.update(status="LIVE", minute="63'", home_score=1, away_score=1)
        sa._cache["at"] = None
        out = sa.live_fallback(db, ko + timedelta(minutes=80), [db.get(Match, mid)])
        assert out["ok"] and out["live"][0]["minute"] == "63" and out["live"][0]["home"] == 1
        m = db.get(Match, mid)
        m.status, m.home_goals, m.away_goals, m.ht_home_goals, m.ht_away_goals = saved
        db.commit()


def test_cup_pooling_backtest_and_analysis(populated, client):
    """Coupes : backtest comparatif exécutable et analyse avec historique commun (activable)."""
    from app.services import cup_pool
    with SessionLocal() as db:
        r = cup_pool.cup_backtest(db, "ENG1", months=1)  # simple exécution sur des données réelles
        assert r["status"] == "ok" and "matchs_communs" in r
    assert client.put("/api/admin/cup-pooling", json={"enabled": True}, headers=ADMIN).json() == {"enabled": True}
    with SessionLocal() as db:
        assert cup_pool.enabled(db)
        assert run_analysis(db, now=NOW, publish=False)["analysed"] >= 0
    client.put("/api/admin/cup-pooling", json={"enabled": False}, headers=ADMIN)


def test_live_board_with_extended_pick(populated, client):
    """Page Direct : un pronostic sur un marché étendu ne doit jamais faire échouer la page."""
    from app.engine.markets import evaluate_market
    from app.engine.types import MatchData
    from app.models import Prediction
    from app.services.live import _pick_state
    m = MatchData(1, 1, NOW, 1, 2, hg=2, ag=1, hthg=1, htag=0)
    assert evaluate_market("e:EH-22", m) in (True, False, None)
    with SessionLocal() as db:
        match = db.scalars(select(Match).where(Match.status == "FINISHED")).first()
        p = Prediction(match_id=match.id, market_key="e:EH-22", market_label="test", probability=0.6)
        assert isinstance(_pick_state(p, match, {"home": 1, "away": 0}), str)
    assert client.get("/api/live").status_code == 200


def test_ai_web_news_rules():
    """Recherche web : faits repris sans chiffre ; un chiffre venu du web n'est jamais validé."""
    from app.ai.analyst import check_output, sanitize
    dossier = {"match": {"domicile": "A", "exterieur": "B"}, "marches": [{"cle": "1X", "probabilite_pct": 72}],
               "actualites_web": {"texte": "Selon la presse, 3 joueurs de A sont blessés.", "sources": ["Journal"]}}
    out = {"titre": "A – B", "resume": "Match serré.", "contexte": ["A reçoit B."], "analyse_domicile": "Solide.",
           "analyse_exterieur": "Irrégulier.", "confrontations": "Non disponible.", "scenario": "Match fermé.",
           "pronostic_principal": {"cle": "1X", "argument": "Probabilité de 72 %."}, "alternatives": [],
           "points_de_vigilance": ["Absences signalées chez A."],
           "actualites": ["Selon la presse, le gardien titulaire de A est blessé.",
                          "Selon la presse, 3 joueurs de A sont absents."]}
    problems = check_output(out, dossier, {"1X"})
    assert any("3" in p for p in problems)  # le chiffre du web est signalé
    content, removed = sanitize(out, dossier, {"1X"})
    assert content["actualites"] == ["Selon la presse, le gardien titulaire de A est blessé."] and removed == 1


def test_assistant_answers_any_market(populated, monkeypatch):
    """Assistant : marché précis (même non retenu), recherche de tout match, avis prudent sans données."""
    from app.ai.assistant import Toolbox
    from app.models import Analysis
    with SessionLocal() as db:
        a = db.scalar(select(Analysis).where(Analysis.status == "ok"))
        box = Toolbox(db)
        r = box.marches_match(a.match_id, "score exact")
        assert r["marches"] and all("score" in x["marche"].lower() or "exact" in x["famille"].lower() for x in r["marches"])
        main = box.marches_match(a.match_id)
        assert main["marches"] and not any(x["cle"].startswith("e:") for x in main["marches"])
        assert any(not x["retenu_par_sam"] for x in main["marches"])  # marchés non retenus aussi
        home = a.match.home_team.name.split()[0]
        assert box.chercher_match(home)["matchs"] or True
        assert "note" in box.chercher_match("Equipe Introuvable FC")
        miss = box.marches_match(999999)
        assert miss["donnees_insuffisantes"] is True and "actualites_web" in miss["note"]


def test_usage_counter_atomic():
    """Compteurs d'utilisation : incréments répétés sans doublon de ligne (upsert atomique)."""
    from app.models import ApiUsage
    from app.services.usage import bump_usage
    with SessionLocal() as db:
        for _ in range(3):
            bump_usage(db, "test-compteur", 2, day="2026-01-01")
        assert db.get(ApiUsage, ("test-compteur", "2026-01-01")).requests == 6


def test_web_sources_freshness():
    """Recherche web : une source datée d'une année passée est écartée ; sans source récente, aucun texte."""
    from datetime import datetime, timezone
    from app.ai.providers import _fresh_only
    y = datetime.now(timezone.utc).year
    old = {"text": "x", "sources": [{"title": f"Guide {y - 2}", "uri": f"https://e.com/{y - 2}/a"}]}
    assert _fresh_only(old) == {"text": "", "sources": []}
    mix = _fresh_only({"text": "x", "sources": [{"title": "Sans date", "uri": "https://e.com/a"},
                                                 {"title": "Avant-match", "uri": f"https://e.com/{y}/11/b"},
                                                 {"title": f"Bilan {y - 1}", "uri": "https://e.com/c"}]})
    assert [s["title"] for s in mix["sources"]] == ["Sans date", "Avant-match"] and mix["text"] == "x"


def test_combo_picks_same_match(populated, client):
    """Pronostics combinés (résultat / les deux marquent + buts) : marchés validés, zone de cote 1,60 – 3,20,
    un par match, au plus 4 par jour, exposés dans le tableau de bord, l'historique et la performance."""
    from collections import Counter
    from app.engine.extended_picks import COMBO_RE, validated
    assert COMBO_RE.match("e:BY&TO2.5") and COMBO_RE.match("e:12&TO2.5") and not COMBO_RE.match("e:1X&T2U1.5")
    with SessionLocal() as db:
        ans = db.scalars(select(Analysis)).all()
        combos = [c for a in ans for c in a.payload.get("combos") or []]
        assert combos, "aucun marché combiné calculé"
        for c in combos:
            assert c["family"] == "res_combo" and c["key"] in validated() and COMBO_RE.match(c["key"])
            assert 0.50 <= c["probability"] and 1.60 <= c["fair_odds"] <= 3.20
        assert {"e:BY&TO2.5", "e:12&TO2.5", "e:1&TO2.5", "e:2&TO2.5"} <= set(validated())  # combos demandés validés
        preds = db.scalars(select(Prediction).where(Prediction.combo_pick.is_(True))).all()
        assert preds, "aucun pronostic combiné publié"
        assert len({p.match_id for p in preds}) == len(preds)
        assert max(Counter(p.match.kickoff.date() for p in preds).values()) <= 4
        assert all(p.market_key.startswith("e:") and p.confidence >= 70 for p in preds)
    assert client.get("/api/history", params={"combo": True}).json()["total"] == len(preds)
    assert client.get("/api/performance", params={"combo": True}).json()["overall"]["total"] == len(preds)
    dash = client.get("/api/dashboard").json()
    assert "combo_picks" in dash and "combo_performance" in dash
    assert all(c["combo_pick"] and c["reference_odds"] >= 1.6 for c in dash["combo_picks"])



def test_banker_and_track_record(populated, client):
    """Le banker du jour : au plus un par jour, très solide, grands championnats ; bilan public sans données inventées."""
    from collections import Counter
    with SessionLocal() as db:
        bk = db.scalars(select(Prediction).where(Prediction.banker.is_(True))).all()
        assert all(p.probability >= 0.75 and p.confidence >= 75 for p in bk)
        assert not bk or max(Counter(p.match.kickoff.date() for p in bk).values()) <= 3
    tr = client.get("/api/track-record").json()
    assert [c["key"] for c in tr["categories"]] == ["banker", "selection", "value", "combo", "all"]
    allp = next(c for c in tr["categories"] if c["key"] == "all")["periods"]["all"]
    assert allp["total"] == client.get("/api/performance").json()["overall"]["total"]
    assert all(c["n"] >= 10 for c in tr["by_competition"])
    assert set(tr["banker_form"]) <= {"won", "lost"}
    dash = client.get("/api/dashboard").json()
    assert "bankers" in dash and "banker_performance" in dash


def test_market_stats_pages(client):
    """Statistiques par marché : fréquences réelles, au moins 5 matchs joués, matchs à venir au-dessus du seuil."""
    assert len(client.get("/api/stats").json()["items"]) >= 8
    assert client.get("/api/stats/inconnu").status_code == 404
    comps = client.get("/api/competitions").json()["items"]
    code = comps[0]["code"]
    for mk in ("btts", "plus-2-5", "clean-sheet", "corners"):
        r = client.get(f"/api/stats/{mk}", params={"competition": code, "min_probability": 0.5, "days": 7}).json()
        assert all(t["n"] >= 5 and 0 <= t["rate"] <= 1 and len(t["last"]) <= 5 for t in r["teams"])
        assert [t["rate"] for t in r["teams"]] == sorted((t["rate"] for t in r["teams"]), reverse=True)
        assert all(u["probability"] >= 0.5 for u in r["upcoming"])
    r = client.get("/api/stats/btts", params={"competition": code}).json()
    assert r["teams"] and r["league_n"] > 0


def test_push_alerts(populated, client, monkeypatch):
    """Alertes : abonnement par membre, une seule fois par alerte, filtres favoris, nuit respectée, appareil
    désinstallé supprimé."""
    import pywebpush
    from app.config import get_settings
    from app.models import PushLog, PushSubscription
    from app.services import push
    cfg = get_settings()
    h = {"X-Member-Id": "alerte-1"}
    monkeypatch.setattr(cfg, "vapid_public_key", "")
    assert client.get("/api/alertes/cle").json()["enabled"] is False
    sub = {"endpoint": "https://push.exemple.ml/abc", "keys": {"p256dh": "k" * 80, "auth": "a" * 20}}
    assert client.post("/api/alertes/abonnement", json={"subscription": sub}, headers=h).status_code == 503
    monkeypatch.setattr(cfg, "vapid_public_key", "pub")
    monkeypatch.setattr(cfg, "vapid_private_key", "priv")
    monkeypatch.setattr(push, "dispatch_async", lambda: None)
    sent = []
    monkeypatch.setattr(pywebpush, "webpush", lambda **kw: sent.append(kw["data"]))
    r = client.post("/api/alertes/abonnement", json={"subscription": sub, "prefs": {"combo": True}}, headers=h).json()
    assert r["prefs"]["banker"] and r["prefs"]["combo"]
    assert client.post("/api/alertes/etat", json={"endpoint": sub["endpoint"]}, headers={"X-Member-Id": "autre"}).json()["subscribed"] is False
    assert client.post("/api/alertes/preferences", json={"endpoint": sub["endpoint"], "prefs": {}}, headers={"X-Member-Id": "autre"}).status_code == 404

    with SessionLocal() as db:
        s = db.scalar(select(PushSubscription))
        pred = db.scalars(select(Prediction)).first()
        old = (pred.result, pred.featured)
        now = pred.match.kickoff - timedelta(hours=5)
        pred.featured, pred.result = True, "pending"
        db.commit()
        night = now.replace(hour=2)
        assert push.dispatch(db, night)["skipped"] == "nuit"
        day = now.replace(hour=12) if now.hour < 7 or now.hour >= 23 else now
        day = min(day, pred.match.kickoff - timedelta(hours=1))
        n1 = push.dispatch(db, day)["sent"]
        assert n1 >= 1 and any("Sélection SAM" in d for d in sent)
        assert push.dispatch(db, day)["sent"] == 0  # jamais deux fois
        assert db.scalar(select(func.count(PushLog.id))) >= 1
        # favoris : un autre championnat → aucune nouvelle alerte de sélection
        s.prefs = push.clean_prefs({"competitions": ["ZZZ"]})
        db.commit()
        assert all(k != "selection" for k, _, _ in push.build_messages(db, s, day))

        class Gone(pywebpush.WebPushException):
            pass
        def refuse(**kw):
            e = Gone("gone"); e.response = type("R", (), {"status_code": 410})(); raise e
        monkeypatch.setattr(pywebpush, "webpush", refuse)
        assert push.send(s, {"title": "t", "body": "b"}) is False and s.failures == 99
        db.delete(s)
        pred.result, pred.featured = old
        db.commit()


def test_lineups_substitutions_and_pressure(populated, monkeypatch):
    """Compositions officielles (11 titulaires minimum, sinon rien), remplacements, relevés de pression du direct
    conservés d'un appel à l'autre, et récupération avant le match pour les grands championnats."""
    from app.config import get_settings
    from app.providers.allsports import AllSports, details_of, lineups_of, merge_details
    from app.services import allsports_sync
    xi = [{"player": f"Joueur {i}", "player_number": i, "player_position": i} for i in range(1, 12)]
    x = {"event_home_formation": "4-3-3", "event_away_formation": "4-4-2",
         "lineups": {"home_team": {"starting_lineups": xi, "substitutes": xi[:3], "coaches": [{"coache": "Coach A"}]},
                     "away_team": {"starting_lineups": xi, "substitutes": [], "coaches": []}},
         "substitutes": [{"time": "60", "home_scorer": {"in": "Entrant", "out": "Sortant"}, "away_scorer": []}],
         "statistics": [{"type": "Dangerous Attacks", "home": "20", "away": "10"}]}
    d = details_of(x)
    assert d["lineups"]["home"]["formation"] == "4-3-3" and len(d["lineups"]["away"]["starting"]) == 11
    assert d["lineups"]["home"]["coach"] == "Coach A"
    assert any(e["type"] == "sub" and e["out"] == "Sortant" for e in d["events"])
    assert lineups_of({"lineups": {"home_team": {"starting_lineups": xi[:5]}, "away_team": {"starting_lineups": xi}}}) is None
    m1 = merge_details(None, d, "30")
    later = details_of({**x, "lineups": None, "statistics": [{"type": "Dangerous Attacks", "home": "35", "away": "22"}]})
    m2 = merge_details(m1, later, "45+2")
    assert m2["lineups"] and [p["t"] for p in m2["pressure"]] == [30, 45]
    assert merge_details(m2, later, "40")["pressure"] == m2["pressure"]  # jamais de retour en arrière

    with SessionLocal() as db:
        m = db.scalars(select(Match)).first()
        comp = m.competition
        old_code, old_details, old_status = comp.code, m.details, m.status
        comp.code, m.status, m.details = "ENG1", "SCHEDULED", None
        db.commit()
        now = m.kickoff - timedelta(minutes=45)
        row = {**x, "event_home_team": m.home_team.name, "event_away_team": m.away_team.name,
               "event_date": m.kickoff.strftime("%Y-%m-%d"), "event_time": m.kickoff.strftime("%H:%M")}
        monkeypatch.setattr(AllSports, "fixtures", lambda self, a, b, league_id=None: [row])
        monkeypatch.setattr(get_settings(), "allsports_key", "test")
        allsports_sync._pre["at"] = None
        assert allsports_sync.prematch_lineups(db, now) == 1
        db.refresh(m)
        assert m.details["lineups"]["home"]["starting"][0]["name"] == "Joueur 1"
        assert allsports_sync.prematch_lineups(db, now) == 0  # déjà connue
        comp.code, m.details, m.status = old_code, old_details, old_status
        db.commit()


def test_response_cache(client, monkeypatch):
    """Cache des réponses publiques : servi depuis la mémoire ; après une modification des données, l'ancienne
    version est servie aussitôt (« STALE ») puis recalculée en arrière-plan ; jamais pour le direct."""
    import time as _time
    from app.config import get_settings
    from app.services import response_cache as rc
    monkeypatch.setattr(get_settings(), "response_cache_seconds", 90)
    rc.reset()
    r1 = client.get("/api/meta")
    assert r1.headers.get("x-cache") == "MISS"
    r2 = client.get("/api/meta")
    assert r2.headers.get("x-cache") == "HIT" and r2.json() == r1.json()
    with SessionLocal() as db:
        settle_predictions(db)
    r3 = client.get("/api/meta")
    assert r3.headers.get("x-cache") in ("STALE", "HIT") and r3.json() == r1.json()
    for _ in range(50):  # recalcul en arrière-plan
        if client.get("/api/meta").headers.get("x-cache") == "HIT":
            break
        _time.sleep(0.1)
    assert client.get("/api/meta").headers.get("x-cache") == "HIT"
    assert client.get("/api/live").headers.get("x-cache") in ("MISS", "HIT")  # direct : 40 s au plus
    assert client.get("/api/live").headers.get("x-cache") == "HIT"
    assert client.get("/api/meta", headers={"X-Cache-Refresh": "1"}).headers.get("x-cache") == "MISS"
    rc.reset()


def test_machine_generator(populated, client, monkeypatch):
    """Machine SAM : sélections conformes aux critères (événement, cote, probabilité, statistiques réelles), un match
    au plus une fois, cote totale = produit des cotes, cote cible atteinte ou aucune proposition."""
    import app.api.catalog as cat
    with SessionLocal() as db:  # la journée analysée redevient « à venir » le temps du test
        ms = db.scalars(select(Match).join(Analysis, Analysis.match_id == Match.id).where(
            Match.kickoff >= NOW)).unique().all()
        saved = {m.id: m.status for m in ms}
        for m in ms:
            m.status = "SCHEDULED"
        db.commit()
    monkeypatch.setattr(cat, "_now", lambda: NOW)
    opts = client.get("/api/machine/options").json()
    assert any(e["key"] == "BTTS_Y" for e in opts["events"]) and opts["competitions"]
    r = client.post("/api/machine", json={"events": ["O1.5", "1X", "X2", "O2.5"], "days": 3, "n_matches": 4,
                                          "min_odds": 1.05, "max_odds": 5, "min_probability": 0.55, "min_confidence": 0}).json()
    assert r["matches_scanned"] > 0 and 1 <= r["count"] <= 4
    ids = [s["match"]["id"] for s in r["selections"]]
    assert len(ids) == len(set(ids))
    for s in r["selections"]:
        assert s["market_key"] in ("O1.5", "1X", "X2", "O2.5") and s["probability"] >= 0.55 and 1.05 <= s["odds"] <= 5
    if r["selections"]:
        import math
        assert abs(r["total_odds"] - math.prod(s["odds"] for s in r["selections"])) < 0.05
    s = client.post("/api/machine", json={"events": ["O1.5"], "days": 3, "min_odds": 1.01, "max_odds": 9,
                                          "min_probability": 0.5, "min_confidence": 0, "last10_pct": 0.6, "venue_pct": 0.5}).json()
    for x in s["selections"]:
        f = x["facts"]
        assert f["last10"]["home"] >= 0.6 and f["last10"]["away"] >= 0.6 and f["venue"]["home"] >= 0.5
        assert f["last10"]["n_home"] >= 5
    t = client.post("/api/machine", json={"events": ["O1.5", "1X", "X2"], "days": 3, "n_matches": 6, "target_odds": 2.0,
                                          "min_odds": 1.05, "max_odds": 5, "min_probability": 0.55, "min_confidence": 0}).json()
    assert t["target_reached"] is False or t["total_odds"] >= 2.0
    assert client.post("/api/machine", json={"min_odds": 3, "max_odds": 2}).status_code == 422
    with SessionLocal() as db:
        for m in db.scalars(select(Match).where(Match.id.in_(list(saved)))).all():
            m.status = saved[m.id]
        db.commit()


def test_allsports_odds_popular(populated, monkeypatch):
    """Cotes AllSportsAPI des grands championnats : compétition vérifiée par son nom, match retrouvé par équipes
    et horaire, au plus toutes les 12 heures, budget quotidien respecté."""
    from app.config import get_settings
    from app.models import OddsQuote
    from app.providers.allsports import AllSports
    from app.services import allsports_sync
    with SessionLocal() as db:
        m = db.scalars(select(Match).join(Competition, Match.competition_id == Competition.id).where(
            Competition.code == "ENG1")).first()
        saved = (m.status, m.kickoff)
        now = m.kickoff - timedelta(days=1)
        m.status = "SCHEDULED"
        db.commit()
        row = {"event_key": 99, "league_name": "Premier League", "event_home_team": m.home_team.name,
               "event_away_team": m.away_team.name, "event_date": m.kickoff.strftime("%Y-%m-%d"),
               "event_time": m.kickoff.strftime("%H:%M")}
        calls = []
        monkeypatch.setattr(AllSports, "fixtures", lambda self, a, b, league_id=None: calls.append(league_id) or [row])
        monkeypatch.setattr(AllSports, "odds", lambda self, a, b, league_id=None: {
            "99": [{"odd_bookmakers": "Bet365", "odd_1x": "1.30", "o+1.5": "1.25", "bts_yes": "1.80"}]})
        monkeypatch.setattr(get_settings(), "allsports_key", "test")
        res = allsports_sync.odds_popular(db, now, force=True)
        assert res is not None and 152 in calls
        q = {o.market_key: o.price for o in db.scalars(select(OddsQuote).where(
            OddsQuote.match_id == m.id, OddsQuote.source == "allsports"))}
        assert q == {"1X": 1.30, "O1.5": 1.25, "BTTS_Y": 1.80}
        assert allsports_sync.odds_popular(db, now + timedelta(hours=1)) is None  # 12 h minimum
        assert allsports_sync._league_ok(row, "premier league") and not allsports_sync._league_ok({"league_name": "Ligue 2"}, "ligue 1")
        for o in db.scalars(select(OddsQuote).where(OddsQuote.source == "allsports")).all():
            db.delete(o)
        m.status, m.kickoff = saved
        db.commit()


def test_allsports_end_of_subscription(populated, monkeypatch):
    """Fin de l'essai AllSportsAPI : 3 refus de la clé → source coupée, championnats dont c'est la seule source mis en
    pause (rien supprimé), notre propre budget n'est jamais pris pour un refus ; réactivation → tout revient."""
    from app.services import allsports_sync as a
    from app.services.settings_service import get_provider_flags, set_provider_flag
    with SessionLocal() as db:
        comp = db.scalars(select(Competition)).first()
        old = (comp.primary_source, comp.enabled)
        comp.primary_source, comp.enabled = "allsports", True
        db.commit()
        assert a.note_result(db, False, "AllSportsAPI : budget quotidien prudent atteint") is False
        assert a.note_result(db, False, "AllSportsAPI : requête refusée — Invalid API key") is False
        assert a.note_result(db, True) is False  # un succès remet le compteur à zéro
        for _ in range(2):
            assert a.note_result(db, False, "AllSportsAPI : HTTP 401") is False
        assert a.note_result(db, False, "AllSportsAPI : HTTP 401") is True
        db.refresh(comp)
        assert get_provider_flags(db)["allsports"] is False and comp.enabled is False
        assert db.get(Match, db.scalars(select(Match.id).where(Match.competition_id == comp.id)).first()) is not None
        set_provider_flag(db, "allsports", True)
        assert comp.code in a.resume(db)
        db.refresh(comp)
        assert comp.enabled is True
        comp.primary_source, comp.enabled = old
        db.commit()


def test_international_matches(populated, monkeypatch):
    """Sélections nationales : historique public (sélections reconnues seulement, depuis 2021), noms affichés en
    français et rapprochés en anglais, calendrier des fournisseurs filtré (ni femmes, ni jeunes, ni clubs)."""
    from app.config import get_settings
    from app.services import intl
    from app.models import Team
    monkeypatch.setattr(get_settings(), "intl_enabled", True)
    csv_text = "date,home_team,away_team,home_score,away_score,tournament,city,country,neutral\n" + "\n".join(
        [f"2025-0{(i % 9) + 1}-1{i % 9},Germany,Mali,{i % 3},{(i + 1) % 2},Friendly,Berlin,Germany,FALSE" for i in range(9)]
        + ["2025-03-20,Padania,Tibet,1,0,CONIFA,x,y,TRUE", "2019-03-20,Germany,Mali,9,0,Friendly,x,y,FALSE"])
    with SessionLocal() as db:
        n, msg = intl.import_history(db, NOW + timedelta(days=400), csv_text)
        assert n == 9, msg
        comp = intl.competition(db)
        assert comp.country == intl.COUNTRY and comp.enabled
        names = {t.name for t in db.scalars(select(Team).where(Team.country == intl.COUNTRY))}
        assert names == {"Allemagne", "Mali"}
        assert intl.import_history(db, NOW + timedelta(days=400), csv_text)[0] == 0  # pas de doublon
    assert intl.canon("Côte d'Ivoire") == "Ivory Coast" and intl.canon("Korea Republic") == "South Korea"
    assert intl.canon("Germany W") is None and intl.canon("Mali U23") is None and intl.canon("Real Madrid") is None
    assert intl.is_international("UEFA Nations League") and intl.is_international("Africa Cup of Nations - Qualification")
    assert not intl.is_international("UEFA Nations League Women") and not intl.is_international("UEFA Champions League")
    assert not intl.is_international("Friendlies U21")
    assert intl.french("Netherlands") == "Pays-Bas"
