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


def test_featured_selection(populated, client):
    with SessionLocal() as db:
        feats = db.scalars(select(Prediction).where(Prediction.featured.is_(True))).all()
        per_day = {}
        for p in feats:
            assert p.probability >= 0.75 and p.confidence >= 70 and p.featured_at is not None
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

    # Règlement : la journée se joue, résultats réels remis en place.
    with SessionLocal() as db:
        for mid, (status, hg, ag) in saved.items():
            m = db.get(Match, mid)
            m.status, m.home_goals, m.away_goals = status, hg, ag
        db.commit()
        res = game.settle_bets(db, NOW + timedelta(days=5))
        bets = db.scalars(select(Bet).where(Bet.member_id == "joueur-1")).all()
        assert all(x.status != "pending" for x in bets) and sum(res.values()) == 3
        w = db.get(Wallet, "joueur-1")
        assert w.balance == before - 200 + sum(x.payout for x in bets)
        rk = game.ranking(db, "joueur-1", NOW + timedelta(days=5))
        assert rk["me"] and rk["me"]["name"] == "Awa"
