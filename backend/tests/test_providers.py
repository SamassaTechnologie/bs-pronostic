"""Tests des connecteurs : analyse des formats documentés (aucun appel réseau)."""
from datetime import datetime, timezone

import pytest

from app.providers.api_football import ApiFootball, map_bet
from app.providers.base import ProviderError
from app.providers.football_data_co_uk import parse_extra_csv, parse_kickoff, parse_main_csv, season_code
from app.providers.football_data_org import FootballDataOrg
from app.providers.names import best_match, normalize_team, similarity

UTC = timezone.utc

FIXTURES_CSV = """Div,Date,Time,HomeTeam,AwayTeam,FTHG,FTAG,FTR,AvgH,AvgD,AvgA,B365H,B365D,B365A,Avg>2.5,Avg<2.5
E0,07/11/2026,15:00,Arsenal,Everton,,,,1.45,4.6,7.2,1.44,4.75,7.0,1.75,2.10
F1,08/11/2026,20:45,Paris SG,Lyon,,,,1.40,5.0,7.0,,,,1.55,2.45
"""

EXTRA_CSV = """Country,League,Season,Date,Time,Home,Away,HG,AG,Res,PSCH,PSCD,PSCA,AvgCH,AvgCD,AvgCA
Brazil,Serie A,2025,10/11/2025,23:00,Flamengo RJ,Palmeiras,2,1,H,2.1,3.3,3.8,2.0,3.2,3.7
Brazil,Serie A,2019,10/11/2019,23:00,Santos,Gremio,1,1,D,2.1,3.3,3.8,2.0,3.2,3.7
"""


def test_season_code_and_time_conversion():
    assert season_code(2026) == "2627"
    assert season_code(1999) == "9900"
    # 20:00 heure d'été britannique = 19:00 UTC ; 15:00 en hiver = 15:00 UTC
    assert parse_kickoff("15/08/2025", "20:00") == datetime(2025, 8, 15, 19, 0, tzinfo=UTC)
    assert parse_kickoff("07/11/26", "15:00") == datetime(2026, 11, 7, 15, 0, tzinfo=UTC)


def test_parse_real_results_csv(e0_csv):
    recs = parse_main_csv(e0_csv, {"E0": "ENG1"}, with_odds=False, season="2025-2026")
    assert len(recs) == 380
    first = recs[0]
    assert (first.home_name, first.away_name, first.home_goals, first.away_goals) == ("Liverpool", "Bournemouth", 4, 2)
    assert first.status == "FINISHED" and first.home_corners == 6 and first.away_yellow == 2
    assert all(r.odds == [] for r in recs)  # pas de cotes stockées pour les matchs terminés


def test_parse_fixtures_with_odds():
    recs = parse_main_csv(FIXTURES_CSV, {"E0": "ENG1"}, with_odds=True)
    assert len(recs) == 1  # F1 ignorée car non activée
    r = recs[0]
    assert r.status == "SCHEDULED" and r.home_goals is None
    keys = {(o.market_key, o.bookmaker) for o in r.odds}
    assert ("1", "Moyenne") in keys and ("X", "Bet365") in keys and ("O2.5", "Moyenne") in keys
    assert next(o.price for o in r.odds if o.market_key == "1" and o.bookmaker == "Moyenne") == 1.45


def test_parse_extra_league_csv():
    recs = parse_extra_csv(EXTRA_CSV, {"Brazil": "BRA1"}, with_odds=False, min_season_year=2023)
    assert len(recs) == 1
    assert recs[0].home_goals == 2 and recs[0].ht_home_goals is None and recs[0].home_corners is None


API_FIXTURE = {
    "fixture": {"id": 1208021, "referee": "M. Oliver", "date": "2026-11-07T15:00:00+00:00",
                "status": {"short": "FT"}},
    "league": {"id": 39, "season": 2026},
    "teams": {"home": {"id": 42, "name": "Arsenal"}, "away": {"id": 45, "name": "Everton"}},
    "goals": {"home": 3, "away": 1},
    "score": {"halftime": {"home": 1, "away": 0}, "fulltime": {"home": 2, "away": 1},
              "extratime": {"home": 1, "away": 0}},
}


