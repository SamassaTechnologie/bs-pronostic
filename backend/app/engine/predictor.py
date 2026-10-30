"""Orchestration du moteur : ajustement des modèles par championnat et analyse
complète d'un match (toutes les probabilités, confiance, facteurs, sélection)."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Hashable, Mapping, Optional

import numpy as np

from .calibration import PlattCalibrator, apply_calibration
from .confidence import DEFAULT_FAMILY_RELIABILITY, ConfidenceInputs, compute_confidence
from .explain import build_factors, explanation
from .features import TeamHistory, form_summary, h2h_matches, head_to_head, recent_market_rates
from .markets import (DISPLAY_MARKETS, card_probabilities, corner_probabilities, ft_probabilities,
                      ht_probabilities, score_matrix, top_scores, total_count_pmf)
from .selection import avoid_reasons, select_picks, selection_score, tier_of
from .team_model import TeamModel, fit_team_model
from .types import MatchData, OddsInfo

ENGINE_VERSION = "sam-dc-1.0"


@dataclass
class EngineParams:
    xi: float = 0.0019  # décroissance temporelle par jour (demi-vie ≈ 1 an, Dixon & Coles 1997)
    window_days: int = 730  # fenêtre d'historique utilisée
    prior_sd_goals: float = 0.35  # réglé par backtest (log loss hors échantillon)
    prior_sd_corners: float = 0.4
    prior_sd_cards: float = 0.3
    min_league_matches: int = 60
    min_team_matches: int = 6
    min_stat_matches: int = 60
    h2h_max_weight: float = 0.10  # poids maximal des confrontations directes (10 %)
    h2h_min_matches: int = 3


@dataclass
class LeagueModels:
    competition_id: Hashable
    as_of: datetime
    n_matches: int
    goals: Optional[TeamModel] = None
    ht_ratio: Optional[tuple[float, float]] = None
    corners: Optional[TeamModel] = None
    cards: Optional[TeamModel] = None
    reason: Optional[str] = None
    league_stats: dict = field(default_factory=dict)


def _weights(ms: list[MatchData], as_of: datetime, xi: float) -> np.ndarray:
    return np.array([math.exp(-xi * max((as_of - m.kickoff).total_seconds() / 86400.0, 0.0)) for m in ms])


def fit_league_models(competition_id: Hashable, matches: list[MatchData], as_of: datetime,
                      params: EngineParams = EngineParams(),
                      warm: Optional[LeagueModels] = None) -> LeagueModels:
    start = as_of - timedelta(days=params.window_days)
    hist = [m for m in matches if m.finished and start <= m.kickoff < as_of]
    lm = LeagueModels(competition_id, as_of, len(hist))
    if len(hist) < params.min_league_matches:
        lm.reason = (f"Données insuffisantes : {len(hist)} matchs terminés disponibles pour ce championnat "
                     f"(minimum {params.min_league_matches})")
        return lm
    w = _weights(hist, as_of, params.xi)
    lm.goals = fit_team_model(
        [m.home_id for m in hist], [m.away_id for m in hist], [m.hg for m in hist], [m.ag for m in hist], w,
        prior_sd=params.prior_sd_goals, dixon_coles=True, warm_start=warm.goals if warm else None)

    ht = [(m, wi) for m, wi in zip(hist, w) if m.hthg is not None and m.htag is not None]
    if len(ht) >= params.min_stat_matches:
        sh = sum(wi * m.hg for m, wi in ht)
        sa = sum(wi * m.ag for m, wi in ht)
        if sh > 0 and sa > 0:
            lm.ht_ratio = (sum(wi * m.hthg for m, wi in ht) / sh, sum(wi * m.htag for m, wi in ht) / sa)

    cm = [(m, wi) for m, wi in zip(hist, w) if m.total_corners is not None]
    if len(cm) >= params.min_stat_matches:
        lm.corners = fit_team_model(
            [m.home_id for m, _ in cm], [m.away_id for m, _ in cm], [m.hc for m, _ in cm],
            [m.ac for m, _ in cm], [wi for _, wi in cm], prior_sd=params.prior_sd_corners,
            warm_start=warm.corners if warm else None)

    km = [(m, wi) for m, wi in zip(hist, w) if m.total_cards is not None]
    if len(km) >= params.min_stat_matches:
        lm.cards = fit_team_model(
            [m.home_id for m, _ in km], [m.away_id for m, _ in km], [m.hy + m.hr for m, _ in km],
            [m.ay + m.ar for m, _ in km], [wi for _, wi in km], prior_sd=params.prior_sd_cards,
            warm_start=warm.cards if warm else None)

    n = len(hist)
    lm.league_stats = {
        "matches": n,
        "avg_goals": round(sum(m.hg + m.ag for m in hist) / n, 2),
        "home_win_rate": round(sum(1 for m in hist if m.hg > m.ag) / n, 3),
        "draw_rate": round(sum(1 for m in hist if m.hg == m.ag) / n, 3),
        "over25_rate": round(sum(1 for m in hist if m.hg + m.ag > 2.5) / n, 3),
        "btts_rate": round(sum(1 for m in hist if m.hg > 0 and m.ag > 0) / n, 3),
        "avg_corners": round(sum(m.total_corners for m, _ in cm) / len(cm), 2) if cm else None,
        "avg_cards": round(sum(m.total_cards for m, _ in km) / len(km), 2) if km else None,
        "home_advantage": round(math.exp(lm.goals.home), 3),
        "rho": round(lm.goals.rho, 4),
    }
    return lm


def raw_probabilities(lm: LeagueModels, home_id: Hashable, away_id: Hashable,
                      params: EngineParams = EngineParams(),
                      h2h: Optional[list[MatchData]] = None) -> Optional[dict]:
    """Probabilités brutes (non calibrées) + éléments intermédiaires. None si données insuffisantes."""
    g = lm.goals
    if g is None or not (g.has_team(home_id) and g.has_team(away_id)):
        return None
    if g.team_matches(home_id) < params.min_team_matches or g.team_matches(away_id) < params.min_team_matches:
        return None
    lam, mu = g.rates(home_id, away_id)
    h2h_factor = 1.0
    if h2h and len(h2h) >= params.h2h_min_matches:
        avg = sum(m.hg + m.ag for m in h2h) / len(h2h)
        ratio = avg / (lam + mu)
        weight = params.h2h_max_weight * min(len(h2h), 6) / 6
        h2h_factor = float(np.clip(1 + weight * (ratio - 1), 0.92, 1.08))
        lam *= h2h_factor
        mu *= h2h_factor
    mat = score_matrix(lam, mu, g.rho)
    raw = ft_probabilities(mat)
    out = {"raw": raw, "matrix": mat, "lam": lam, "mu": mu, "h2h_factor": h2h_factor,
           "ht": None, "corners": None, "cards": None}
    if lm.ht_ratio:
        lh, la = lam * lm.ht_ratio[0], mu * lm.ht_ratio[1]
        raw.update(ht_probabilities(lh, la))
        out["ht"] = (lh, la)
    for name, model, fn in (("corners", lm.corners, corner_probabilities), ("cards", lm.cards, card_probabilities)):
        if model is None or not (model.has_team(home_id) and model.has_team(away_id)):
            continue
        if min(model.team_matches(home_id), model.team_matches(away_id)) < params.min_team_matches:
            continue
        a, b = model.rates(home_id, away_id)
        raw.update(fn(total_count_pmf(a, b, model.dispersion)))
        out[name] = (a, b)
    return out


def implied_probabilities(odds: Mapping[str, OddsInfo]) -> dict[str, float]:
    """Probabilités implicites des cotes, marge du bookmaker retirée (normalisation)."""
    out: dict[str, float] = {}

    def price(k: str) -> Optional[float]:
        o = odds.get(k)
        return o.price if o and o.price and o.price > 1.0 else None

    def norm(keys: list[str], total: float = 1.0) -> None:
        ps = [price(k) for k in keys]
        if any(p is None for p in ps):
            return
        q = [1.0 / p for p in ps]
        s = sum(q) / total
        for k, x in zip(keys, q):
            out[k] = x / s

    norm(["1", "X", "2"])
    if all(k in out for k in ("1", "X", "2")):
        out["1X"] = out["1"] + out["X"]
        out["X2"] = out["X"] + out["2"]
        out["12"] = out["1"] + out["2"]
    else:
        norm(["1X", "X2", "12"], total=2.0)
    for line in ("0.5", "1.5", "2.5", "3.5", "4.5"):
        norm([f"O{line}", f"U{line}"])
        norm([f"HT_O{line}", f"HT_U{line}"])
    norm(["BTTS_Y", "BTTS_N"])
    norm(["HT_1", "HT_X", "HT_2"])
    for line in ("6.5", "7.5", "8.5", "9.5", "10.5", "11.5", "12.5"):
        norm([f"C_O{line}", f"C_U{line}"])
    for line in ("1.5", "2.5", "3.5", "4.5", "5.5", "6.5"):
        norm([f"K_O{line}", f"K_U{line}"])
    return out


@dataclass
class FixtureContext:
    match_id: Hashable
    competition_id: Hashable
    kickoff: datetime
    home_id: Hashable
    away_id: Hashable
    home_name: str
    away_name: str
    odds: dict = field(default_factory=dict)  # clé marché -> OddsInfo
    injuries: Optional[dict] = None  # {"home": [...], "away": [...]} ; None = source indisponible
    data_age_hours: Optional[float] = None
    late_season: bool = False
    standings: Optional[dict] = None  # {"home": {...}, "away": {...}, "teams": n}


UNAVAILABLE = {
    "halftime": "Données insuffisantes : scores à la mi-temps non disponibles pour ce championnat",
    "halftime_result": "Données insuffisantes : scores à la mi-temps non disponibles pour ce championnat",
    "corners": "Données insuffisantes : historique de corners indisponible ou trop court",
    "cards": "Données insuffisantes : historique de cartons indisponible ou trop court",
}


def analyze_fixture(lm: LeagueModels, fx: FixtureContext, history: TeamHistory,
                    calibrators: Mapping[str, PlattCalibrator], reliability: Mapping[str, float],
                    settings: Mapping, params: EngineParams = EngineParams()) -> dict:
    when = fx.kickoff
    home, away = fx.home_id, fx.away_id
    h_last = history.before(home, when, 10)
    a_last = history.before(away, when, 10)
    h2h_list = h2h_matches(history, home, away, when)
    payload: dict = {
        "engine_version": ENGINE_VERSION,
        "status": "insufficient",
        "reasons": [],
        "markets": [],
        "picks": [],
        "form": {
            "home": {"last5": form_summary(home, h_last[:5]), "last10": form_summary(home, h_last),
                     "venue10": form_summary(home, history.before(home, when, 10, venue="home"))},
            "away": {"last5": form_summary(away, a_last[:5]), "last10": form_summary(away, a_last),
                     "venue10": form_summary(away, history.before(away, when, 10, venue="away"))},
        },
        "h2h": head_to_head(history, home, away, when),
        "standings": fx.standings,
        "league": lm.league_stats,
    }
    n_home = lm.goals.team_matches(home) if lm.goals else 0
    n_away = lm.goals.team_matches(away) if lm.goals else 0
    injuries = fx.injuries
    inj_counts = None
    if injuries is not None:
        inj_counts = {"home": len(injuries.get("home") or []), "away": len(injuries.get("away") or [])}
    limits = ["xG non disponibles dans les sources actuelles : modèle fondé sur les buts réels."]
    if injuries is None:
        limits.append("Absences et blessures non disponibles (nécessite la clé API-Football).")
    limits.append("Motivation et enjeux non mesurés directement : seul le classement est indiqué.")
    limits.append("Compositions d'équipes non prises en compte.")
    payload["data_quality"] = {
        "league_matches": lm.n_matches, "home_matches": n_home, "away_matches": n_away,
        "halftime_available": bool(lm.ht_ratio), "corners_available": bool(lm.corners),
        "cards_available": bool(lm.cards), "odds_markets": sorted(fx.odds.keys()),
        "injuries_available": injuries is not None, "xg_available": False, "limits": limits,
    }
    payload["injuries"] = injuries

    if lm.goals is None:
        payload["reasons"].append(lm.reason or "Données insuffisantes")
    else:
        for name, n in ((fx.home_name, n_home), (fx.away_name, n_away)):
            if n < params.min_team_matches:
                payload["reasons"].append(
                    f"Données insuffisantes : {n} match(s) de {name} dans l'historique (minimum {params.min_team_matches})")
    rp = raw_probabilities(lm, home, away, params, h2h_list) if not payload["reasons"] else None
    if rp is None:
        if not payload["reasons"]:
            payload["reasons"].append("Données insuffisantes")
        payload["markets"] = [{"key": s.key, "label": s.label, "short": s.short, "family": s.family,
                               "group": s.group, "available": False, "probability": None,
                               "reason": "Données insuffisantes"} for s in DISPLAY_MARKETS]
        payload["avoid_reasons"] = avoid_reasons(payload, settings)
        return payload

    raw = rp["raw"]
    cal = apply_calibration(raw, calibrators)
    implied = implied_probabilities(fx.odds)
    last_h = history.last_played(home, when)
    last_a = history.last_played(away, when)
    days_h = (when - last_h).total_seconds() / 86400 if last_h else None
    days_a = (when - last_a).total_seconds() / 86400 if last_a else None
    inj_total = (inj_counts["home"] + inj_counts["away"]) if inj_counts else None

    markets = []
    for spec in DISPLAY_MARKETS:
        key = spec.key
        base = {"key": key, "label": spec.label, "short": spec.short, "family": spec.family, "group": spec.group}
        if key not in cal:
            markets.append({**base, "available": False, "probability": None,
                            "reason": UNAVAILABLE.get(spec.family, "Données insuffisantes")})
            continue
        p = float(np.clip(cal[key], 0.001, 0.999))
        model_for_volume = {"corners": lm.corners, "cards": lm.cards}.get(spec.family, lm.goals)
        nh = model_for_volume.team_matches(home)
        na = model_for_volume.team_matches(away)
        rates = recent_market_rates(key, history, home, away, when, 10)
        o: Optional[OddsInfo] = fx.odds.get(key)
        pm = implied.get(key)
        conf = compute_confidence(ConfidenceInputs(
            n_home=nh, n_away=na, days_since_home_last=days_h, days_since_away_last=days_a,
            data_age_hours=fx.data_age_hours, p_model=p, p_recent=rates["combined"], n_recent=rates["n"],
            model_reliability=float(reliability.get(key, DEFAULT_FAMILY_RELIABILITY[spec.family])),
            p_market=pm, injuries_count=inj_total, late_season=fx.late_season))
        tier = tier_of(p, settings)
        edge = (p * o.price - 1.0) if o else None
        ctx = {"home_name": fx.home_name, "away_name": fx.away_name, "home_id": home,
               "lam": rp["lam"], "mu": rp["mu"], "ht": rp["ht"], "exp_corners": rp["corners"],
               "exp_cards": rp["cards"], "rates": rates, "p_market": pm, "odds": o.price if o else None,
               "edge": edge, "h2h_matches": h2h_list, "n_home": nh, "n_away": na, "injuries": inj_counts}
        fav, unf = build_factors(key, p, ctx)
        m = {**base, "available": True, "probability": round(p, 4), "raw_probability": round(float(raw[key]), 4),
             "tier": tier, "confidence": conf,
             "odds": round(o.price, 3) if o else None, "bookmaker": o.bookmaker if o else None,
             "odds_source": o.source if o else None,
             "implied_probability": round(pm, 4) if pm is not None else None,
             "edge": round(edge, 4) if edge is not None else None, "fair_odds": round(1 / p, 3),
             "recent": {k: (round(v, 3) if isinstance(v, float) else v) for k, v in rates.items()},
             "explanation": explanation(key, p, tier, conf, ctx),
             "factors_for": fav, "factors_against": unf}
        m["score"] = selection_score(m)
        markets.append(m)

    payload.update({
        "status": "ok",
        "markets": markets,
        "expected_goals": {"home": round(rp["lam"], 3), "away": round(rp["mu"], 3)},
        "expected_ht_goals": ({"home": round(rp["ht"][0], 3), "away": round(rp["ht"][1], 3)}
                              if rp["ht"] else None),
        "expected_corners": ({"home": round(rp["corners"][0], 2), "away": round(rp["corners"][1], 2)}
                             if rp["corners"] else None),
        "expected_cards": ({"home": round(rp["cards"][0], 2), "away": round(rp["cards"][1], 2)}
                           if rp["cards"] else None),
        "h2h_factor": round(rp["h2h_factor"], 4),
        "top_scores": top_scores(rp["matrix"]),
    })
    payload["picks"] = select_picks(markets, settings)
    payload["avoid_reasons"] = avoid_reasons(payload, settings)
    avail = [m for m in markets if m["available"]]
    payload["match_confidence"] = max((m["confidence"]["score"] for m in avail), default=0)
    return payload
