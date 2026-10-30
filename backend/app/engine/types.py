"""Structures de données partagées par le moteur statistique.

Le moteur est volontairement indépendant de la base de données : il travaille sur
des objets `MatchData` simples, ce qui permet de le tester et de le rejouer
(backtest) sur des données historiques sans dépendance externe.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Hashable, Optional


@dataclass(slots=True)
class MatchData:
    """Un match (terminé ou à venir) tel que vu par le moteur."""

    id: Hashable
    competition_id: Hashable
    kickoff: datetime  # UTC, timezone-aware
    home_id: Hashable
    away_id: Hashable
    hg: Optional[int] = None  # buts domicile (temps réglementaire)
    ag: Optional[int] = None  # buts extérieur
    hthg: Optional[int] = None  # buts domicile à la mi-temps
    htag: Optional[int] = None
    hc: Optional[int] = None  # corners domicile
    ac: Optional[int] = None
    hy: Optional[int] = None  # cartons jaunes domicile
    ay: Optional[int] = None
    hr: Optional[int] = None  # cartons rouges domicile
    ar: Optional[int] = None
    status: str = "FINISHED"
    season: Optional[str] = None

    @property
    def finished(self) -> bool:
        return self.status == "FINISHED" and self.hg is not None and self.ag is not None

    def goals_for(self, team_id: Hashable) -> Optional[int]:
        return self.hg if team_id == self.home_id else self.ag

    def goals_against(self, team_id: Hashable) -> Optional[int]:
        return self.ag if team_id == self.home_id else self.hg

    @property
    def total_cards(self) -> Optional[int]:
        if None in (self.hy, self.ay, self.hr, self.ar):
            return None
        return int(self.hy + self.ay + self.hr + self.ar)

    @property
    def total_corners(self) -> Optional[int]:
        if self.hc is None or self.ac is None:
            return None
        return int(self.hc + self.ac)


@dataclass(slots=True)
class OddsInfo:
    """Cote disponible pour un marché (jamais inventée : provient d'un fournisseur)."""

    price: float
    bookmaker: str
    source: str
    implied_probability: Optional[float] = None  # probabilité implicite sans marge
