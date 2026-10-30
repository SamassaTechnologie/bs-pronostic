"""Interface commune des fournisseurs de données football."""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Optional

import httpx

from ..config import get_settings


class ProviderError(Exception):
    """Erreur réelle renvoyée par un fournisseur (jamais masquée)."""


class QuotaExceeded(ProviderError):
    pass


@dataclass
class OddsRecord:
    market_key: str
    price: float
    bookmaker: str


@dataclass
class MatchRecord:
    competition_code: str
    kickoff: datetime  # UTC « aware »
    home_name: str
    away_name: str
    status: str  # SCHEDULED | LIVE | FINISHED | POSTPONED | CANCELLED
    source: str
    season: Optional[str] = None
    home_goals: Optional[int] = None
    away_goals: Optional[int] = None
    ht_home_goals: Optional[int] = None
    ht_away_goals: Optional[int] = None
    home_corners: Optional[int] = None
    away_corners: Optional[int] = None
    home_yellow: Optional[int] = None
    away_yellow: Optional[int] = None
    home_red: Optional[int] = None
    away_red: Optional[int] = None
    home_shots: Optional[int] = None
    away_shots: Optional[int] = None
    home_sot: Optional[int] = None
    away_sot: Optional[int] = None
    referee: Optional[str] = None
    source_ref: Optional[str] = None
    home_ext_id: Optional[int] = None
    away_ext_id: Optional[int] = None
    fixture_ext_id: Optional[int] = None
    odds: list[OddsRecord] = field(default_factory=list)


@dataclass
class InjuryRecord:
    team_name: str
    team_ext_id: Optional[int]
    player: str
    kind: Optional[str]
    reason: Optional[str]


class Provider(ABC):
    name: str = ""
    label: str = ""
    requires_key: bool = True
    website: str = ""
    capabilities: tuple[str, ...] = ()

    def __init__(self, usage_hook: Optional[Callable[[str, int], None]] = None,
                 budget_check: Optional[Callable[[str], bool]] = None):
        self.settings = get_settings()
        self._usage_hook = usage_hook
        self._budget_check = budget_check
        self.requests_made = 0

    @abstractmethod
    def is_configured(self) -> bool: ...

    @abstractmethod
    def test_connection(self) -> dict: ...

    def _client(self) -> httpx.Client:
        return httpx.Client(timeout=self.settings.http_timeout, follow_redirects=True,
                            headers={"User-Agent": self.settings.http_user_agent})

    def _request(self, url: str, headers: Optional[dict] = None, params: Optional[dict] = None,
                 count: bool = True, retries: int = 2) -> httpx.Response:
        if count and self._budget_check is not None and not self._budget_check(self.name):
            raise QuotaExceeded(f"{self.label} : budget quotidien de requêtes atteint")
        last_exc: Optional[Exception] = None
        for attempt in range(retries + 1):
            try:
                with self._client() as c:
                    r = c.get(url, headers=headers or {}, params=params or {})
                if count:
                    self.requests_made += 1
                    if self._usage_hook:
                        self._usage_hook(self.name, 1)
                if r.status_code in (429, 500, 502, 503, 504) and attempt < retries:
                    time.sleep(2 * (attempt + 1))
                    continue
                return r
            except httpx.HTTPError as exc:  # réseau, délai dépassé…
                last_exc = exc
                if attempt < retries:
                    time.sleep(2 * (attempt + 1))
        raise ProviderError(f"{self.label} : erreur réseau ({last_exc})")