def test_api_football_records_and_bets():
    rec = ApiFootball.to_record(API_FIXTURE, "ENG1")
    # le score à 90 minutes (fulltime) est utilisé, pas le score après prolongation
    assert rec.status == "FINISHED" and (rec.home_goals, rec.away_goals) == (2, 1)
    assert rec.ht_home_goals == 1 and rec.fixture_ext_id == 1208021 and rec.home_ext_id == 42
    sched = ApiFootball.to_record({**API_FIXTURE, "fixture": {**API_FIXTURE["fixture"], "status": {"short": "NS"}}},
                                  "ENG1")
    assert sched.status == "SCHEDULED" and sched.home_goals is None
    assert map_bet("Match Winner", "Home") == "1"
    assert map_bet("Double Chance", "Draw/Away") == "X2"
    assert map_bet("Goals Over/Under", "Over 2.5") == "O2.5"
    assert map_bet("Goals Over/Under", "Under 3") is None
    assert map_bet("Goals Over/Under First Half", "Under 1.5") == "HT_U1.5"
    assert map_bet("Both Teams Score", "No") == "BTTS_N"
    assert map_bet("Corners Over Under", "Over 9.5") == "C_O9.5"
    assert map_bet("Cards Over/Under", "Over 4.5") == "K_O4.5"
    assert map_bet("Exact Score", "1:0") is None


def test_api_football_errors_are_surfaced(monkeypatch):
    af = ApiFootball()
    af.settings = af.settings.model_copy(update={"api_football_key": "cle-test"})

    class Resp:
        status_code = 200

        @staticmethod
        def json():
            return {"errors": {"plan": "Free plans do not have access to this season"}, "response": []}

    monkeypatch.setattr(af, "_request", lambda *a, **k: Resp())
    with pytest.raises(ProviderError, match="Free plans"):
        af.fixtures_by_league(39, 2026)


def test_api_football_statistics(monkeypatch):
    af = ApiFootball()
    af.settings = af.settings.model_copy(update={"api_football_key": "cle-test"})
    payload = {"errors": [], "response": [
        {"team": {"id": 42}, "statistics": [{"type": "Corner Kicks", "value": 7}, {"type": "Yellow Cards", "value": 2},
                                            {"type": "Red Cards", "value": None}, {"type": "expected_goals", "value": "1.84"}]},
        {"team": {"id": 45}, "statistics": [{"type": "Corner Kicks", "value": 3}, {"type": "Yellow Cards", "value": 4},
                                            {"type": "Red Cards", "value": 1}]}]}

    class Resp:
        status_code = 200

        @staticmethod
        def json():
            return payload

    monkeypatch.setattr(af, "_request", lambda *a, **k: Resp())
    stats = af.fixture_statistics(1)
    assert stats[42]["corners"] == 7 and stats[42]["red"] == 0 and stats[42]["xg"] == pytest.approx(1.84)
    assert stats[45]["yellow"] == 4 and stats[45]["red"] == 1


def test_football_data_org_record():
    m = {"id": 5501, "utcDate": "2026-11-04T20:00:00Z", "status": "FINISHED",
         "homeTeam": {"id": 81, "name": "FC Barcelona"}, "awayTeam": {"id": 5, "name": "FC Bayern München"},
         "score": {"fullTime": {"home": 3, "away": 3}, "regularTime": {"home": 2, "away": 2},
                   "halfTime": {"home": 1, "away": 0}},
         "season": {"startDate": "2026-08-01", "endDate": "2027-05-31"}, "referees": []}
    rec = FootballDataOrg.to_record(m, "UCL")
    assert rec.status == "FINISHED" and (rec.home_goals, rec.away_goals) == (2, 2) and rec.season == "2026-2027"


def test_team_name_matching():
    assert normalize_team("Man United") == normalize_team("Manchester United")
    assert normalize_team("Nott'm Forest") == normalize_team("Nottingham Forest")
    assert normalize_team("Paris SG") == normalize_team("Paris Saint Germain")
    assert similarity("Bayern Munich", "Bayern München") >= 90
    assert best_match("Wolves", ["Wolverhampton Wanderers", "West Ham"]) == "Wolverhampton Wanderers"
    assert best_match("Arsenal", ["Chelsea", "Everton"]) is None
