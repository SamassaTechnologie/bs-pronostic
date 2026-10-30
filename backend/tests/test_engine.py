"""Tests du moteur statistique.

Les données utilisées ici sont SYNTHÉTIQUES (générées par simulation dans les
tests) : elles servent uniquement à vérifier les propriétés mathématiques du
moteur et ne sont jamais présentées comme des données réelles.
"""
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest
from scipy.optimize import check_grad

from app.engine.calibration import (apply_calibration, brier_score, fit_platt, log_loss)
from app.engine.combos import Leg, MatchModel, evaluate_combo, generate_combos
from app.engine.confidence import ConfidenceInputs, compute_confidence
from app.engine.features import TeamHistory, form_summary, standings
from app.engine.markets import (DISPLAY_KEYS, evaluate_market, ft_probabilities, joint_ft_probability,
                                score_matrix, total_count_pmf)
from app.engine.predictor import EngineParams, FixtureContext, analyze_fixture, fit_league_models
from app.engine.selection import DEFAULT_SETTINGS, eligible, select_picks, tier_of
from app.engine.team_model import fit_team_model, make_objective
from app.engine.types import MatchData, OddsInfo

UTC = timezone.utc


def simulate_league(n_teams=12, rounds=4, seed=0, start=datetime(2024, 8, 1, tzinfo=UTC), with_stats=True):
    """Ligue simulée (Poisson) avec paramètres connus — usage test uniquement."""
    rng = np.random.default_rng(seed)
    att = rng.normal(0, 0.3, n_teams)
    att -= att.mean()
    de = rng.normal(0, 0.3, n_teams)
    de -= de.mean()
    home = 0.25
    c = np.log(1.2)
    matches = []
    day = 0
    mid = 0
    for _ in range(rounds):
        for i in range(n_teams):
            for j in range(n_teams):
                if i == j:
                    continue
                lam = np.exp(c + home + att[i] - de[j])
                mu = np.exp(c + att[j] - de[i])
                hg, ag = int(rng.poisson(lam)), int(rng.poisson(mu))
                mid += 1
                kw = {}
                if with_stats:
                    kw = dict(hthg=int(rng.binomial(hg, 0.45)), htag=int(rng.binomial(ag, 0.45)),
                              hc=int(rng.poisson(5.5)), ac=int(rng.poisson(4.5)),
                              hy=int(rng.poisson(1.8)), ay=int(rng.poisson(2.0)), hr=0, ar=int(rng.random() < 0.05))
                matches.append(MatchData(id=mid, competition_id="SIM", kickoff=start + timedelta(hours=6 * day),
                                         home_id=f"T{i}", away_id=f"T{j}", hg=hg, ag=ag, **kw))
                day += 1
    return matches, att, de, home


def test_gradient_is_correct():
    rng = np.random.default_rng(1)
    n, m = 6, 80
    hi = rng.integers(0, n, m)
    ai = (hi + rng.integers(1, n, m)) % n
    yh = rng.poisson(1.4, m).astype(float)
    ya = rng.poisson(1.1, m).astype(float)
    w = rng.uniform(0.3, 1.0, m)
    for dc in (False, True):
        obj, n_params = make_objective(hi, ai, yh, ya, w, n, 4.0, dc)
        x0 = rng.normal(0, 0.1, n_params)
        if dc:
            x0[-1] = -0.05
        err = check_grad(lambda x: obj(x)[0], lambda x: obj(x)[1], x0)
        assert err < 1e-3, err


def test_fit_recovers_known_strengths():
    matches, att, de, home = simulate_league(n_teams=12, rounds=6, seed=3, with_stats=False)
    w = np.ones(len(matches))
    model = fit_team_model([m.home_id for m in matches], [m.away_id for m in matches],
                           [m.hg for m in matches], [m.ag for m in matches], w, prior_sd=1.0, dixon_coles=True)
    est_att = np.array([model.off[model.index[f"T{i}"]] for i in range(12)])
    est_de = np.array([model.deff[model.index[f"T{i}"]] for i in range(12)])
    assert np.corrcoef(att, est_att)[0, 1] > 0.85
    assert np.corrcoef(de, est_de)[0, 1] > 0.85
    assert abs(model.home - home) < 0.12
    assert model.converged


def test_score_matrix_markets_are_coherent():
    m = score_matrix(1.6, 1.1, -0.08)
    assert abs(m.sum() - 1) < 1e-9
    p = ft_probabilities(m)
    assert abs(p["1"] + p["X"] + p["2"] - 1) < 1e-9
    assert p["O0.5"] >= p["O1.5"] >= p["O2.5"] >= p["O3.5"]
    assert abs(p["U2.5"] + p["O2.5"] - 1) < 1e-12
    assert abs(p["1X"] - (p["1"] + p["X"])) < 1e-12
    assert abs(p["BTTS_Y"] + p["BTTS_N"] - 1) < 1e-12


