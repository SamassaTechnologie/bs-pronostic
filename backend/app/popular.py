"""Grands championnats (les plus suivis) : toujours affichés en premier dans les listes de l'application.

L'ordre ci-dessous est l'ordre d'affichage. Les autres compétitions suivent, sans changement de leur tri propre.
Cette mise en avant ne modifie aucune probabilité ni la Sélection SAM (choisie sur la seule fiabilité).
"""
from __future__ import annotations

POPULAR = ("UCL", "ENG1", "ESP1", "ITA1", "GER1", "FRA1", "UEL", "UECL", "POR1", "NED1", "CAF1", "INT")
_RANK = {code: i for i, code in enumerate(POPULAR)}


def is_popular(code: str | None) -> bool:
    return (code or "") in _RANK


def rank(code: str | None) -> int:
    """0, 1, 2… pour les grands championnats ; 100 pour les autres."""
    return _RANK.get(code or "", 100)
