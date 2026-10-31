"""API publique (lecture seule) consommée par le frontend."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from ..config import get_settings
from ..engine.combos import Leg, MatchModel, evaluate_combo, generate_combos
from ..engine.value import naive_equivalent, reference_odds, short_equivalent, target_combos
from ..engine.markets import FAMILY_LABELS, MARKET_BY_KEY, DISPLAY_MARKETS, score_matrix
from ..engine.predictor import ENGINE_VERSION
from ..models import Analysis, Competition, Match, OddsQuote, Prediction, SyncRun
from ..providers.registry import provider_status
from ..services.analysis import load_calibration, match_summary
from ..services.performance import performance, prediction_row
from ..services.settings_service import get_selection_settings
from .deps import get_db

router = APIRouter(prefix="/api", tags=["public"])
UTC = timezone.utc

DISCLAIMER = ("Pronostics statistiques fournis à titre informatif : aucune garantie de gain. "
              "Les paris comportent un risque de perte. Interdit aux mineurs. Jouez de manière responsable.")


def _tz(name: Optional[str]) -> ZoneInfo:
    try:
        return ZoneInfo(name or get_settings().default_timezone)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo(get_settings().default_timezone)


def _now() -> datetime:
    return datetime.now(UTC)


def _day_range(day: date, tz: ZoneInfo) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time(0, 0), tzinfo=tz).astimezone(UTC)
    return start, start + timedelta(days=1)


def pick_card(payload: dict, mk: dict) -> dict:
    return {
        "match": payload.get("match"),
        "market_key": mk["key"], "label": mk["label"], "short": mk.get("short"), "family": mk["family"],
        "family_label": FAMILY_LABELS.get(mk["family"], mk["family"]),
        "probability": mk["probability"], "tier": mk["tier"],
        "confidence": {"score": mk["confidence"]["score"], "level": mk["confidence"]["level"]},
        "odds": mk.get("odds"), "bookmaker": mk.get("bookmaker"), "implied_probability": mk.get("implied_probability"),
        "edge": mk.get("edge"), "fair_odds": mk.get("fair_odds"), "explanation": mk.get("explanation"),
        "factors_for": mk.get("factors_for", []), "factors_against": mk.get("factors_against", []),
        "score": mk.get("score"), "is_pick": mk["key"] in (payload.get("picks") or []),
        "model_probability": mk.get("model_probability"), "consensus": bool(mk.get("consensus")),
    }


def _featured_keys(db: Session, since: datetime) -> set:
    return {(p.match_id, p.market_key) for p in db.scalars(select(Prediction).join(
        Match, Prediction.match_id == Match.id).where(Prediction.featured.is_(True), Match.kickoff >= since)).unique()}


def _value_keys(db: Session, since: datetime) -> set:
    return {(p.match_id, p.market_key) for p in db.scalars(select(Prediction).join(
        Match, Prediction.match_id == Match.id).where(Prediction.value_pick.is_(True), Match.kickoff >= since)).unique()}


def _value_card(payload: dict, mk: dict) -> dict:
    c = pick_card(payload, mk)
    odds, real = reference_odds(mk)
    c["reference_odds"] = round(odds, 2)
    c["bookmaker_odds"] = real
    c["value_pick"] = True
    return c


def _target_legs(analyses: list, s: dict, now: datetime, competition_ids: Optional[list[int]] = None) -> list[Leg]:
    """Sélections candidates pour les combinés à cote cible : tous les marchés solides (pas seulement
    les pronostics retenus), hors matchs à éviter."""
    legs = []
    for a in analyses:
        p = a.payload
        if a.match.kickoff <= now + timedelta(minutes=10) or p.get("status") != "ok" or p.get("avoid_reasons"):
            continue
        if competition_ids and a.match.competition_id not in competition_ids:
            continue
        for mk in p.get("markets", []):
            if not mk.get("available") or mk["key"] in ("X", "HT_X", "HT_1", "HT_2"):
                continue
            if mk["key"] not in s["enabled_markets"]:
                continue
            pm = mk.get("model_probability")
            if mk.get("implied_probability") is not None and pm is not None and \
                    abs(float(pm) - float(mk["probability"])) > float(s["value_max_disagreement"]):
                continue
            legs.append(_leg(p, mk))
    return legs


def _upcoming_analyses(db: Session, start: datetime, end: datetime) -> list[Analysis]:
    return db.scalars(select(Analysis).join(Match, Analysis.match_id == Match.id).where(
        Match.kickoff >= start, Match.kickoff < end).order_by(Match.kickoff)).unique().all()


# ---------------------------------------------------------------------------

@router.get("/health")
def health(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
        db_ok = "ok"
    except Exception as exc:  # pragma: no cover
        db_ok = f"erreur : {exc.__class__.__name__}"
    return {"status": "ok", "app": get_settings().app_name, "engine": ENGINE_VERSION, "database": db_ok,
            "time": _now().isoformat()}


@router.get("/meta")
def meta(db: Session = Depends(get_db)):
    s = get_selection_settings(db)
    cal = load_calibration(db)
    oos = cal.get("out_of_sample") or {}
    last_sync = db.scalar(select(func.max(SyncRun.finished_at)).where(SyncRun.status == "ok",
                                                                      SyncRun.provider != "moteur"))
    last_analysis = db.scalar(select(func.max(Analysis.computed_at)))
    comps = db.scalars(select(Competition).where(Competition.enabled.is_(True)).order_by(
        Competition.country, Competition.name)).all()
    return {
        "app": {"name": get_settings().app_name, "slogan": get_settings().slogan, "engine": ENGINE_VERSION},
        "last_sync": last_sync.isoformat() if last_sync else None,
        "last_analysis": last_analysis.isoformat() if last_analysis else None,
        "providers": provider_status(db),
        "competitions": [{"id": c.id, "code": c.code, "name": c.name, "country": c.country} for c in comps],
        "markets": [{"key": m.key, "label": m.label, "short": m.short, "family": m.family,
                     "family_label": FAMILY_LABELS[m.family]} for m in DISPLAY_MARKETS],
        "settings": {k: s[k] for k in ("tier_a", "tier_b", "tier_c", "min_probability", "min_confidence",
                                       "min_fair_odds", "days_ahead")},
        "calibration": {"source": cal.get("source"), "generated_at": cal.get("generated_at"),
                        "n_matches": cal.get("n_matches"), "period": cal.get("period"),
                        "divisions": cal.get("divisions"), "tiers": oos.get("tiers"),
                        "market_benchmark": oos.get("market_benchmark")},
        "default_timezone": get_settings().default_timezone,
        "disclaimer": DISCLAIMER,
    }


@router.get("/dashboard")
def dashboard(tz: Optional[str] = None, db: Session = Depends(get_db)):
    zone = _tz(tz)
    s = get_selection_settings(db)
    now = _now()
    today = now.astimezone(zone).date()
    d_start, d_end = _day_range(today, zone)
    horizon = now + timedelta(days=int(s["days_ahead"]))
    analyses = _upcoming_analyses(db, min(d_start, now), max(d_end, horizon))
    today_an = [a for a in analyses if d_start <= a.match.kickoff < d_end]

    picks, avoid, market_agg = [], [], defaultdict(list)
    for a in analyses:
        p = a.payload
        if a.match.kickoff < now:
            continue
        for mk in p.get("markets", []):
            if mk.get("available") and mk["key"] in (p.get("picks") or []):
                card = pick_card(p, mk)
                picks.append(card)
                market_agg[mk["key"]].append(card)
        if p.get("avoid_reasons"):
            avoid.append({"match": p.get("match"), "reasons": p["avoid_reasons"],
                          "match_confidence": p.get("match_confidence")})
    by_prob = sorted(picks, key=lambda c: c["probability"], reverse=True)
    best_today = sorted([c for c in picks if d_start <= _parse(c["match"]["kickoff"]) < d_end],
                        key=lambda c: c["score"] or 0, reverse=True)
    top5, seen = [], set()
    for c in sorted(picks, key=lambda c: (c["probability"] * (0.5 + c["confidence"]["score"] / 200)), reverse=True):
        if c["match"]["id"] in seen:
            continue
        seen.add(c["match"]["id"])
        top5.append(c)
        if len(top5) == 5:
            break
    markets = sorted(({"key": k, "label": MARKET_BY_KEY[k].label, "count": len(v),
                       "avg_probability": round(sum(c["probability"] for c in v) / len(v), 4),
                       "avg_confidence": round(sum(c["confidence"]["score"] for c in v) / len(v), 1)}
                      for k, v in market_agg.items()), key=lambda d: (-d["count"], -d["avg_probability"]))
    perf = performance(db)["overall"]
    feat_perf = performance(db, featured=True)["overall"]
    featured_keys = _featured_keys(db, now)
    for c in picks:
        c["featured"] = (c["match"]["id"], c["market_key"]) in featured_keys
    selection = sorted([c for c in picks if (c["match"]["id"], c["market_key"]) in featured_keys],
                       key=lambda c: c["match"]["kickoff"])
    value_keys = _value_keys(db, now)
    value_picks = []
    for a in analyses:
        if a.match.kickoff < now:
            continue
        for mk in a.payload.get("markets", []):
            if mk.get("available") and (a.match_id, mk["key"]) in value_keys:
                value_picks.append(_value_card(a.payload, mk))
    value_picks.sort(key=lambda c: c["match"]["kickoff"])
    value_perf = performance(db, value=True)["overall"]
    soon = [a for a in analyses if now < a.match.kickoff < now + timedelta(hours=36)]
    combo_day = target_combos(_target_legs(soon, s, now), target=2.0, max_results=2)
    latest = db.scalars(select(Analysis).order_by(Analysis.computed_at.desc(), Analysis.id.desc()).limit(8)).unique().all()
    today_matches = [{"match": a.payload.get("match") or match_summary(a.match), "status": a.status,
                      "n_picks": a.n_picks, "match_confidence": a.match_confidence,
                      "avoid": bool(a.payload.get("avoid_reasons"))} for a in today_an]
    last_sync = db.scalar(select(func.max(SyncRun.finished_at)).where(SyncRun.status == "ok",
                                                                      SyncRun.provider != "moteur"))
    return {
        "date": today.isoformat(), "timezone": str(zone.key),
        "last_sync": last_sync.isoformat() if last_sync else None,
        "last_analysis": latest[0].computed_at.isoformat() if latest else None,
        "stats": {"matches_analysed": len([a for a in analyses if a.match.kickoff >= now]),
                  "matches_today": len(today_an), "picks": len(picks),
                  "competitions": len({a.match.competition_id for a in analyses}),
                  "insufficient": len([a for a in analyses if a.status != "ok" and a.match.kickoff >= now]),
                  "history_total": perf["total"], "history_hit_rate": perf["hit_rate"], "history_roi": perf["roi"],
                  "history_settled": perf["n"], "selection_settled": feat_perf["n"],
                  "selection_hit_rate": feat_perf["hit_rate"], "selection_roi": feat_perf["roi"],
                  "value_settled": value_perf["n"], "value_hit_rate": value_perf["hit_rate"],
                  "value_roi": value_perf["roi"], "value_avg_probability": value_perf["avg_probability"]},
        "selection": selection,
        "value_picks": value_picks,
        "value_settings": {k: s[k] for k in ("value_min_odds", "value_max_odds", "value_min_probability",
                                             "value_min_confidence", "value_max_per_day")},
        "combo_of_day": combo_day,
        "today_matches": today_matches,
        "best_today": best_today[:10],
        "by_probability": by_prob[:20],
        "top5": top5,
        "avoid": avoid[:10],
        "markets": markets[:8],
        "latest_analyses": [{"match": a.payload.get("match") or match_summary(a.match),
                             "computed_at": a.computed_at.isoformat(), "status": a.status, "n_picks": a.n_picks}
                            for a in latest],
    }


def _parse(iso: str) -> datetime:
    return datetime.fromisoformat(iso)


@router.get("/predictions")
def predictions(date_from: Optional[date] = None, date_to: Optional[date] = None, tz: Optional[str] = None,
                competition: Optional[str] = None, country: Optional[str] = None, team: Optional[str] = None,
                market: Optional[str] = None, family: Optional[str] = None,
                min_prob: float = Query(0.0, ge=0, le=1), min_conf: int = Query(0, ge=0, le=100),
                tier: Optional[str] = None, min_odds: Optional[float] = None, max_odds: Optional[float] = None,
                all_markets: bool = False, best: bool = False, featured_only: bool = False, value_only: bool = False, sort: str = "score",
                limit: int = Query(60, ge=1, le=300), db: Session = Depends(get_db)):
    zone = _tz(tz)
    now = _now()
    s = get_selection_settings(db)
    start = _day_range(date_from, zone)[0] if date_from else now
    end = _day_range(date_to, zone)[1] if date_to else now + timedelta(days=int(s["days_ahead"]))
    start = max(start, now - timedelta(hours=3))
    analyses = _upcoming_analyses(db, start, end)
    tiers = set(tier.upper().split(",")) if tier else None
    vk = _value_keys(db, now - timedelta(hours=3))
    cards = []
    for a in analyses:
        p = a.payload
        m = p.get("match") or {}
        comp = m.get("competition") or {}
        if competition and competition not in (str(comp.get("id")), comp.get("code")):
            continue
        if country and country.lower() != (comp.get("country") or "").lower():
            continue
        if team and team.lower() not in (m["home"]["name"] + " " + m["away"]["name"]).lower():
            continue
        best_card = None
        for mk in p.get("markets", []):
            if not mk.get("available"):
                continue
            is_pick = mk["key"] in (p.get("picks") or []) or (a.match_id, mk["key"]) in vk
            if best:
                if mk["probability"] < s["min_probability"] or mk["confidence"]["score"] < s["min_confidence"]:
                    continue
                ref_odds = mk.get("odds") or 1 / mk["probability"]
                if ref_odds < s["min_fair_odds"]:
                    continue
            elif not (all_markets or is_pick):
                continue
            if market and mk["key"] != market:
                continue
            if family and mk["family"] != family:
                continue
            if mk["probability"] < min_prob or mk["confidence"]["score"] < min_conf:
                continue
            if tiers and mk["tier"] not in tiers:
                continue
            if (min_odds or max_odds) and not mk.get("odds"):
                continue
            if min_odds and mk["odds"] < min_odds:
                continue
            if max_odds and mk["odds"] > max_odds:
                continue
            card = pick_card(p, mk)
            if best:
                opp = (mk.get("score") or 0) + 0.5 * max(mk.get("edge") or 0, 0)
                card["opportunity"] = round(opp, 4)
                if best_card is None or opp > best_card["opportunity"]:
                    best_card = card
            else:
                cards.append(card)
        if best and best_card:
            cards.append(best_card)
    keyfn = {"probability": lambda c: c["probability"], "confidence": lambda c: c["confidence"]["score"],
             "value": lambda c: c["edge"] if c["edge"] is not None else -9,
             "kickoff": lambda c: -_parse(c["match"]["kickoff"]).timestamp(),
             "score": lambda c: c.get("opportunity") or c["score"] or 0}.get(sort, lambda c: c["score"] or 0)
    fk = _featured_keys(db, now - timedelta(hours=3))
    for c in cards:
        c["featured"] = (c["match"]["id"], c["market_key"]) in fk
        c["value_pick"] = (c["match"]["id"], c["market_key"]) in vk
    if featured_only:
        cards = [c for c in cards if c["featured"]]
    if value_only:
        cards = [c for c in cards if c["value_pick"]]
    cards.sort(key=keyfn, reverse=True)
    return {"count": len(cards), "items": cards[:limit], "range": {"from": start.isoformat(), "to": end.isoformat()}}


@router.get("/matches")
def matches(day: Optional[date] = None, tz: Optional[str] = None, competition: Optional[str] = None,
            db: Session = Depends(get_db)):
    zone = _tz(tz)
    day = day or _now().astimezone(zone).date()
    start, end = _day_range(day, zone)
    q = select(Match).where(Match.kickoff >= start, Match.kickoff < end).order_by(Match.kickoff)
    rows = db.scalars(q).unique().all()
    an = {a.match_id: a for a in db.scalars(select(Analysis).where(
        Analysis.match_id.in_([m.id for m in rows]))).unique()} if rows else {}
    out = []
    for m in rows:
        if not m.competition.enabled:
            continue
        if competition and competition not in (str(m.competition_id), m.competition.code):
            continue
        a = an.get(m.id)
        out.append({"match": match_summary(m), "analysis": {
            "status": a.status, "n_picks": a.n_picks, "match_confidence": a.match_confidence,
            "picks": a.payload.get("picks"), "avoid": bool(a.payload.get("avoid_reasons")),
            "computed_at": a.computed_at.isoformat()} if a else None})
    return {"date": day.isoformat(), "timezone": str(zone.key), "items": out}


@router.get("/matches/{match_id}")
def match_detail(match_id: int, db: Session = Depends(get_db)):
    m = db.get(Match, match_id)
    if m is None:
        raise HTTPException(404, "Match introuvable")
    a = db.scalar(select(Analysis).where(Analysis.match_id == m.id))
    quotes = db.scalars(select(OddsQuote).where(OddsQuote.match_id == m.id).order_by(
        OddsQuote.market_key, OddsQuote.bookmaker)).all()
    preds = db.scalars(select(Prediction).where(Prediction.match_id == m.id)).unique().all()
    return {
        "match": match_summary(m),
        "analysis": a.payload if a else None,
        "computed_at": a.computed_at.isoformat() if a else None,
        "odds": [{"market_key": q.market_key, "bookmaker": q.bookmaker, "price": q.price, "source": q.source,
                  "collected_at": q.collected_at.isoformat()} for q in quotes],
        "predictions": [prediction_row(p) for p in preds],
    }


class ComboRequest(BaseModel):
    legs: int = Field(3, ge=2, le=5)
    mode: str = Field("prudent", pattern="^(prudent|valeur)$")
    min_confidence: int = Field(55, ge=0, le=100)
    competition_ids: Optional[list[int]] = None


class Selection(BaseModel):
    match_id: int
    market_key: str


class EvaluateRequest(BaseModel):
    selections: list[Selection] = Field(min_length=2, max_length=10)


def _leg(payload: dict, mk: dict) -> Leg:
    m = payload["match"]
    return Leg(match_id=m["id"], market_key=mk["key"], label=mk["label"], probability=mk["probability"],
               confidence=mk["confidence"]["score"], odds=mk.get("odds"), raw_probability=mk.get("raw_probability"),
               match_label=f"{m['home']['name']} – {m['away']['name']}", competition=m["competition"]["name"],
               kickoff=m["kickoff"], tier=mk.get("tier", ""))


@router.post("/combos/generate")
def combos_generate(req: ComboRequest, db: Session = Depends(get_db)):
    now = _now()
    s = get_selection_settings(db)
    analyses = _upcoming_analyses(db, now + timedelta(minutes=10), now + timedelta(days=int(s["days_ahead"])))
    cands = []
    for a in analyses:
        p = a.payload
        if req.competition_ids and a.match.competition_id not in req.competition_ids:
            continue
        for mk in p.get("markets", []):
            if mk.get("available") and mk["key"] in (p.get("picks") or []):
                cands.append(_leg(p, mk))
    combos = generate_combos(cands, req.legs, req.mode, max_results=3, min_confidence=req.min_confidence)
    msg = None
    if not combos:
        msg = ("Pas assez de sélections indépendantes répondant aux critères"
               + (" (le mode « valeur » exige des cotes disponibles et une valeur positive)" if req.mode == "valeur" else ""))
    return {"combos": combos, "candidates": len({c.match_id for c in cands}), "message": msg}


class TargetRequest(BaseModel):
    target: float = Field(2.0, ge=1.3, le=6.0)
    max_legs: int = Field(3, ge=2, le=4)
    min_confidence: int = Field(60, ge=0, le=100)
    hours: int = Field(48, ge=6, le=72)
    competition_ids: Optional[list[int]] = None


@router.post("/combos/target")
def combos_target(req: TargetRequest, db: Session = Depends(get_db)):
    """Combinés courts (2 à 4 matchs) visant une cote totale, classés par chance de passer."""
    now = _now()
    s = get_selection_settings(db)
    analyses = _upcoming_analyses(db, now + timedelta(minutes=10), now + timedelta(hours=req.hours))
    legs = _target_legs(analyses, s, now, req.competition_ids)
    combos = target_combos(legs, req.target, 2, req.max_legs, max_results=3, min_confidence=req.min_confidence)
    msg = None if combos else (f"Aucune combinaison de {req.max_legs} matchs au plus n'atteint une cote d'environ "
                               f"{str(req.target).replace('.', ',')} avec des sélections assez solides. "
                               "Essayez une cote cible plus basse ou une période plus longue.")
    return {"combos": combos, "candidates": len({l.match_id for l in legs}), "message": msg,
            "comparison": {"short": short_equivalent(req.target, 2), "long": naive_equivalent(req.target, 1.10)}}


@router.post("/combos/evaluate")
def combos_evaluate(req: EvaluateRequest, db: Session = Depends(get_db)):
    legs, models = [], {}
    for sel in req.selections:
        a = db.scalar(select(Analysis).where(Analysis.match_id == sel.match_id))
        if a is None or a.status != "ok":
            raise HTTPException(422, f"Match {sel.match_id} : analyse indisponible (données insuffisantes)")
        p = a.payload
        mk = next((x for x in p["markets"] if x["key"] == sel.market_key and x.get("available")), None)
        if mk is None:
            raise HTTPException(422, f"Marché {sel.market_key} indisponible pour ce match")
        legs.append(_leg(p, mk))
        eg = p.get("expected_goals")
        if eg and sel.match_id not in models:
            rho = (p.get("league") or {}).get("rho", 0.0)
            mat = score_matrix(eg["home"], eg["away"], rho)
            raw = {x["key"]: x.get("raw_probability") for x in p["markets"] if x.get("available")}
            models[sel.match_id] = MatchModel(matrix=mat, raw=raw)
    return evaluate_combo(legs, models)


@router.get("/history")
def history(limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0), result: Optional[str] = None,
            market: Optional[str] = None, competition: Optional[int] = None, featured: bool = False,
            value: bool = False, db: Session = Depends(get_db)):
    q = select(Prediction).join(Match, Prediction.match_id == Match.id)
    if featured:
        q = q.where(Prediction.featured.is_(True))
    if value:
        q = q.where(Prediction.value_pick.is_(True))
    if result:
        q = q.where(Prediction.result == result)
    if market:
        q = q.where(Prediction.market_key == market)
    if competition:
        q = q.where(Match.competition_id == competition)
    total = db.scalar(select(func.count()).select_from(q.subquery()))
    rows = db.scalars(q.order_by(Match.kickoff.desc(), Prediction.id.desc()).offset(offset).limit(limit)).unique().all()
    return {"total": total, "items": [prediction_row(p) for p in rows]}


@router.get("/performance")
def performance_endpoint(date_from: Optional[date] = None, date_to: Optional[date] = None,
                         competition: Optional[int] = None, featured: bool = False, value: bool = False,
                         db: Session = Depends(get_db)):
    df = datetime.combine(date_from, time(0), tzinfo=UTC) if date_from else None
    dt = datetime.combine(date_to, time(0), tzinfo=UTC) + timedelta(days=1) if date_to else None
    return performance(db, df, dt, competition, featured, value)


@router.get("/calibration")
def calibration_summary(db: Session = Depends(get_db)):
    cal = load_calibration(db)
    return {k: cal.get(k) for k in ("description", "source", "divisions", "period", "params", "n_matches",
                                     "generated_at", "out_of_sample", "reliability")}


@router.get("/public-summary")
def public_summary(db: Session = Depends(get_db)):
    """Chiffres publics pour la page de présentation (aucune donnée personnelle)."""
    perf = performance(db)["overall"]
    feat = performance(db, featured=True)["overall"]
    val = performance(db, value=True)["overall"]
    cal = load_calibration(db)
    oos = cal.get("out_of_sample") or {}
    comps = db.scalar(select(func.count(Competition.id)).where(Competition.enabled.is_(True)))
    upcoming = db.scalar(select(func.count(Analysis.id)).join(Match, Analysis.match_id == Match.id).where(
        Match.kickoff >= _now()))
    return {"competitions": comps, "upcoming_analysed": upcoming,
            "all": {k: perf[k] for k in ("total", "n", "won", "hit_rate", "avg_probability", "roi")},
            "selection": {k: feat[k] for k in ("total", "n", "won", "hit_rate", "avg_probability", "roi")},
            "value": {k: val[k] for k in ("total", "n", "won", "hit_rate", "avg_probability", "roi")},
            "backtest": {"tiers": oos.get("tiers"), "n_matches": cal.get("n_matches"),
                         "divisions": len(cal.get("divisions") or [])}}


@router.get("/live")
def live(tz: Optional[str] = None, db: Session = Depends(get_db)):
    """Journée : matchs en cours (scores football-data.org, légèrement différés), à venir et terminés."""
    from ..services.live import live_board
    return live_board(db, tz_name=tz)


@router.get("/recent-results")
def recent_results(limit: int = Query(12, ge=1, le=50), db: Session = Depends(get_db)):
    now = _now()
    settled = db.scalars(select(Prediction).join(Match, Prediction.match_id == Match.id).where(
        Prediction.result.in_(["won", "lost", "void", "unverifiable"])).order_by(
        Match.kickoff.desc()).limit(limit)).unique().all()
    waiting = db.scalars(select(Prediction).join(Match, Prediction.match_id == Match.id).where(
        Prediction.result == "pending", Match.kickoff < now - timedelta(minutes=110)).order_by(
        Match.kickoff.desc()).limit(limit)).unique().all()
    return {"settled": [prediction_row(p) for p in settled], "waiting": [prediction_row(p) for p in waiting]}
