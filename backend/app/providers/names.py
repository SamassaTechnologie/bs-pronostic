"""Normalisation et rapprochement des noms d'équipes entre fournisseurs."""
from __future__ import annotations

import re
import unicodedata
from typing import Iterable, Optional

from rapidfuzz import fuzz

STOPWORDS = {
    "fc", "cf", "afc", "sc", "ac", "club", "cd", "ud", "sd", "rc", "ssc", "us", "sv", "fk", "sk", "bk",
    "the", "de", "calcio", "ssd", "asd", "cfc", "kv", "krc", "rsc", "1", "sl", "ca",
}

# Abréviations de football-data.co.uk et variantes courantes -> forme canonique
ALIASES = {
    "man united": "manchester united", "man utd": "manchester united", "manchester utd": "manchester united",
    "man city": "manchester city", "nott m forest": "nottingham forest", "nottm forest": "nottingham forest",
    "sheffield weds": "sheffield wednesday", "sheffield utd": "sheffield united", "sheff utd": "sheffield united",
    "west brom": "west bromwich albion", "wolves": "wolverhampton wanderers", "qpr": "queens park rangers",
    "spurs": "tottenham", "tottenham hotspur": "tottenham", "brighton and hove albion": "brighton",
    "brighton hove albion": "brighton", "newcastle united": "newcastle", "west ham united": "west ham",
    "leeds united": "leeds", "leicester city": "leicester", "ipswich town": "ipswich", "luton town": "luton",
    "ath madrid": "atletico madrid", "atl madrid": "atletico madrid", "ath bilbao": "athletic club",
    "athletic bilbao": "athletic club", "sociedad": "real sociedad", "betis": "real betis", "celta": "celta vigo",
    "vallecano": "rayo vallecano", "espanol": "espanyol", "alaves": "deportivo alaves",
    "paris sg": "paris saint germain", "psg": "paris saint germain", "st etienne": "saint etienne",
    "ein frankfurt": "eintracht frankfurt", "m gladbach": "borussia monchengladbach",
    "monchengladbach": "borussia monchengladbach", "leverkusen": "bayer leverkusen", "fc koln": "koln",
    "bayern munich": "bayern munchen", "dortmund": "borussia dortmund", "hertha": "hertha berlin",
    "milan": "ac milan", "verona": "hellas verona", "inter milan": "inter", "internazionale": "inter",
    "sp lisbon": "sporting cp", "sporting lisbon": "sporting cp", "sp braga": "braga", "sporting braga": "braga",
    "for sittard": "fortuna sittard", "nijmegen": "nec nijmegen", "psv eindhoven": "psv",
}


def normalize_team(name: str) -> str:
    s = unicodedata.normalize("NFKD", name or "")
    s = "".join(ch for ch in s if not unicodedata.combining(ch)).lower()
    s = s.replace("&", " and ").replace("'", " ")
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    s = ALIASES.get(s, s)
    tokens = [t for t in s.split() if t not in STOPWORDS]
    s = " ".join(tokens) if tokens else s
    return ALIASES.get(s, s)


def similarity(a: str, b: str) -> float:
    na, nb = normalize_team(a), normalize_team(b)
    if na == nb:
        return 100.0
    return float(max(fuzz.token_set_ratio(na, nb), fuzz.ratio(na, nb)))


def best_match(name: str, candidates: Iterable[str], threshold: float = 85.0) -> Optional[str]:
    best, score = None, 0.0
    for c in candidates:
        s = similarity(name, c)
        if s > score:
            best, score = c, s
    return best if score >= threshold else None
