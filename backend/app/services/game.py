"""Section « Jouer » : paris en jetons virtuels (aucun argent réel, aucun dépôt ni retrait).

* Cotes proposées : la cote bookmaker collectée quand elle existe, sinon une « cote SAM » = cote juste du moteur
  diminuée d'une marge de 6 % (comme un bookmaker), toujours signalée comme telle.
* Paris acceptés jusqu'au coup d'envoi, réglés automatiquement avec les scores officiels.
* Bonus quotidien, classement mensuel au bénéfice net.
"""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..engine import extended as ext
from ..engine.markets import FAMILY_LABELS, evaluate_market, score_matrix
from ..models import Analysis, Bet, BetLeg, Match, Wallet, utcnow

START_BALANCE = 1000
DAILY_BONUS = 50
SAM_MARGIN = 0.06
MIN_STAKE, MAX_STAKE = 10, 5000
MAX_LEGS = 10
MAX_ODDS = 50.0

FAMILY_ORDER = ["result", "double_chance", "goals", "btts", "halftime_result", "halftime", "corners", "cards"]


class GameError(ValueError):
    pass


def offered_odds(mk: dict) -> tuple[float, str]:
    if mk.get("odds"):
        return round(min(MAX_ODDS, max(1.01, float(mk["odds"]))), 2), "bookmaker"
    fair = 1 / max(float(mk["probability"]), 1e-6)
    return round(min(MAX_ODDS, max(1.01, fair * (1 - SAM_MARGIN))), 2), "sam"


def extended_rows(payload: dict) -> list[dict]:
    """Marchés étendus du match (catalogue complet), probabilités du modèle non calibrées, cote SAM."""
    eg = payload.get("expected_goals")
    if not eg:
        return []
    m = payload.get("match") or {}
    home, away = (m.get("home") or {}).get("name", "Équipe 1"), (m.get("away") or {}).get("name", "Équipe 2")
    rho = (payload.get("league") or {}).get("rho", 0.0) or 0.0
    ht = payload.get("expected_ht_goals")
    rows = ext.compute(score_matrix(eg["home"], eg["away"], rho), eg["home"], eg["away"],
                       (ht["home"], ht["away"]) if ht else None)
    out = []
    for r in rows:
        margin = SAM_MARGIN if r["probability"] >= 0.2 else 0.10  # marge plus forte sur les issues rares
        odds = round(min(MAX_ODDS, max(1.01, r["fair_odds"] * (1 - margin))), 2)
        out.append({"key": r["key"], "label": r["label"].replace("{E1}", home).replace("{E2}", away),
                    "short": r["label"].replace("{E1}", "1").replace("{E2}", "2"), "family": r["family"],
                    "odds": odds, "odds_source": "sam", "probability": r["probability"],
                    "void_probability": r["void_probability"], "confidence": None, "is_pick": False,
                    "extended": True})
    return out


def _open(m: Match, now: datetime) -> bool:
    return m.status == "SCHEDULED" and m.kickoff > now + timedelta(minutes=1)


def wallet(db: Session, member_id: str, name: Optional[str] = None, today: Optional[date] = None) -> Wallet:
    """Portefeuille du membre (créé à la première visite), bonus quotidien crédité au premier passage du jour."""
    today = today or utcnow().date()
    w = db.get(Wallet, member_id)
    if w is None:
        w = Wallet(member_id=member_id, display_name=(name or "Membre")[:60], balance=START_BALANCE,
                   last_bonus=today.isoformat())
        db.add(w)
        db.commit()
        return w
    changed = False
    if name and name[:60] != w.display_name:
        w.display_name = name[:60]
        changed = True
    if w.last_bonus != today.isoformat():
        w.balance += DAILY_BONUS
        w.last_bonus = today.isoformat()
        changed = True
    if changed:
        db.commit()
    return w


def market_row(mk: dict) -> dict:
    odds, src = offered_odds(mk)
    return {"key": mk["key"], "label": mk["label"], "short": mk.get("short") or mk["key"], "family": mk["family"],
            "odds": odds, "odds_source": src, "probability": mk["probability"],
            "confidence": mk["confidence"]["score"], "is_pick": False}