def test_dixon_coles_adjusts_low_scores():
    base = score_matrix(1.3, 1.0, 0.0)
    dc = score_matrix(1.3, 1.0, -0.1)
    assert dc[0, 0] > base[0, 0] and dc[1, 1] > base[1, 1]
    assert dc[1, 0] < base[1, 0] and dc[0, 1] < base[0, 1]


def test_total_count_distribution():
    pmf = total_count_pmf(5.5, 4.5, 1.2)
    assert abs(pmf.sum() - 1) < 1e-9
    mean = (np.arange(len(pmf)) * pmf).sum()
    assert abs(mean - 10.0) < 0.05


def test_evaluate_market():
    m = MatchData(1, "C", datetime(2025, 1, 1, tzinfo=UTC), "A", "B", hg=2, ag=1, hthg=0, htag=1,
                  hc=6, ac=3, hy=2, ay=1, hr=0, ar=1)
    assert evaluate_market("1", m) is True
    assert evaluate_market("X2", m) is False
    assert evaluate_market("O2.5", m) is True
    assert evaluate_market("U3.5", m) is True
    assert evaluate_market("BTTS_Y", m) is True
    assert evaluate_market("HT_2", m) is True
    assert evaluate_market("HT_U1.5", m) is True
    assert evaluate_market("C_O8.5", m) is True
    assert evaluate_market("C_U10.5", m) is True
    assert evaluate_market("K_O3.5", m) is True  # 2 + 1 + 0 + 1 = 4
    no_stats = MatchData(2, "C", datetime(2025, 1, 1, tzinfo=UTC), "A", "B", hg=0, ag=0)
    assert evaluate_market("C_O8.5", no_stats) is None
    assert evaluate_market("HT_O0.5", no_stats) is None


def test_joint_probability_is_not_naive_product():
    m = score_matrix(1.7, 0.9, -0.05)
    p = ft_probabilities(m)
    joint = joint_ft_probability(["1", "O2.5"], m)
    assert joint < min(p["1"], p["O2.5"])
    assert abs(joint - p["1"] * p["O2.5"]) > 1e-3  # dépendance réelle
    assert abs(joint_ft_probability(["O1.5", "O2.5"], m) - p["O2.5"]) < 1e-12


def test_calibration_keeps_coherence():
    raw = ft_probabilities(score_matrix(1.5, 1.2, -0.05))
    cals = {k: fit_platt([0.2, 0.4, 0.6, 0.8] * 50, [0, 0, 1, 1] * 50) for k in ("1", "X", "2", "O2.5", "O1.5")}
    out = apply_calibration(raw, cals)
    assert abs(out["1"] + out["X"] + out["2"] - 1) < 1e-9
    assert out["O1.5"] >= out["O2.5"]
    assert abs(out["U2.5"] + out["O2.5"] - 1) < 1e-12
    ident = apply_calibration(raw, {})
    assert all(abs(ident[k] - raw[k]) < 1e-12 for k in raw)


def test_platt_improves_miscalibrated_predictions():
    rng = np.random.default_rng(5)
    true = rng.uniform(0.2, 0.8, 4000)
    y = (rng.random(4000) < true).astype(float)
    overconf = np.clip(0.5 + (true - 0.5) * 1.6, 0.01, 0.99)  # probabilités trop extrêmes
    cal = fit_platt(overconf, y)
    fixed = np.array([cal(p) for p in overconf])
    assert log_loss(fixed, y) < log_loss(overconf, y)
    assert brier_score(fixed, y) <= brier_score(overconf, y)
    assert cal.a < 1.0  # contraction vers 50 %


def test_combo_same_match_uses_joint_probability():
    m = score_matrix(1.8, 0.8, -0.05)
    raw = ft_probabilities(m)
    legs = [Leg(1, "1", "1", raw["1"], 70, odds=1.6, raw_probability=raw["1"], match_label="A – B"),
            Leg(1, "O1.5", "+1,5", raw["O1.5"], 70, odds=1.3, raw_probability=raw["O1.5"], match_label="A – B")]
    res = evaluate_combo(legs, {1: MatchModel(matrix=m, raw=raw)})
    assert res["valid"]
    assert abs(res["probability"] - joint_ft_probability(["1", "O1.5"], m)) < 1e-3
    assert res["total_odds"] is None  # pas de multiplication des cotes intra-match
    bad = evaluate_combo([legs[0], Leg(1, "C_O8.5", "corners", 0.7, 70)], {1: MatchModel(matrix=m, raw=raw)})
    assert not bad["valid"]


