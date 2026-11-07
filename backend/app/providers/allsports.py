"""Fournisseur AllSportsAPI (apiv2.allsportsapi.com) — clé requise (ALLSPORTS_KEY, côté serveur).

Apporte : championnats africains (Mali, Sénégal, Côte d'Ivoire, Maroc, Algérie, Tunisie, Égypte…),
calendrier, résultats (mi-temps comprise), statistiques de match (corners, cartons, tirs), cotes de
plusieurs bookmakers (1X2, double chance, buts, les deux équipes marquent) et scores en direct.

Les heures sont demandées en UTC (paramètre timezone). Une réponse {"success": 1} sans « result »
signifie « aucune donnée » (ex. pas de cotes pour ce championnat) : elle n'est jamais complétée.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Optional

from .base import MatchRecord, OddsRecord, Provider, ProviderError

UTC = timezone.utc
BASE_URL = "https://apiv2.allsportsapi.com/football/"

FINISHED = {"Finished", "After ET", "After Pen."}
CANCELLED = {"Cancelled", "Aban.", "Abandoned", "Awarded"}
POSTPONED = {"Postponed", "Suspended", "Interrupted"}

# Cotes AllSportsAPI → clés de marché SAM (lignes entières à remboursement ignorées)
ODDS_MAP = {
    "odd_1": "1", "odd_x": "X", "odd_2": "2", "odd_1x": "1X", "odd_x2": "X2", "odd_12": "12",
    "o+0.5": "O0.5", "o+1.5": "O1.5", "o+2.5": "O2.5", "o+3.5": "O3.5", "u+2.5": "U2.5", "u+3.5": "U3.5",
    "bts_yes": "BTTS_Y", "bts_no": "BTTS_N",
}


def _pair(s: Optional[str]) -> tuple[Optional[int], Optional[int]]:
    m = re.match(r"^\s*(\d+)\s*-\s*(\d+)\s*$", s or "")
    return (int(m.group(1)), int(m.group(2))) if m else (None, None)


def _int(v) -> Optional[int]:
    try:
        return int(str(v).replace("%", "").strip())
    except (TypeError, ValueError):
        return None


def status_of(x: dict) -> str:
    st = (x.get("event_status") or "").strip()
    if st in FINISHED:
        return "FINISHED"
    if st in CANCELLED:
        return "CANCELLED"
    if st in POSTPONED:
        return "POSTPONED"
    if str(x.get("event_live")) == "1" or st == "Half Time" or re.match(r"^\d+\+?$", st):
        return "LIVE"
    return "SCHEDULED"


def minute_of(x: dict) -> Optional[str]:
    st = (x.get("event_status") or "").strip()
    return st if re.match(r"^\d+\+?$", st) else None


def kickoff_of(x: dict) -> Optional[datetime]:
    try:
        return datetime.strptime(f"{x['event_date']} {x.get('event_time') or '00:00'}", "%Y-%m-%d %H:%M").replace(tzinfo=UTC)
    except (KeyError, ValueError):
        return None


def stats_of(x: dict) -> dict[str, tuple[Optional[int], Optional[int]]]:
    """Statistiques du match entier. Un même type peut apparaître deux fois (une période et le match complet) :
    on garde la valeur au total le plus élevé, qui est celle du match complet."""
    out: dict = {}
    for s in x.get("statistics") or []:
        t = s.get("type")
        v = (_int(s.get("home")), _int(s.get("away")))
        if not t or None in v:
            continue
        if t not in out or sum(v) > sum(out[t]):
            out[t] = v
    return out


class AllSports(Provider):
    name = "allsports"
    label = "AllSportsAPI"
    requires_key = True
    website = "https://allsportsapi.com"
    capabilities = ("championnats africains", "calendrier", "résultats", "mi-temps", "corners et cartons",
                    "cotes multi-bookmakers", "scores en direct")

    def is_configured(self) -> bool:
        return bool(self.settings.allsports_key)

    def _get(self, met: str, **params) -> object:
        if not self.is_configured():
            raise ProviderError("AllSportsAPI : clé absente (variable ALLSPORTS_KEY)")
        q = {"met": met, "APIkey": self.settings.allsports_key, "timezone": "UTC"}
        q.update({k: v for k, v in params.items() if v is not None})
        r = self._request(BASE_URL, params=q)
        if r.status_code >= 400:
            raise ProviderError(f"AllSportsAPI : HTTP {r.status_code}")
        try:
            data = r.json()
        except ValueError:
            raise ProviderError("AllSportsAPI : réponse illisible")
        if not isinstance(data, dict) or str(data.get("success")) != "1":
            msg = (data.get("error") or data.get("message")) if isinstance(data, dict) else None
            raise ProviderError(f"AllSportsAPI : requête refusée{f' — {msg}' if msg else ''}")
        return data.get("result")

    def test_connection(self) -> dict:
        try:
            leagues = self._get("Leagues") or []
        except ProviderError as exc:
            return {"ok": False, "message": str(exc)}
        if not leagues:
            return {"ok": False, "message": "AllSportsAPI : réponse vide (accès limité ou essai terminé ?)"}
        return {"ok": True, "message": f"Connexion réussie : {len(leagues)} championnats accessibles"}

    def fixtures(self, date_from: str, date_to: str, league_id: Optional[int] = None) -> list[dict]:
        res = self._get("Fixtures", **{"from": date_from, "to": date_to, "leagueId": league_id})
        return res if isinstance(res, list) else []

    def livescore(self) -> list[dict]:
        res = self._get("Livescore")
        return res if isinstance(res, list) else []

    def odds(self, date_from: str, date_to: str, league_id: Optional[int] = None) -> dict[str, list[dict]]:
        res = self._get("Odds", **{"from": date_from, "to": date_to, "leagueId": league_id})
        return res if isinstance(res, dict) else {}

    @staticmethod
    def odds_records(rows: list[dict]) -> list[OddsRecord]:
        out = []
        for row in rows or []:
            book = (row.get("odd_bookmakers") or "").strip()[:40]
            if not book:
                continue
            for k, key in ODDS_MAP.items():
                try:
                    price = float(row.get(k))
                except (TypeError, ValueError):
                    continue
                if price > 1.0:
                    out.append(OddsRecord(market_key=key, price=price, bookmaker=book))
        return out

    @staticmethod
    def to_record(x: dict, competition_code: str) -> Optional[MatchRecord]:
        home, away = (x.get("event_home_team") or "").strip(), (x.get("event_away_team") or "").strip()
        ko = kickoff_of(x)
        if not home or not away or ko is None:
            return None
        status = status_of(x)
        season = (x.get("league_season") or "").replace("/", "-")[:9] or None
        rec = MatchRecord(competition_code=competition_code, kickoff=ko, home_name=home, away_name=away,
                          status=status, source="allsports", season=season, source_ref=str(x.get("event_key") or ""),
                          referee=((x.get("event_referee") or "").split(",")[0].strip() or None))
        if status == "FINISHED":
            # Score du temps réglementaire (les paris se règlent sur 90 minutes)
            ft = x.get("event_ft_result") if (x.get("event_status") in ("After ET", "After Pen.")) else None
            rec.home_goals, rec.away_goals = _pair(ft or x.get("event_final_result"))
            if rec.home_goals is None:
                return None  # terminé sans score publié : on n'invente rien
            rec.ht_home_goals, rec.ht_away_goals = _pair(x.get("event_halftime_result"))
            st = stats_of(x)
            if "Corners" in st:
                rec.home_corners, rec.away_corners = st["Corners"]
            if "Yellow Cards" in st:
                rec.home_yellow, rec.away_yellow = st["Yellow Cards"]
                red = st.get("Red Cards")
                rec.home_red, rec.away_red = red or (0, 0)
            if "Shots Total" in st:
                rec.home_shots, rec.away_shots = st["Shots Total"]
            if "Shots On Goal" in st:
                rec.home_sot, rec.away_sot = st["Shots On Goal"]
        return rec


STAT_LABELS = (  # (type AllSportsAPI, libellé, pourcentage)
    ("Ball Possession", "Possession", True), ("Shots Total", "Tirs", False), ("Shots On Goal", "Tirs cadrés", False),
    ("Corners", "Corners", False), ("Dangerous Attacks", "Attaques dangereuses", False), ("Fouls", "Fautes", False),
    ("Offsides", "Hors-jeu", False), ("Saves", "Arrêts", False), ("Yellow Cards", "Cartons jaunes", False),
    ("Red Cards", "Cartons rouges", False),
)


def _minute_key(t: str) -> tuple:
    m = re.match(r"^(\d+)(?:\+(\d+))?", str(t or ""))
    return (int(m.group(1)), int(m.group(2) or 0)) if m else (999, 0)


def details_of(x: dict) -> Optional[dict]:
    """Chronologie (buts, penalties, contre son camp, cartons) et statistiques principales d'un match, telles que
    publiées par AllSportsAPI. None si la source ne donne rien."""
    events = []
    for g in x.get("goalscorers") or []:
        side = "home" if g.get("home_scorer") else "away" if g.get("away_scorer") else None
        if side is None:
            continue
        info = (g.get("info") or "").lower()
        kind = "own_goal" if "own" in info else "penalty" if "pen" in info else "goal"
        events.append({"minute": str(g.get("time") or "").strip(), "type": kind, "side": side,
                       "player": (g.get(f"{side}_scorer") or "").strip(), "assist": (g.get(f"{side}_assist") or "").strip(),
                       "score": (g.get("score") or "").replace(" ", "")})
    for c in x.get("cards") or []:
        side = "home" if c.get("home_fault") else "away" if c.get("away_fault") else None
        card = (c.get("card") or "").lower()
        if side is None or "card" not in card:
            continue
        kind = "second_yellow" if "yellow red" in card or "second" in card else "red" if "red" in card else "yellow"
        events.append({"minute": str(c.get("time") or "").strip(), "type": kind, "side": side,
                       "player": (c.get(f"{side}_fault") or "").strip()})
    for s in x.get("substitutes") or []:
        for side in ("home", "away"):
            v = s.get(f"{side}_scorer")
            if isinstance(v, dict) and (v.get("in") or v.get("out")):
                events.append({"minute": str(s.get("time") or "").strip(), "type": "sub", "side": side,
                               "player": (v.get("in") or "").strip(), "out": (v.get("out") or "").strip()})
    events.sort(key=lambda e: _minute_key(e["minute"]))
    raw = stats_of(x)
    stats = [{"label": label, "home": raw[t][0], "away": raw[t][1], "pct": pct}
             for t, label, pct in STAT_LABELS if t in raw]
    lineups = lineups_of(x)
    if not events and not stats and not lineups:
        return None
    out = {"events": events[:60], "stats": stats, "source": "AllSportsAPI"}
    if lineups:
        out["lineups"] = lineups
    return out


def _players(rows) -> list[dict]:
    out = []
    for r in rows or []:
        name = (r.get("player") or "").strip() if isinstance(r, dict) else ""
        if name:
            out.append({"name": name, "number": _int(r.get("player_number")), "pos": _int(r.get("player_position"))})
    return out


def lineups_of(x: dict) -> Optional[dict]:
    """Compositions officielles publiées par AllSportsAPI (environ une heure avant le match) ; None sinon."""
    lu = x.get("lineups")
    if not isinstance(lu, dict):
        return None
    out = {}
    for side, key in (("home", "home_team"), ("away", "away_team")):
        t = lu.get(key) or {}
        xi = _players(t.get("starting_lineups"))
        if len(xi) < 11:
            return None
        coach = next((c.get("coache") for c in t.get("coaches") or [] if isinstance(c, dict) and c.get("coache")), None)
        out[side] = {"formation": (x.get(f"event_{side}_formation") or "").strip() or None, "starting": xi,
                     "bench": _players(t.get("substitutes")), "coach": coach,
                     "missing": [m.get("player") for m in t.get("missing_players") or [] if isinstance(m, dict) and m.get("player")]}
    return out


def merge_details(old: Optional[dict], new: Optional[dict], minute: Optional[str] = None) -> Optional[dict]:
    """Nouvelle chronologie + ce qu'elle ne contient plus (compositions, relevés de pression du direct)."""
    old = old or {}
    if new is None:
        return old or None
    out = dict(new)
    if "lineups" not in out and old.get("lineups"):
        out["lineups"] = old["lineups"]
    pressure = list(old.get("pressure") or [])
    da = next((s for s in out.get("stats") or [] if s["label"] == "Attaques dangereuses"), None)
    m = _minute_key(minute or "")[0] if minute else None
    if da and m is not None and m < 999 and da["home"] is not None and da["away"] is not None:
        if not pressure or m > pressure[-1]["t"]:
            pressure.append({"t": m, "h": da["home"], "a": da["away"]})
    if pressure:
        out["pressure"] = pressure[-40:]
    for k in ("final",):
        if old.get(k) and k not in out:
            out[k] = old[k]
    return out