def board(db: Session, start: datetime, end: datetime, now: Optional[datetime] = None) -> list[dict]:
    """Matchs ouverts aux paris, groupés par championnat, avec la cote 1X2 et le repère SAM."""
    now = now or utcnow()
    rows = db.scalars(select(Analysis).join(Match, Analysis.match_id == Match.id).where(
        Match.kickoff >= max(start, now), Match.kickoff < end, Analysis.status == "ok")
        .order_by(Match.kickoff)).unique().all()
    groups: dict[str, dict] = {}
    for a in rows:
        m = a.match
        if not _open(m, now):
            continue
        p = a.payload
        mks = {mk["key"]: mk for mk in p.get("markets", []) if mk.get("available")}
        if not all(k in mks for k in ("1", "X", "2")):
            continue
        picks = [mks[k] for k in (p.get("picks") or []) if k in mks]
        best = max(picks, key=lambda x: x["probability"]) if picks else None
        info = p.get("match") or {}
        comp = info.get("competition") or {}
        g = groups.setdefault(comp.get("code") or str(m.competition_id), {
            "code": comp.get("code"), "name": comp.get("name"), "country": comp.get("country"), "matches": []})
        g["matches"].append({
            "match": info, "markets_count": len(mks) + len(ext.CATALOG),
            "odds": {k: market_row(mks[k]) for k in ("1", "X", "2")},
            "sam": {"key": best["key"], "label": best["label"], "short": best.get("short"),
                    "probability": best["probability"]} if best else None,
            "avoid": bool(p.get("avoid_reasons")),
        })
    return list(groups.values())


def match_markets(db: Session, match_id: int, now: Optional[datetime] = None) -> dict:
    now = now or utcnow()
    a = db.scalar(select(Analysis).where(Analysis.match_id == match_id))
    m = db.get(Match, match_id)
    if m is None:
        raise GameError("Match introuvable")
    if a is None or a.status != "ok":
        return {"match": None, "open": False, "groups": [], "message": "Données insuffisantes : paris indisponibles"}
    p = a.payload
    picks = set(p.get("picks") or [])
    fams: dict[str, list] = {}
    for mk in p.get("markets", []):
        if mk.get("available"):
            r = market_row(mk)
            r["is_pick"] = mk["key"] in picks
            fams.setdefault(mk["family"], []).append(r)
    groups = [{"family": f, "label": FAMILY_LABELS.get(f, f), "markets": fams[f]}
              for f in FAMILY_ORDER if f in fams]
    xf: dict[str, list] = {}
    for r in extended_rows(p):
        xf.setdefault(r["family"], []).append(r)
    groups += [{"family": f, "label": ext.FAMILIES[f], "markets": xf[f], "extended": True}
               for f in ext.FAMILY_ORDER if f in xf]
    from .market_layout import build as build_layout
    allrows = [r for g in groups for r in g["markets"]]
    tabs = build_layout(allrows, m.home_team.name, m.away_team.name)
    return {"match": p.get("match"), "open": _open(m, now), "groups": groups, "tabs": tabs,
            "expected_goals": p.get("expected_goals"), "avoid_reasons": p.get("avoid_reasons") or [],
            "message": None if _open(m, now) else "Paris fermés : le match a commencé ou est terminé"}


def _leg_for(db: Session, match_id: int, key: str, now: datetime) -> tuple[BetLeg, Match]:
    a = db.scalar(select(Analysis).where(Analysis.match_id == match_id))
    m = db.get(Match, match_id)
    if m is None or a is None or a.status != "ok":
        raise GameError(f"Match {match_id} : paris indisponibles (données insuffisantes)")
    if not _open(m, now):
        raise GameError(f"{m.home_team.name} – {m.away_team.name} : paris fermés")
    if key.startswith("e:"):
        row = next((r for r in extended_rows(a.payload) if r["key"] == key), None)
        if row is None:
            raise GameError(f"Marché {key} indisponible pour ce match")
        return BetLeg(match_id=m.id, market_key=key, label=row["label"][:80], odds=row["odds"], odds_source="sam",
                      probability=row["probability"]), m
    mk = next((x for x in a.payload.get("markets", []) if x["key"] == key and x.get("available")), None)
    if mk is None:
        raise GameError(f"Marché {key} indisponible pour ce match")
    odds, src = offered_odds(mk)
    return BetLeg(match_id=m.id, market_key=key, label=mk["label"], odds=odds, odds_source=src,
                  probability=mk["probability"]), m


