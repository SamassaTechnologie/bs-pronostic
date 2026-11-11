"""Matchs internationaux (sélections nationales) : Ligue des nations, éliminatoires CAN / Coupe du monde, amicaux…

Sources, toutes gratuites ou déjà disponibles :
* Historique : jeu de données public « International football results » (GitHub, martj42), mis à jour régulièrement
  par son auteur ; seules les sélections reconnues (liste de app/data/intl_fr.json) sont importées.
* Calendrier et direct : AllSportsAPI tant que l'abonnement est actif, puis SportAPI.ai (offre gratuite).

Les noms des sélections sont stockés en anglais (comme dans les sources, pour les rapprocher) et affichés en français.
Aucune donnée n'est inventée : une sélection sans historique suffisant reste en « Données insuffisantes ».
"""
from __future__ import annotations

import csv
import io
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Optional

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import Competition, Match, Setting, SyncRun
from ..providers.base import MatchRecord
from ..providers.names import similarity

log = logging.getLogger("sam.intl")
UTC = timezone.utc
CODE = "INT"
COUNTRY = "Sélections"
SOURCE = "intl_results"
CSV_URL = "https://raw.githubusercontent.com/martj42/international_results/master/results.csv"
SINCE = "2021-01-01"

# Graphies des fournisseurs → nom du jeu de données historique
ALIASES = {
    "cote d'ivoire": "Ivory Coast", "côte d'ivoire": "Ivory Coast", "congo dr": "DR Congo", "dr congo": "DR Congo",
    "democratic republic of the congo": "DR Congo", "congo republic": "Congo", "korea republic": "South Korea",
    "korea dpr": "North Korea", "usa": "United States", "united states of america": "United States",
    "bosnia & herzegovina": "Bosnia and Herzegovina", "bosnia-herzegovina": "Bosnia and Herzegovina",
    "türkiye": "Turkey", "turkiye": "Turkey", "czechia": "Czech Republic", "cape verde islands": "Cape Verde",
    "cabo verde": "Cape Verde", "ireland": "Republic of Ireland", "fyr macedonia": "North Macedonia",
    "macedonia": "North Macedonia", "swaziland": "Eswatini", "ir iran": "Iran", "china pr": "China",
    "kyrgyz republic": "Kyrgyzstan", "chinese taipei": "Taiwan", "sao tome and principe": "São Tomé and Príncipe",
    "st. kitts and nevis": "Saint Kitts and Nevis", "st kitts and nevis": "Saint Kitts and Nevis",
    "st. lucia": "Saint Lucia", "st. vincent and the grenadines": "Saint Vincent and the Grenadines",
    "us virgin islands": "United States Virgin Islands", "the gambia": "Gambia", "timor-leste": "East Timor",
    "curacao": "Curaçao", "brunei darussalam": "Brunei", "viet nam": "Vietnam", "guinea bissau": "Guinea-Bissau",
}
# Compétitions de sélections à garder (nom de ligue des fournisseurs), puis exclusions (jeunes, femmes, clubs)
KEEP = re.compile(r"nations league|qualif|friendl|world cup|africa cup|african nations|afcon|asian cup|gold cup|"
                  r"copa am[eé]rica|euro\b|european championship|international|arab cup|gulf cup|cosafa|cecafa|"
                  r"wafu|fifa series|kings cup|king's cup", re.I)
DROP = re.compile(r"women|femin|u-?1[5-9]|u-?2[0-3]|youth|olymp|club|champions league|europa|conference|"
                  r"libertadores|sudamericana|confederation cup|caf champions|reserve|futsal|beach", re.I)


@lru_cache(maxsize=1)
def french_names() -> dict[str, str]:
    return json.loads((Path(__file__).resolve().parent.parent / "data" / "intl_fr.json").read_text(encoding="utf-8"))


def french(name: str) -> str:
    return french_names().get(name, name)


