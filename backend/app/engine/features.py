"""Indicateurs descriptifs : forme (5 / 10 matchs), domicile/extérieur,
confrontations directes et classement. Uniquement calculés à partir de matchs
réels présents en base ; rien n'est extrapolé."""
from __future__ import annotations

from bisect import bisect_left
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Hashable, Iterable, Optional, Sequence

from .markets import MARKET_BY_KEY, evaluate_market
from .types import MatchData

SYMMETRIC_FAMILIES = {"goals", "btts", "halftime", "corners", "cards"}


class TeamHistory:
    """Index des matchs terminés par équipe (ordre chronologique)."""

    def __init__(self, matches: Iterable[MatchData]):
        self._by_team: dict[Hashable, list[MatchData]] = defaultdict(list)
        for m in sorted((m for m in matches if m.finished), key=lambda m: m.kickoff):
            self._by_team[m.home_id].append(m)
            self._by_team[m.away_id].append(m)
        self._dates = {t: [m.kickoff for m in ms] for t, ms in self._by_team.items()}

    def before(self, team_id: Hashable, when: datetime, n: Optional[int] = None,
               venue: Optional[str] = None) -> list[MatchData]:
        ms = self._by_team.get(team_id, [])
        k = bisect_left(self._dates.get(team_id, []), when)
        out: list[MatchData] = []
        for m in reversed(ms[:k]):
            if venue == "home" and m.home_id != team_id:
                continue
            if venue == "away" and m.away_id != team_id:
                continue
            out.append(m)
            if n is not None and len(out) >= n:
                break
        return out  # du plus récent au plus ancien

    def last_played(self, team_id: Hashable, when: datetime) -> Optional[datetime]:
        prev = self.before(team_id, when, n=1)
        return prev[0].kickoff if prev else None


def _result_letter(m: MatchData, team_id: Hashable) -> str:
    gf, ga = m.goals_for(team_id), m.goals_against(team_id)
    return "V" if gf > ga else ("N" if gf == ga else "D")


def form_summary(team_id: Hashable, ms: Sequence[MatchData]) -> dict:
    """Résumé de forme sur une liste de matchs (plus récent en premier)."""
    n = len(ms)
    if n == 0:
        return {"played": 0}
    letters = [_result_letter(m, team_id) for m in ms]
    pts = sum(3 if r == "V" else 1 if r == "N" else 0 for r in letters)
    gf = [m.goals_for(team_id) for m in ms]
    ga = [m.goals_against(team_id) for m in ms]
    out = {
        "played": n,
        "sequence": "".join(letters),
        "wins": letters.count("V"), "draws": letters.count("N"), "losses": letters.count("D"),
        "points": pts,
        "points_per_match": round(pts / n, 2),
        "goals_for_avg": round(sum(gf) / n, 2),
        "goals_against_avg": round(sum(ga) / n, 2),
        "over25_rate": round(sum(1 for m in ms if m.hg + m.ag > 2.5) / n, 3),
        "btts_rate": round(sum(1 for m in ms if m.hg > 0 and m.ag > 0) / n, 3),
        "clean_sheets": sum(1 for x in ga if x == 0),
        "failed_to_score": sum(1 for x in gf if x == 0),
        "scored_in": sum(1 for x in gf if x > 0),
    }
    cm = [m for m in ms if m.total_corners is not None]
    if cm:
        out["corners_for_avg"] = round(sum(m.hc if m.home_id == team_id else m.ac for m in cm) / len(cm), 2)
        out["corners_against_avg"] = round(sum(m.ac if m.home_id == team_id else m.hc for m in cm) / len(cm), 2)
        out["corners_total_avg"] = round(sum(m.total_corners for m in cm) / len(cm), 2)
        out["corners_matches"] = len(cm)
    km = [m for m in ms if m.total_cards is not None]
    if km:
        out["cards_for_avg"] = round(
            sum((m.hy + m.hr) if m.home_id == team_id else (m.ay + m.ar) for m in km) / len(km), 2)
        out["cards_total_avg"] = round(sum(m.total_cards for m in km) / len(km), 2)
        out["cards_matches"] = len(km)
    return out


