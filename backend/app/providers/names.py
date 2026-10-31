"""Normalisation et rapprochement des noms d'équipes entre fournisseurs."""
from __future__ import annotations

import re
import unicodedata
from typing import Iterable, Optional

from rapidfuzz import fuzz

STOPWORDS = {
    "fc", "cf", "afc", "sc", "ac", "club", "cd", "ud", "sd", "rc", "ssc", "us", "sv", "fk", "sk", "bk",
    "the", "de", "calcio", "ssd", "asd", "cfc", "kv", "krc", "rsc", "1", "sl", "ca", "osc", "ogc", "sco", "aj",
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
    # Noms longs de football-data.org
    "stade rennais 1901": "rennes", "stade rennais": "rennes", "ogc nice": "nice", "olympique lyonnais": "lyon",
    "olympique de marseille": "marseille", "strasbourg alsace": "strasbourg", "racing club de lens": "lens",
    "racing lens": "lens", "lille osc": "lille", "stade brestois 29": "brest", "stade brestois": "brest",
    "monaco": "monaco", "aj auxerre": "auxerre", "angers sco": "angers", "toulouse": "toulouse",
    "havre": "le havre", "le havre ac": "le havre", "espanyol de barcelona": "espanyol",
    "rcd espanyol de barcelona": "espanyol", "villarreal": "villarreal", "real betis balompie": "real betis",
    "club atletico de madrid": "atletico madrid", "atletico de madrid": "atletico madrid",
    "rcd mallorca": "mallorca", "real valladolid": "valladolid", "sv 07 elversberg": "elversberg",
    "1 fsv mainz 05": "mainz", "fsv mainz 05": "mainz", "mainz 05": "mainz", "tsg 1899 hoffenheim": "hoffenheim",
    "bayer 04 leverkusen": "bayer leverkusen", "vfb stuttgart": "stuttgart", "vfl wolfsburg": "wolfsburg",
    "borussia monchengladbach": "borussia monchengladbach", "1 fc union berlin": "union berlin",
    "1 fc heidenheim 1846": "heidenheim", "hamburger sv": "hamburg", "werder bremen": "werder bremen",
    "sport lisboa e benfica": "benfica", "sporting clube de portugal": "sporting cp", "fc porto": "porto",
    "casa pia ac": "casa pia", "manchester united": "manchester united", "brighton hove albion": "brighton",
    "wolverhampton wanderers": "wolverhampton wanderers", "nottingham forest": "nottingham forest",
    "afc bournemouth": "bournemouth", "sheffield united": "sheffield united", "wrexham": "wrexham",
    "internazionale milano": "inter", "fc internazionale milano": "inter", "royale union saint gilloise": "st gilloise",
    "union saint gilloise": "st gilloise", "union sg": "st gilloise", "pae olympiakos sfp": "olympiakos",
    "olympiacos": "olympiakos", "olympiakos piraeus": "olympiakos", "pae aek": "aek", "aek athens": "aek",
    "fc kobenhavn": "kobenhavn", "fc copenhagen": "kobenhavn", "copenhagen": "kobenhavn",
    "fk bodo glimt": "bodo glimt", "bodo glimt": "bodo glimt",
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
