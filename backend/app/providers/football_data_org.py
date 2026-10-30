"""Fournisseur football-data.org (v4) — clé gratuite.

Offre gratuite : 12 compétitions (dont Ligue des champions et Coupe du monde),
10 appels/minute, calendrier, résultats (dont mi-temps), classements. Pas de
cotes ni de statistiques de match (corners/cartons) dans l'offre gratuite.
"""
from __future__ import annotations

import time
from collections import deque
from datetime import datetime, timezone
from typing import Optional

from .base import MatchRecord, Provider, ProviderError

UTC = timezone.utc

STATUS_MAP = {
    "SCHEDULED": "SCHEDULED", "TIMED": "SCHEDULED", "IN_PLAY": "LIVE", "PAUSED": "LIVE", "LIVE": "LIVE",
    "FINISHED": "FINISHED", "AWARDED": "CANCELLED", "POSTPONED": "POSTPONED", "SUSPENDED": "POSTPONED",
    "CANCELLED": "CANCELLED",
}

FREE_COMPETITIONS = {"PL", "ELC", "BL1", "SA", "PD", "FL1", "DED", "PPL", "BSA", "CL", "EC", "WC"}


class FootballDataOrg(Provider):
    name = "football_data_org"
    label = "football-data.org"
    requires_key = True
    website = "https://www.football-data.org"
    capabilities = ("calendrier", "résultats", "mi-temps", "classements")

    _calls: deque = deque(maxlen=10)

    def is_configured(self) -> bool:
        return bool(self.settings.football_data_org_key)

    def _throttle(self) -> None:
        # Respecte la limite de 10 appels/minute de l'offre gratuite.
        if len(self._calls) == 10:
            wait = 61 - (time.monotonic() - self._calls[0])
            if wait > 0:
                time.sleep(wait)
        self._calls.append(time.monotonic())

    def _get(self, path: str, params: Optional[dict] = None) -> dict:
        if not self.is_configured():
            raise ProviderError("football-data.org : clé API absente (variable FOOTBALL_DATA_ORG_KEY)")
        self._throttle()
        url = self.settings.football_data_org_base_url.rstrip("/") + path
        r = self._request(url, headers={"X-Auth-Token": self.settings.football_data_org_key}, params=params)
        if r.status_code >= 400:
            try:
                msg = r.json().get("message")
            except ValueError:
                msg = None
            raise ProviderError(f"football-data.org : HTTP {r.status_code}" + (f" — {msg}" if msg else ""))
        return r.json()

    def test_connection(self) -> dict:
        try:
            data = self._get("/competitions")
        except ProviderError as exc:
            return {"ok": False, "message": str(exc)}
        comps = data.get("competitions") or []
        return {"ok": True, "message": f"Connexion réussie : {len(comps)} compétitions accessibles",
                "details": {"codes": sorted(c.get("code") for c in comps if c.get("code"))}}

    def competition_matches(self, code: str, season: int) -> list[dict]:
        return self._get(f"/competitions/{code}/matches", {"season": season}).get("matches") or []

    def matches_between(self, date_from: str, date_to: str) -> list[dict]:
        return self._get("/matches", {"dateFrom": date_from, "dateTo": date_to}).get("matches") or []

    @staticmethod
    def to_record(m: dict, competition_code: str) -> Optional[MatchRecord]:
        home, away = m.get("homeTeam") or {}, m.get("awayTeam") or {}
        if not m.get("utcDate") or not home.get("name") or not away.get("name"):
            return None
        status = STATUS_MAP.get(m.get("status", ""), "SCHEDULED")
        ko = datetime.fromisoformat(m["utcDate"].replace("Z", "+00:00")).astimezone(UTC)
        score = m.get("score") or {}
        regular = score.get("regularTime") or score.get("fullTime") or {}
        half = score.get("halfTime") or {}
        season = m.get("season") or {}
        start = (season.get("startDate") or "")[:4]
        end = (season.get("endDate") or "")[:4]
        rec = MatchRecord(
            competition_code=competition_code, kickoff=ko, home_name=home["name"], away_name=away["name"],
            status=status, source="football_data_org",
            season=(f"{start}-{end}" if start and end and start != end else start) or None,
            source_ref=str(m.get("id")), home_ext_id=home.get("id"), away_ext_id=away.get("id"),
            referee=next((r.get("name") for r in m.get("referees") or [] if r.get("type") == "REFEREE"), None),
        )
        if status == "FINISHED":
            rec.home_goals, rec.away_goals = regular.get("home"), regular.get("away")
            rec.ht_home_goals, rec.ht_away_goals = half.get("home"), half.get("away")
        return rec