def test_combo_independent_matches():
    legs = [Leg(i, "1X", "1X", 0.8, 70, odds=1.3, match_label=f"M{i}") for i in range(3)]
    res = evaluate_combo(legs, {})
    assert abs(res["probability"] - 0.8 ** 3) < 1e-9
    assert res["total_odds"] == round(1.3 ** 3, 2)
    assert res["independent"]
    combos = generate_combos(legs + [Leg(9, "O1.5", "+1,5", 0.75, 80, odds=1.35)], 3)
    assert combos and all(len({leg["match_id"] for leg in c["legs"]}) == 3 for c in combos)


def test_confidence_reacts_to_data_volume_and_market():
    common = dict(days_since_home_last=7, days_since_away_last=7, data_age_hours=2, p_model=0.8,
                  p_recent=0.8, n_recent=20, model_reliability=0.8)
    strong = compute_confidence(ConfidenceInputs(n_home=40, n_away=40, p_market=0.79, **common))
    weak = compute_confidence(ConfidenceInputs(n_home=7, n_away=40, p_market=0.55, **common))
    assert strong["score"] > weak["score"]
    assert strong["level"] == "Élevée"
    assert 0 <= weak["score"] <= 100


def test_tiers_and_selection_rules():
    s = DEFAULT_SETTINGS
    assert tier_of(0.86, s) == "A" and tier_of(0.80, s) == "B" and tier_of(0.72, s) == "C" and tier_of(0.6, s) == "D"
    conf = {"score": 70, "level": "Élevée"}
    trivial = {"key": "O0.5", "group": "buts", "available": True, "probability": 0.95, "confidence": conf}
    assert not eligible(trivial, s)  # cote juste 1,05 < 1,10
    a = {"key": "O1.5", "group": "buts", "available": True, "probability": 0.8, "confidence": conf}
    b = {"key": "U3.5", "group": "buts", "available": True, "probability": 0.75, "confidence": conf}
    c = {"key": "1X", "group": "resultat", "available": True, "probability": 0.82, "confidence": conf}
    assert select_picks([a, b, c], s) == ["1X", "O1.5"]


def test_analyze_fixture_insufficient_data():
    matches, *_ = simulate_league(n_teams=6, rounds=1, seed=2)  # 30 matchs < 60
    when = matches[-1].kickoff + timedelta(days=1)
    lm = fit_league_models("SIM", matches, when)
    fx = FixtureContext(1, "SIM", when, "T0", "T1", "Équipe 0", "Équipe 1")
    out = analyze_fixture(lm, fx, TeamHistory(matches), {}, {}, DEFAULT_SETTINGS)
    assert out["status"] == "insufficient"
    assert all(not m["available"] and m["reason"].startswith("Données insuffisantes") for m in out["markets"])
    assert out["picks"] == []


def test_analyze_fixture_full():
    matches, *_ = simulate_league(n_teams=12, rounds=4, seed=7)
    when = matches[-1].kickoff + timedelta(days=2)
    lm = fit_league_models("SIM", matches, when, EngineParams())
    assert lm.goals and lm.corners and lm.cards and lm.ht_ratio
    odds = {"1": OddsInfo(2.0, "avg", "test"), "X": OddsInfo(3.4, "avg", "test"), "2": OddsInfo(3.9, "avg", "test")}
    fx = FixtureContext(99, "SIM", when, "T0", "T5", "Équipe 0", "Équipe 5", odds=odds, data_age_hours=1)
    out = analyze_fixture(lm, fx, TeamHistory(matches), {}, {}, DEFAULT_SETTINGS)
    assert out["status"] == "ok"
    keys = [m["key"] for m in out["markets"]]
    assert keys == DISPLAY_KEYS
    for m in out["markets"]:
        assert m["available"]
        assert 0 < m["probability"] < 1
        assert m["tier"] in "ABCD"
        assert 0 <= m["confidence"]["score"] <= 100
        assert m["explanation"]
    one = next(m for m in out["markets"] if m["key"] == "1")
    assert one["odds"] == 2.0 and one["implied_probability"] is not None and one["edge"] is not None
    assert set(out["picks"]) <= set(keys)
    assert len(out["top_scores"]) == 6


def test_form_and_standings():
    matches, *_ = simulate_league(n_teams=6, rounds=2, seed=4)
    hist = TeamHistory(matches)
    when = matches[-1].kickoff + timedelta(days=1)
    f = form_summary("T0", hist.before("T0", when, 5))
    assert f["played"] == 5 and len(f["sequence"]) == 5
    table = standings(matches)
    assert len(table) == 6 and table[0]["position"] == 1
    assert sum(r["played"] for r in table) == 2 * len(matches)
