"""Données de référence : compétitions et réglages par défaut (aucune donnée de match)."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .engine.selection import DEFAULT_SETTINGS
from .models import Competition, Setting
from .providers.football_data_co_uk import EXTRA_LEAGUES, MAIN_DIVISIONS

# code interne, code football-data.co.uk, id API-Football, code football-data.org, activé par défaut
MAIN = [
    ("ENG1", "E0", 39, "PL", True), ("ENG2", "E1", 40, "ELC", True), ("ENG3", "E2", 41, None, False),
    ("ENG4", "E3", 42, None, False), ("ENG5", "EC", 43, None, False),
    ("SCO1", "SC0", 179, None, True), ("SCO2", "SC1", 180, None, False), ("SCO3", "SC2", None, None, False),
    ("SCO4", "SC3", None, None, False),
    ("GER1", "D1", 78, "BL1", True), ("GER2", "D2", 79, None, False),
    ("ITA1", "I1", 135, "SA", True), ("ITA2", "I2", 136, None, False),
    ("ESP1", "SP1", 140, "PD", True), ("ESP2", "SP2", 141, None, False),
    ("FRA1", "F1", 61, "FL1", True), ("FRA2", "F2", 62, None, True),
    ("NED1", "N1", 88, "DED", True), ("BEL1", "B1", 144, None, True), ("POR1", "P1", 94, "PPL", True),
    ("TUR1", "T1", 203, None, True), ("GRE1", "G1", 197, None, False),
]
EXTRA = [  # code interne, code fdcuk, id API-Football, code fdorg, saison = année civile
    ("ARG1", "ARG", 128, None, True), ("AUT1", "AUT", 218, None, False), ("BRA1", "BRA", 71, "BSA", True),
    ("CHN1", "CHN", 169, None, True), ("DEN1", "DNK", 119, None, False), ("FIN1", "FIN", 244, None, True),
    ("IRL1", "IRL", 357, None, True), ("JPN1", "JPN", 98, None, True), ("MEX1", "MEX", 262, None, False),
    ("NOR1", "NOR", 103, None, True), ("POL1", "POL", 106, None, False), ("ROU1", "ROU", 283, None, False),
    ("SWE1", "SWE", 113, None, True), ("SUI1", "SWZ", 207, None, False), ("USA1", "USA", 253, None, True),
]
# Compétitions internationales (nécessitent une clé : API-Football ou football-data.org)
CUPS = [
    ("UCL", "Ligue des champions", "Europe", 2, "CL", "football_data_org"),
    ("UEL", "Ligue Europa", "Europe", 3, None, "api_football"),
    ("UECL", "Ligue Conférence", "Europe", 848, None, "api_football"),
    ("CAF1", "Ligue des champions CAF", "Afrique", 12, None, "api_football"),
    ("CAF2", "Coupe de la Confédération CAF", "Afrique", 20, None, "api_football"),
]


def seed_reference_data(db: Session) -> None:
    existing = {c.code for c in db.scalars(select(Competition)).all()}
    for code, div, af, fo, enabled in MAIN:
        if code in existing:
            continue
        name, country = MAIN_DIVISIONS[div]
        db.add(Competition(code=code, name=name, country=country, enabled=enabled, fdcuk_code=div,
                           api_football_id=af, fdorg_code=fo, primary_source="football_data_co_uk"))
    for code, fd, af, fo, calendar in EXTRA:
        if code in existing:
            continue
        name, country, _ = EXTRA_LEAGUES[fd]
        db.add(Competition(code=code, name=name, country=country, enabled=False, fdcuk_code=fd, fdcuk_extra=True,
                           api_football_id=af, fdorg_code=fo, calendar_year=calendar,
                           primary_source="football_data_co_uk"))
    for code, name, country, af, fo, primary in CUPS:
        if code in existing:
            continue
        db.add(Competition(code=code, name=name, country=country, enabled=False, api_football_id=af,
                           fdorg_code=fo, primary_source=primary))
    if db.get(Setting, "selection") is None:
        db.add(Setting(key="selection", value=dict(DEFAULT_SETTINGS)))
    if db.get(Setting, "providers") is None:
        db.add(Setting(key="providers", value={"football_data_co_uk": True, "api_football": True,
                                                "football_data_org": True}))
    db.commit()