def combo_probability(db: Session, selections: list[tuple[int, str]], legs: list[BetLeg]) -> Optional[float]:
    """Probabilité SAM d'un combiné (matchs différents) : moteur de combinés pour les marchés principaux,
    produit des probabilités sinon (marchés étendus, matchs indépendants)."""
    from ..api.public import evaluate_selections
    if not any(k.startswith("e:") for _, k in selections):
        try:
            return evaluate_selections(db, selections).get("probability")
        except ValueError:
            return None
    if len({mid for mid, _ in selections}) < len(selections) or any(l.probability is None for l in legs):
        return None
    return round(math.prod(l.probability for l in legs), 4)


def place_bets(db: Session, member_id: str, selections: list[tuple[int, str]], stake: int, mode: str,
               now: Optional[datetime] = None) -> list[Bet]:
    """Enregistre un combiné, ou un pari simple par sélection (même mise chacun). Les cotes sont relues ici."""
    now = now or utcnow()
    if not selections:
        raise GameError("Coupon vide")
    if len(selections) > MAX_LEGS:
        raise GameError(f"{MAX_LEGS} sélections au maximum")
    if len(set(selections)) < len(selections):
        raise GameError("Sélection en double")
    if not MIN_STAKE <= stake <= MAX_STAKE:
        raise GameError(f"Mise entre {MIN_STAKE} et {MAX_STAKE} jetons")
    legs = [_leg_for(db, mid, key, now) for mid, key in selections]
    w = db.scalar(select(Wallet).where(Wallet.member_id == member_id).with_for_update())
    if w is None:
        raise GameError("Portefeuille introuvable")
    bets: list[Bet] = []
    if mode == "combine":
        if len(legs) < 2:
            raise GameError("Un combiné compte au moins 2 sélections")
        if len({m.id for _, m in legs}) < len(legs):
            raise GameError("Un combiné ne peut contenir qu'une sélection par match")
        total = round(math.prod(leg.odds for leg, _ in legs), 2)
        sam_p = combo_probability(db, selections, [leg for leg, _ in legs])
        bets.append(Bet(member_id=member_id, created_at=now, kind="combine", stake=stake, total_odds=total,
                        sam_probability=sam_p, legs=[leg for leg, _ in legs]))
    else:
        for leg, _ in legs:
            bets.append(Bet(member_id=member_id, created_at=now, kind="simple", stake=stake, total_odds=leg.odds,
                            sam_probability=leg.probability, legs=[leg]))
    cost = stake * len(bets)
    if cost > w.balance:
        raise GameError(f"Solde insuffisant : {w.balance} jetons disponibles pour {cost} misés")
    w.balance -= cost
    for b in bets:
        db.add(b)
    db.commit()
    return bets


def settle_bets(db: Session, now: Optional[datetime] = None) -> dict:
    """Règle les paris dont les matchs sont terminés (appelé avec le règlement des pronostics)."""
    now = now or utcnow()
    counts = {"won": 0, "lost": 0, "void": 0}
    for b in db.scalars(select(Bet).where(Bet.status == "pending")).unique().all():
        for leg in b.legs:
            if leg.result != "pending":
                continue
            m = leg.match
            if m.status == "FINISHED":
                if leg.market_key.startswith("e:"):
                    res = ext.settle(leg.market_key, m.home_goals, m.away_goals, m.ht_home_goals, m.ht_away_goals)
                    if res is None:
                        if m.kickoff < now - timedelta(days=8):
                            leg.result = "void"
                        continue
                    leg.result = res
                    continue
                from .analysis import match_to_data
                out = evaluate_market(leg.market_key, match_to_data(m))
                if out is None:
                    if m.kickoff < now - timedelta(days=8):
                        leg.result = "void"
                    continue
                leg.result = "won" if out else "lost"
            elif m.status in ("POSTPONED", "CANCELLED") and m.kickoff < now - timedelta(days=2):
                leg.result = "void"
        results = [leg.result for leg in b.legs]
        if "lost" in results:
            b.status, b.payout = "lost", 0
        elif "pending" in results:
            continue
        elif all(r == "void" for r in results):
            b.status, b.payout = "void", b.stake
        else:
            odds = math.prod(leg.odds for leg in b.legs if leg.result == "won")
            b.status, b.payout = "won", int(round(b.stake * odds))
        b.settled_at = now
        counts[b.status] += 1
        if b.payout:
            w = db.get(Wallet, b.member_id)
            if w is not None:
                w.balance += b.payout
    db.commit()
    return counts