def market_rate(key: str, ms: Sequence[MatchData]) -> tuple[Optional[float], int]:
    vals = [evaluate_market(key, m) for m in ms]
    vals = [v for v in vals if v is not None]
    if not vals:
        return None, 0
    return sum(vals) / len(vals), len(vals)


def recent_market_rates(key: str, history: TeamHistory, home_id: Hashable, away_id: Hashable,
                        when: datetime, n: int = 10) -> dict:
    """Fréquence récente d'un marché pour chaque équipe.

    Marchés symétriques (buts, BTTS, corners, cartons) : 10 derniers matchs
    toutes compétitions présentes en base. Marchés de résultat : matchs à
    domicile de l'équipe qui reçoit, matchs à l'extérieur du visiteur."""
    spec = MARKET_BY_KEY[key]
    if spec.family in SYMMETRIC_FAMILIES:
        hm = history.before(home_id, when, n)
        am = history.before(away_id, when, n)
    else:
        hm = history.before(home_id, when, n, venue="home")
        am = history.before(away_id, when, n, venue="away")
    rh, nh = market_rate(key, hm)
    ra, na = market_rate(key, am)
    rates = [r for r in (rh, ra) if r is not None]
    return {
        "home_rate": rh, "home_n": nh, "away_rate": ra, "away_n": na,
        "combined": sum(rates) / len(rates) if rates else None,
        "n": nh + na,
    }


def h2h_matches(history: TeamHistory, home_id: Hashable, away_id: Hashable, when: datetime,
                years: int = 5, limit: int = 6) -> list[MatchData]:
    since = when - timedelta(days=365 * years)
    return [m for m in history.before(home_id, when)
            if m.kickoff >= since and {m.home_id, m.away_id} == {home_id, away_id}][:limit]


def head_to_head(history: TeamHistory, home_id: Hashable, away_id: Hashable, when: datetime,
                 years: int = 5, limit: int = 6) -> dict:
    ms = h2h_matches(history, home_id, away_id, when, years, limit)
    if not ms:
        return {"n": 0, "matches": []}
    wins_home = sum(1 for m in ms if m.goals_for(home_id) > m.goals_against(home_id))
    wins_away = sum(1 for m in ms if m.goals_for(away_id) > m.goals_against(away_id))
    return {
        "n": len(ms),
        "home_team_wins": wins_home,
        "away_team_wins": wins_away,
        "draws": len(ms) - wins_home - wins_away,
        "avg_total_goals": round(sum(m.hg + m.ag for m in ms) / len(ms), 2),
        "over25_rate": round(sum(1 for m in ms if m.hg + m.ag > 2.5) / len(ms), 3),
        "btts_rate": round(sum(1 for m in ms if m.hg > 0 and m.ag > 0) / len(ms), 3),
        "matches": [
            {"date": m.kickoff.isoformat(), "home_id": m.home_id, "away_id": m.away_id,
             "score": f"{m.hg}-{m.ag}"} for m in ms
        ],
    }


def standings(matches: Iterable[MatchData]) -> list[dict]:
    """Classement calculé à partir des résultats présents en base (3/1/0 points)."""
    table: dict[Hashable, dict] = {}
    for m in matches:
        if not m.finished:
            continue
        for t, gf, ga in ((m.home_id, m.hg, m.ag), (m.away_id, m.ag, m.hg)):
            row = table.setdefault(t, {"team_id": t, "played": 0, "wins": 0, "draws": 0, "losses": 0,
                                       "goals_for": 0, "goals_against": 0, "points": 0})
            row["played"] += 1
            row["goals_for"] += gf
            row["goals_against"] += ga
            if gf > ga:
                row["wins"] += 1
                row["points"] += 3
            elif gf == ga:
                row["draws"] += 1
                row["points"] += 1
            else:
                row["losses"] += 1
    rows = list(table.values())
    for r in rows:
        r["goal_difference"] = r["goals_for"] - r["goals_against"]
    rows.sort(key=lambda r: (-r["points"], -r["goal_difference"], -r["goals_for"]))
    for i, r in enumerate(rows, start=1):
        r["position"] = i
    return rows