def canon(name: str) -> Optional[str]:
    """Nom du jeu de données pour une graphie de fournisseur ; None si ce n'est pas une sélection reconnue."""
    known = french_names()
    n = (name or "").strip()
    if n in known:
        return n
    low = n.lower()
    if low in ALIASES:
        return ALIASES[low]
    if low.endswith(" w") or " women" in low or re.search(r"\bu-?\d\d\b", low):
        return None
    scored = sorted(((similarity(n, k), k) for k in known), reverse=True)
    if scored and scored[0][0] >= 92 and (len(scored) == 1 or scored[0][0] - scored[1][0] >= 4):
        return scored[0][1]
    return None


def competition(db: Session) -> Optional[Competition]:
    return db.scalar(select(Competition).where(Competition.code == CODE))


def ensure_competition(db: Session) -> Competition:
    c = competition(db)
    if c is None:
        c = Competition(code=CODE, name="Matchs internationaux", country=COUNTRY, enabled=True,
                        primary_source=SOURCE, calendar_year=True)
        db.add(c)
        db.commit()
    return c


def is_international(x_league: str) -> bool:
    return bool(KEEP.search(x_league or "")) and not DROP.search(x_league or "")


def frenchify(db: Session) -> int:
    """Affichage en français ; le nom de rapprochement (norm_name, anglais) reste inchangé."""
    from ..models import Team
    n = 0
    names = french_names()
    for t in db.scalars(select(Team).where(Team.country == COUNTRY)).all():
        fr = names.get(t.name)
        if fr and fr != t.name:
            t.name = fr
            n += 1
    db.commit()
    return n


def import_history(db: Session, now: datetime, text: Optional[str] = None, recent_only: bool = False) -> tuple[int, str]:
    """Résultats officiels des sélections depuis 2021 (au plus une fois par jour)."""
    from .sync import MatchIndex, TeamResolver
    comp = ensure_competition(db)
    if text is None:
        r = httpx.get(CSV_URL, timeout=60, headers={"User-Agent": get_settings().http_user_agent})
        r.raise_for_status()
        text = r.text
    known = french_names()
    resolver, index = TeamResolver(db), MatchIndex(db, comp.id)
    # après le premier import, seuls les deux derniers mois sont relus (le reste est déjà en base)
    since = max(SINCE, (now - timedelta(days=60)).date().isoformat()) if recent_only else SINCE
    n_new = n_upd = 0
    for row in csv.DictReader(io.StringIO(text)):
        if row["date"] < since or row["home_team"] not in known or row["away_team"] not in known:
            continue
        if row["home_score"] in ("", "NA") or row["away_score"] in ("", "NA"):
            continue
        day = datetime.fromisoformat(row["date"]).replace(hour=18, tzinfo=UTC)
        if day > now:
            continue
        home = resolver.resolve(row["home_team"], COUNTRY, SOURCE)
        away = resolver.resolve(row["away_team"], COUNTRY, SOURCE)
        hg, ag = int(row["home_score"]), int(row["away_score"])
        m = index.find(home.id, away.id, day, "FINISHED")
        if m is None:
            m = Match(competition_id=comp.id, home_team_id=home.id, away_team_id=away.id, kickoff=day,
                      status="FINISHED", source=SOURCE, season=row["date"][:4], home_goals=hg, away_goals=ag,
                      source_ref=(row["tournament"] or "")[:80])
            db.add(m)
            db.flush()
            index.add(m)
            n_new += 1
        elif m.status != "FINISHED" or m.home_goals is None:
            # match du calendrier (heure réelle conservée) : seul le score officiel est repris
            m.home_goals, m.away_goals, m.status = hg, ag, "FINISHED"
            n_upd += 1
    db.commit()
    frenchify(db)
    return n_new + n_upd, f"{n_new} résultat(s) historique(s) ajouté(s), {n_upd} score(s) complété(s)"


def _upsert_fixture(db: Session, comp: Competition, rec: MatchRecord, resolver, index) -> Optional[Match]:
    from .sync import upsert_match
    h, a = canon(rec.home_name), canon(rec.away_name)
    if not h or not a:
        return None
    rec.home_name, rec.away_name, rec.competition_code = h, a, CODE
    rec.season = str(rec.kickoff.year)
    return upsert_match(db, comp, rec, resolver, index)