def _leg_live(db: Session, leg: BetLeg, now: datetime) -> dict:
    """État du match d'une sélection : à venir, en direct (score, minute, sélection gagnante à l'instant), terminé."""
    from ..engine.types import MatchData
    from .live import match_live_state
    m = leg.match
    if m.status == "FINISHED" and m.home_goals is not None:
        return {"state": "finished", "home": m.home_goals, "away": m.away_goals,
                "ht_home": m.ht_home_goals, "ht_away": m.ht_away_goals}
    if m.kickoff > now:
        return {"state": "scheduled"}
    st = match_live_state(db, m)
    out = {"state": st.get("state"), "home": st.get("home"), "away": st.get("away"), "minute": st.get("minute"),
           "minute_estimated": st.get("minute_estimated"), "label": st.get("label"), "covered": st.get("covered")}
    if st.get("state") == "live" and st.get("home") is not None:
        h, a = int(st["home"]), int(st["away"])
        if leg.market_key.startswith("e:"):
            mk = ext.BY_KEY.get(leg.market_key)
            r = ext.settle(leg.market_key, h, a, None, None) if mk and not mk.halves else None
            out["winning_now"] = None if r is None else r == "won"
        else:
            r = evaluate_market(leg.market_key, MatchData(m.id, m.competition_id, m.kickoff, m.home_team_id,
                                                          m.away_team_id, hg=h, ag=a))
            out["winning_now"] = r
    return out


def bet_row(b: Bet, db: Optional[Session] = None, now: Optional[datetime] = None) -> dict:
    now = now or utcnow()
    legs = []
    for l in b.legs:
        row = {"match_id": l.match_id, "match": f"{l.match.home_team.name} – {l.match.away_team.name}",
               "competition": l.match.competition.name, "kickoff": l.match.kickoff.isoformat(),
               "status": l.match.status,
               "score": (f"{l.match.home_goals}-{l.match.away_goals}" if l.match.home_goals is not None else None),
               "label": l.label, "odds": l.odds, "odds_source": l.odds_source,
               "probability": l.probability, "result": l.result}
        if db is not None and l.result == "pending":
            row["live"] = _leg_live(db, l, now)
        legs.append(row)
    return {"id": b.id, "kind": b.kind, "stake": b.stake, "total_odds": b.total_odds,
            "potential": int(round(b.stake * b.total_odds)), "status": b.status, "payout": b.payout,
            "sam_probability": b.sam_probability, "created_at": b.created_at.isoformat(),
            "settled_at": b.settled_at.isoformat() if b.settled_at else None, "legs": legs,
            "progress": {"won": sum(l.result == "won" for l in b.legs), "lost": sum(l.result == "lost" for l in b.legs),
                         "pending": sum(l.result == "pending" for l in b.legs), "total": len(b.legs)}}


def member_summary(db: Session, member_id: str) -> dict:
    settled = db.scalars(select(Bet).where(Bet.member_id == member_id, Bet.status.in_(("won", "lost")))).all()
    won = sum(1 for b in settled if b.status == "won")
    staked = sum(b.stake for b in settled)
    returned = sum(b.payout for b in settled)
    return {"settled": len(settled), "won": won, "hit_rate": round(won / len(settled), 4) if settled else None,
            "profit": returned - staked}


def ranking(db: Session, member_id: Optional[str] = None, now: Optional[datetime] = None, limit: int = 20) -> dict:
    """Classement du mois : bénéfice net des paris réglés ce mois-ci."""
    now = now or utcnow()
    month_start = datetime(now.year, now.month, 1, tzinfo=timezone.utc)
    rows = db.execute(select(Bet.member_id, func.sum(Bet.payout - Bet.stake), func.count(Bet.id))
                      .where(Bet.status.in_(("won", "lost")), Bet.settled_at >= month_start)
                      .group_by(Bet.member_id)).all()
    rows = sorted(rows, key=lambda r: (-(r[1] or 0), r[0]))
    names = {w.member_id: w.display_name for w in db.scalars(select(Wallet).where(
        Wallet.member_id.in_([r[0] for r in rows] or [""]))).all()}
    table = [{"position": i + 1, "name": names.get(r[0], "Membre"), "profit": int(r[1] or 0), "bets": r[2],
              "me": r[0] == member_id} for i, r in enumerate(rows)]
    mine = next((t for t in table if t["me"]), None)
    return {"month": month_start.strftime("%Y-%m"), "top": table[:limit], "me": mine, "players": len(table)}
