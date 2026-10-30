"""Fournisseur API-Football (api-sports.io, v3) — clé requise.

Apporte : calendrier de très nombreuses compétitions (dont africaines), résultats,
blessures/suspensions, cotes (1X2, double chance, buts, BTTS, mi-temps, corners,
cartons) et statistiques de match (corners, cartons, tirs, xG selon les ligues).

Le plan gratuit (100 requêtes/jour) donne accès à tous les endpoints mais à un
nombre limité de saisons : si la saison demandée n'est pas couverte, l'API
renvoie un message d'erreur explicite, qui est affiché tel quel dans
l'administration (aucune donnée n'est simulée).
"""
from __future__ import annotations

import re
import time
from collections import deque
from datetime import datetime, timezone
from typing import Optional

from .base import InjuryRecord, MatchRecord, OddsRecord, Provider, ProviderError

UTC = timezone.utc

STATUS_MAP = {
    "TBD": "SCHEDULED", "NS": "SCHEDULED",
    "1H": "LIVE", "HT": "LIVE", "2H": "LIVE", "ET": "LIVE", "BT": "LIVE", "P": "LIVE", "LIVE": "LIVE",
    "SUSP": "POSTPONED", "INT": "LIVE", "PST": "POSTPONED",
    "FT": "FINISHED", "AET": "FINISHED", "PEN": "FINISHED",
    "CANC": "CANCELLED", "ABD": "CANCELLED", "AWD": "CANCELLED", "WO": "CANCELLED",
}


def _num(v) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(str(v).replace("%", "").strip())
    except ValueError:
        return None


def map_bet(bet_name: str, value: str) -> Optional[str]:
    """Traduit un pari API-Football en clé de marché SAM (None si non utilisé)."""
    b = (bet_name or "").strip().lower()
    v = (value or "").strip().lower()
    m = re.match(r"^(over|under)\s+(\d+(?:\.\d+)?)$", v)
    if b == "match winner":
        return {"home": "1", "draw": "X", "away": "2"}.get(v)
    if b == "double chance":
        return {"home/draw": "1X", "draw/away": "X2", "home/away": "12"}.get(v)
    if b == "both teams score":
        return {"yes": "BTTS_Y", "no": "BTTS_N"}.get(v)
    if b == "first half winner":
        return {"home": "HT_1", "draw": "HT_X", "away": "HT_2"}.get(v)
    if not m:
        return None
    side = "O" if m.group(1) == "over" else "U"
    line = m.group(2) if "." in m.group(2) else m.group(2) + ".0"
    if not line.endswith(".5"):
        return None  # lignes entières (remboursement) non utilisées
    if b == "goals over/under":
        return f"{side}{line}"
    if b in ("goals over/under first half", "first half goals over/under"):
        return f"HT_{side}{line}"
    if b in ("corners over under", "corners over/under", "total corners"):
        return f"C_{side}{line}"
    if b in ("cards over/under", "total cards", "cards over under"):
        return f"K_{side}{line}"
    return None