def fixtures_allsports(db: Session, now: datetime, days: int = 8) -> tuple[int, str]:
    from ..providers.allsports import AllSports
    from .allsports_sync import make_provider
    from .sync import MatchIndex, TeamResolver, _add_api_usage
    comp = ensure_competition(db)
    p: AllSports = make_provider(db)
    try:
        rows = p.fixtures(now.date().isoformat(), (now + timedelta(days=days)).date().isoformat())
    finally:
        _add_api_usage(db, p.name, p.requests_made)
    resolver, index = TeamResolver(db), MatchIndex(db, comp.id)
    leagues, n = set(), 0
    for x in rows:
        if not is_international(x.get("league_name") or ""):
            continue
        rec = p.to_record(x, CODE)
        if rec and _upsert_fixture(db, comp, rec, resolver, index):
            n += 1
            leagues.add(x.get("league_name"))
    db.commit()
    frenchify(db)
    return n, f"{n} match(s) de sélections ({', '.join(sorted(leagues)[:6]) or 'aucune compétition'})"


def fixtures_sportapi(db: Session, now: datetime, days: int = 3) -> tuple[int, str]:
    from .sportapi import _kickoff, fixtures_on
    from .sync import MatchIndex, TeamResolver
    comp = ensure_competition(db)
    resolver, index = TeamResolver(db), MatchIndex(db, comp.id)
    leagues, n = set(), 0
    for i in range(days):
        for x in fixtures_on(db, (now + timedelta(days=i)).date().isoformat()):
            league = x.get("league_name") or x.get("league") or ""
            ko = _kickoff(x)
            if ko is None or not is_international(league):
                continue
            st = {"FT": "FINISHED", "LIVE": "LIVE"}.get(x.get("status"), "SCHEDULED")
            rec = MatchRecord(competition_code=CODE, kickoff=ko, home_name=x.get("home_team") or "",
                              away_name=x.get("away_team") or "", status=st, source="sportapi",
                              source_ref=str(x.get("id") or ""))
            if st == "FINISHED" and x.get("home_score") is not None:
                rec.home_goals, rec.away_goals = int(x["home_score"]), int(x["away_score"])
            elif st == "FINISHED":
                continue
            if _upsert_fixture(db, comp, rec, resolver, index):
                n += 1
                leagues.add(league)
    db.commit()
    frenchify(db)
    return n, f"{n} match(s) de sélections via SportAPI.ai ({', '.join(sorted(leagues)[:6]) or 'aucune'})"


def run(db: Session, kinds: set, now: datetime, force: bool = False) -> list[dict]:
    """Étape « sélections » de la synchronisation."""
    from .settings_service import get_provider_flags
    from .sync import _run
    if not get_settings().intl_enabled:
        return []
    comp = ensure_competition(db)
    if not comp.enabled:
        return []
    out = []
    if "history" in kinds:
        memo = db.get(Setting, "intl_history")
        last = (memo.value or {}).get("at") if memo else None
        if force or not last or now - datetime.fromisoformat(last) >= timedelta(hours=20):
            def work(run_: SyncRun) -> tuple[int, str]:
                res = import_history(db, now, recent_only=bool(last))
                m = db.get(Setting, "intl_history") or Setting(key="intl_history", value={})
                m.value = {"at": now.isoformat()}
                db.merge(m)
                db.commit()
                return res
            out.append(_run(db, SOURCE, "historique", work))
    if "upcoming" in kinds:
        cfg = get_settings()
        flags = get_provider_flags(db)
        if cfg.allsports_key and flags.get("allsports", True):
            out.append(_run(db, "allsports", "sélections", lambda r: fixtures_allsports(db, now)))
        elif cfg.sportapi_key:
            out.append(_run(db, "sportapi", "sélections", lambda r: fixtures_sportapi(db, now)))
    return out
