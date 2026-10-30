"""Règlement des pronostics et statistiques de performance (historique réel uniquement)."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..engine.calibration import brier_score, log_loss, reliability_table
from ..engine.markets import MARKET_BY_KEY, FAMILY_LABELS, evaluate_market
from ..models import Match, Prediction, utcnow
from .analysis import match_summary, match_to_data

UTC = timezone.utc


def settle_predictions(db: Session, now: Optional[datetime] = None) -> dict:
    now = now or utcnow()
    pending = db.scalars(select(Prediction).where(Prediction.result == "pending")).unique().all()
    counts = defaultdict(int)
    for p in pending:
        m = p.match
        if m.status == "FINISHED":
            outcome = evaluate_market(p.market_key, match_to_data(m))
            if outcome is None:
                if m.kickoff < now - timedelta(days=4):
                    p.result = "unverifiable"
                    p.settled_at = now
                    counts["unverifiable"] += 1
                continue
            p.result = "won" if outcome else "lost"
            p.settled_at = now
            counts[p.result] += 1
        elif m.status in ("POSTPONED", "CANCELLED") and m.kickoff < now - timedelta(days=2):
            p.result = "void"
            p.settled_at = now
            counts["void"] += 1
    db.commit()
    return dict(counts)


def _group_stats(rows: list[Prediction]) -> dict:
    settled = [r for r in rows if r.result in ("won", "lost")]
    won = sum(1 for r in settled if r.result == "won")
    with_odds = [r for r in settled if r.odds]
    profit = sum((r.odds - 1) if r.result == "won" else -1 for r in with_odds)
    n = len(settled)
    avg_p = sum(r.probability for r in settled) / n if n else None
    return {
        "n": n, "won": won, "lost": n - won,
        "hit_rate": round(won / n, 4) if n else None,
        "avg_probability": round(avg_p, 4) if avg_p is not None else None,
        "gap": round(avg_p - won / n, 4) if n else None,  # probabilité annoncée − fréquence réelle
        "staked": len(with_odds), "profit": round(profit, 2),
        "roi": round(profit / len(with_odds), 4) if with_odds else None,
    }


def performance(db: Session, date_from: Optional[datetime] = None, date_to: Optional[datetime] = None,
                competition_id: Optional[int] = None, featured: bool = False) -> dict:
    q = select(Prediction).join(Match, Prediction.match_id == Match.id)
    if featured:
        q = q.where(Prediction.featured.is_(True))
    if date_from:
        q = q.where(Match.kickoff >= date_from)
    if date_to:
        q = q.where(Match.kickoff < date_to)
    if competition_id:
        q = q.where(Match.competition_id == competition_id)
    rows = db.scalars(q.order_by(Match.kickoff)).unique().all()
    settled = [r for r in rows if r.result in ("won", "lost")]
    overall = _group_stats(rows)
    overall.update({
        "total": len(rows),
        "pending": sum(1 for r in rows if r.result == "pending"),
        "void": sum(1 for r in rows if r.result == "void"),
        "unverifiable": sum(1 for r in rows if r.result == "unverifiable"),
    })
    ps = [r.probability for r in settled]
    ys = [1 if r.result == "won" else 0 for r in settled]
    calibration = {
        "brier": round(brier_score(ps, ys), 5) if settled else None,
        "log_loss": round(log_loss(ps, ys), 5) if settled else None,
        "table": reliability_table(ps, ys, [0.7, 0.78, 0.85, 0.9, 0.95, 1.0001]) if settled else [],
    }

    def breakdown(keyfn, labelfn) -> list[dict]:
        groups = defaultdict(list)
        for r in rows:
            groups[keyfn(r)].append(r)
        out = []
        for k, items in groups.items():
            st = _group_stats(items)
            st.update({"key": k, "label": labelfn(k, items)})
            out.append(st)
        out.sort(key=lambda d: (-d["n"], str(d["key"])))
        return out

    by_market = breakdown(lambda r: r.market_key, lambda k, _: MARKET_BY_KEY[k].label if k in MARKET_BY_KEY else k)
    by_family = breakdown(lambda r: MARKET_BY_KEY[r.market_key].family if r.market_key in MARKET_BY_KEY else "autre",
                          lambda k, _: FAMILY_LABELS.get(k, k))
    by_comp = breakdown(lambda r: r.match.competition_id,
                        lambda k, items: f"{items[0].match.competition.name} ({items[0].match.competition.country})")
    by_tier = breakdown(lambda r: r.tier, lambda k, _: f"Niveau {k}")
    by_conf = breakdown(lambda r: r.confidence_level, lambda k, _: f"Confiance {k.lower()}")

    timeline, cum_profit, cum_won, cum_n = [], 0.0, 0, 0
    by_day = defaultdict(list)
    for r in settled:
        by_day[r.match.kickoff.date().isoformat()].append(r)
    for day in sorted(by_day):
        for r in by_day[day]:
            cum_n += 1
            cum_won += r.result == "won"
            if r.odds:
                cum_profit += (r.odds - 1) if r.result == "won" else -1
        timeline.append({"date": day, "n": cum_n, "hit_rate": round(cum_won / cum_n, 4),
                         "profit": round(cum_profit, 2)})
    return {"overall": overall, "calibration": calibration, "by_market": by_market, "by_family": by_family,
            "by_competition": by_comp, "by_tier": by_tier, "by_confidence": by_conf, "timeline": timeline,
            "stake_rule": "Mise fixe théorique de 1 unité par pronostic disposant d'une cote."}


def prediction_row(p: Prediction) -> dict:
    return {
        "id": p.id, "created_at": p.created_at.isoformat(), "match": match_summary(p.match),
        "market_key": p.market_key, "market_label": p.market_label, "probability": p.probability,
        "confidence": p.confidence, "confidence_level": p.confidence_level, "tier": p.tier, "odds": p.odds,
        "bookmaker": p.bookmaker, "implied_probability": p.implied_probability, "result": p.result,
        "settled_at": p.settled_at.isoformat() if p.settled_at else None, "explanation": p.explanation,
        "engine_version": p.engine_version, "featured": bool(p.featured),
        "featured_at": p.featured_at.isoformat() if p.featured_at else None,
    }