class ApiFootball(Provider):
    name = "api_football"
    label = "API-Football"
    requires_key = True
    website = "https://www.api-football.com"
    capabilities = ("calendrier", "résultats", "blessures", "cotes multi-marchés", "statistiques de match")

    _calls: deque = deque(maxlen=9)

    def is_configured(self) -> bool:
        return bool(self.settings.api_football_key)

    def _throttle(self) -> None:
        # Plan gratuit : 10 requêtes/minute. On reste à 9 par fenêtre glissante de 60 s.
        if len(self._calls) == self._calls.maxlen:
            wait = 61 - (time.monotonic() - self._calls[0])
            if wait > 0:
                time.sleep(wait)
        self._calls.append(time.monotonic())

    def _get(self, path: str, params: Optional[dict] = None, count: bool = True) -> dict:
        if not self.is_configured():
            raise ProviderError("API-Football : clé API absente (variable API_FOOTBALL_KEY)")
        url = self.settings.api_football_base_url.rstrip("/") + path
        if count:
            self._throttle()
        r = self._request(url, headers={"x-apisports-key": self.settings.api_football_key}, params=params,
                          count=count)
        if r.status_code >= 400:
            raise ProviderError(f"API-Football : HTTP {r.status_code} sur {path}")
        data = r.json()
        errors = data.get("errors")
        if errors:  # liste vide ou dict vide = pas d'erreur
            msg = "; ".join(f"{k}: {v}" for k, v in errors.items()) if isinstance(errors, dict) else str(errors)
            raise ProviderError(f"API-Football : {msg}")
        return data

    def test_connection(self) -> dict:
        try:
            data = self._get("/status", count=False)  # n'est pas décompté du quota
        except ProviderError as exc:
            return {"ok": False, "message": str(exc)}
        resp = data.get("response") or {}
        sub = resp.get("subscription") or {}
        req = resp.get("requests") or {}
        return {"ok": True,
                "message": f"Connexion réussie — plan {sub.get('plan', '?')}, "
                           f"{req.get('current', '?')}/{req.get('limit_day', '?')} requêtes aujourd'hui",
                "details": {"plan": sub.get("plan"), "active": sub.get("active"), "end": sub.get("end"),
                            "requests_today": req.get("current"), "limit_day": req.get("limit_day")}}

    # --- Calendrier / résultats ---------------------------------------------------------------
    def fixtures_by_date(self, date_iso: str) -> list[dict]:
        return self._get("/fixtures", {"date": date_iso, "timezone": "UTC"}).get("response") or []

    def fixtures_by_league(self, league_id: int, season: int) -> list[dict]:
        return self._get("/fixtures", {"league": league_id, "season": season, "timezone": "UTC"}).get("response") or []

    @staticmethod
    def to_record(fx: dict, competition_code: str) -> Optional[MatchRecord]:
        f = fx.get("fixture") or {}
        teams = fx.get("teams") or {}
        score = fx.get("score") or {}
        status = STATUS_MAP.get(((f.get("status") or {}).get("short") or "").upper(), "SCHEDULED")
        date_s = f.get("date")
        if not date_s or not teams.get("home") or not teams.get("away"):
            return None
        ko = datetime.fromisoformat(date_s.replace("Z", "+00:00")).astimezone(UTC)
        ft = score.get("fulltime") or {}
        ht = score.get("halftime") or {}
        league = fx.get("league") or {}
        rec = MatchRecord(
            competition_code=competition_code, kickoff=ko, home_name=teams["home"].get("name", ""),
            away_name=teams["away"].get("name", ""), status=status, source="api_football",
            season=str(league.get("season")) if league.get("season") else None,
            referee=f.get("referee"), source_ref=str(f.get("id")), fixture_ext_id=f.get("id"),
            home_ext_id=teams["home"].get("id"), away_ext_id=teams["away"].get("id"),
        )
        if status == "FINISHED":
            # score « fulltime » = score à 90 minutes (hors prolongation), ce qu'utilisent les marchés.
            rec.home_goals, rec.away_goals = ft.get("home"), ft.get("away")
            rec.ht_home_goals, rec.ht_away_goals = ht.get("home"), ht.get("away")
        return rec

    # --- Statistiques ------------------------------------------------------------------------
    def fixture_statistics(self, fixture_id: int) -> dict[int, dict]:
        resp = self._get("/fixtures/statistics", {"fixture": fixture_id}).get("response") or []
        out = {}
        for block in resp:
            team_id = (block.get("team") or {}).get("id")
            stats = {s.get("type"): s.get("value") for s in block.get("statistics") or []}
            if team_id is None or not stats:
                continue

            def count(name):  # API-Football renvoie null pour 0 sur certains compteurs
                v = _num(stats.get(name))
                return int(v) if v is not None else (0 if name in stats else None)

            out[team_id] = {"corners": count("Corner Kicks"), "yellow": count("Yellow Cards"),
                            "red": count("Red Cards"), "shots": count("Total Shots"),
                            "sot": count("Shots on Goal"), "xg": _num(stats.get("expected_goals"))}
        return out

    # --- Blessures / suspensions -------------------------------------------------------------
    def injuries_for_fixture(self, fixture_id: int) -> list[InjuryRecord]:
        resp = self._get("/injuries", {"fixture": fixture_id}).get("response") or []
        out = []
        for it in resp:
            p, t = it.get("player") or {}, it.get("team") or {}
            if p.get("name"):
                out.append(InjuryRecord(team_name=t.get("name", ""), team_ext_id=t.get("id"), player=p["name"],
                                        kind=p.get("type"), reason=p.get("reason")))
        return out

    # --- Cotes --------------------------------------------------------------------------------
    def odds_for_fixture(self, fixture_id: int) -> list[OddsRecord]:
        resp = self._get("/odds", {"fixture": fixture_id}).get("response") or []
        out: list[OddsRecord] = []
        for item in resp:
            for bk in item.get("bookmakers") or []:
                name = bk.get("name") or f"bookmaker {bk.get('id')}"
                for bet in bk.get("bets") or []:
                    for v in bet.get("values") or []:
                        key = map_bet(bet.get("name", ""), str(v.get("value", "")))
                        price = _num(v.get("odd"))
                        if key and price and price > 1.0:
                            out.append(OddsRecord(key, price, name))
        return out
