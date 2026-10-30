"""Fournisseur football-data.co.uk (gratuit, sans clé).

Fichiers CSV publics : résultats, mi-temps, tirs, corners, cartons et cotes de
plusieurs bookmakers pour ~22 divisions européennes, plus des « nouvelles
ligues » (résultats + cotes de clôture). Calendrier de la semaine avec cotes
dans `fixtures.csv`.

Notes du site :
* Date au format jj/mm/aa ; l'heure est celle du Royaume-Uni (convertie ici en UTC).
* Cartons : pour les matchs anglais et écossais, le premier jaune d'un joueur
  expulsé pour deux jaunes n'est pas compté ; pour les autres pays il l'est.
"""
from __future__ import annotations

import csv
import io
import re
from datetime import datetime, time, timezone
from typing import Iterable, Optional
from zoneinfo import ZoneInfo

from .base import MatchRecord, OddsRecord, Provider, ProviderError

UTC = timezone.utc
LONDON = ZoneInfo("Europe/London")

# code football-data.co.uk -> (nom, pays)
MAIN_DIVISIONS = {
    "E0": ("Premier League", "Angleterre"), "E1": ("Championship", "Angleterre"),
    "E2": ("League One", "Angleterre"), "E3": ("League Two", "Angleterre"), "EC": ("National League", "Angleterre"),
    "SC0": ("Premiership", "Écosse"), "SC1": ("Championship", "Écosse"), "SC2": ("League One", "Écosse"),
    "SC3": ("League Two", "Écosse"), "D1": ("Bundesliga", "Allemagne"), "D2": ("2. Bundesliga", "Allemagne"),
    "I1": ("Serie A", "Italie"), "I2": ("Serie B", "Italie"), "SP1": ("LaLiga", "Espagne"),
    "SP2": ("LaLiga 2", "Espagne"), "F1": ("Ligue 1", "France"), "F2": ("Ligue 2", "France"),
    "N1": ("Eredivisie", "Pays-Bas"), "B1": ("Pro League", "Belgique"), "P1": ("Liga Portugal", "Portugal"),
    "T1": ("Süper Lig", "Turquie"), "G1": ("Super League", "Grèce"),
}

# « Nouvelles ligues » : un fichier par pays (toutes saisons), saison = année civile pour la plupart.
EXTRA_LEAGUES = {
    "ARG": ("Liga Profesional", "Argentine", "Argentina"), "AUT": ("Bundesliga", "Autriche", "Austria"),
    "BRA": ("Série A", "Brésil", "Brazil"), "CHN": ("Super League", "Chine", "China"),
    "DNK": ("Superliga", "Danemark", "Denmark"), "FIN": ("Veikkausliiga", "Finlande", "Finland"),
    "IRL": ("Premier Division", "Irlande", "Ireland"), "JPN": ("J1 League", "Japon", "Japan"),
    "MEX": ("Liga MX", "Mexique", "Mexico"), "NOR": ("Eliteserien", "Norvège", "Norway"),
    "POL": ("Ekstraklasa", "Pologne", "Poland"), "ROU": ("Liga I", "Roumanie", "Romania"),
    "SWE": ("Allsvenskan", "Suède", "Sweden"), "SWZ": ("Super League", "Suisse", "Switzerland"),
    "USA": ("MLS", "États-Unis", "USA"),
}

ODDS_1X2 = [
    ("Moyenne", ("AvgH", "AvgD", "AvgA")), ("Bet365", ("B365H", "B365D", "B365A")),
    ("Pinnacle", ("PSH", "PSD", "PSA")), ("Pinnacle", ("PH", "PD", "PA")),
    ("Max", ("MaxH", "MaxD", "MaxA")), ("Moyenne", ("BbAvH", "BbAvD", "BbAvA")),
]
ODDS_OU25 = [
    ("Moyenne", ("Avg>2.5", "Avg<2.5")), ("Bet365", ("B365>2.5", "B365<2.5")),
    ("Pinnacle", ("P>2.5", "P<2.5")), ("Max", ("Max>2.5", "Max<2.5")), ("Moyenne", ("BbAv>2.5", "BbAv<2.5")),
]


def season_code(start_year: int) -> str:
    return f"{start_year % 100:02d}{(start_year + 1) % 100:02d}"


def season_label(start_year: int) -> str:
    return f"{start_year}-{start_year + 1}"


def current_season_start(now: datetime) -> int:
    return now.year if now.month >= 7 else now.year - 1


def _int(v: Optional[str]) -> Optional[int]:
    if v is None:
        return None
    v = str(v).strip()
    if v == "" or v.upper() in ("NA", "NAN"):
        return None
    try:
        return int(float(v))
    except ValueError:
        return None


def _float(v: Optional[str]) -> Optional[float]:
    try:
        x = float(str(v).strip())
        return x if x > 1.0 else None
    except (TypeError, ValueError):
        return None


def parse_kickoff(date_s: str, time_s: Optional[str]) -> datetime:
    date_s = (date_s or "").strip()
    d = None
    for fmt in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d"):
        try:
            d = datetime.strptime(date_s, fmt).date()
            break
        except ValueError:
            continue
    if d is None:
        raise ValueError(f"Date illisible : {date_s!r}")
    m = re.match(r"^\s*(\d{1,2}):(\d{2})", time_s or "")
    t = time(int(m.group(1)), int(m.group(2))) if m else time(12, 0)
    return datetime.combine(d, t, tzinfo=LONDON).astimezone(UTC)


def _odds(row: dict, groups, keys) -> list[OddsRecord]:
    out, seen = [], set()
    for bookmaker, cols in groups:
        prices = [_float(row.get(c)) for c in cols]
        if all(prices) and bookmaker not in seen:
            seen.add(bookmaker)
            out.extend(OddsRecord(k, p, bookmaker) for k, p in zip(keys, prices))
    return out


def decode(content: bytes) -> str:
    for enc in ("utf-8-sig", "latin-1"):
        try:
            return content.decode(enc)
        except UnicodeDecodeError:
            continue
    return content.decode("utf-8", errors="replace")


def parse_main_csv(text: str, div_map: dict[str, str], with_odds: bool, season: Optional[str] = None,
                   source: str = "football_data_co_uk") -> list[MatchRecord]:
    """CSV « principal » (résultats d'une division ou fixtures.csv multi-divisions)."""
    out: list[MatchRecord] = []
    for row in csv.DictReader(io.StringIO(text)):
        row = {(k or "").strip(): v for k, v in row.items()}
        div = (row.get("Div") or "").strip()
        comp = div_map.get(div)
        if not comp or not row.get("HomeTeam") or not row.get("AwayTeam") or not row.get("Date"):
            continue
        try:
            ko = parse_kickoff(row["Date"], row.get("Time"))
        except ValueError:
            continue
        hg, ag = _int(row.get("FTHG")), _int(row.get("FTAG"))
        finished = hg is not None and ag is not None
        rec = MatchRecord(
            competition_code=comp, kickoff=ko, home_name=row["HomeTeam"].strip(),
            away_name=row["AwayTeam"].strip(), status="FINISHED" if finished else "SCHEDULED", source=source,
            season=season or season_label(current_season_start(ko)),
            home_goals=hg, away_goals=ag, ht_home_goals=_int(row.get("HTHG")), ht_away_goals=_int(row.get("HTAG")),
            home_corners=_int(row.get("HC")), away_corners=_int(row.get("AC")),
            home_yellow=_int(row.get("HY")), away_yellow=_int(row.get("AY")),
            home_red=_int(row.get("HR")), away_red=_int(row.get("AR")),
            home_shots=_int(row.get("HS")), away_shots=_int(row.get("AS")),
            home_sot=_int(row.get("HST")), away_sot=_int(row.get("AST")),
            referee=(row.get("Referee") or "").strip() or None,
            source_ref=f"{div}:{row['Date'].strip()}:{row['HomeTeam'].strip()}",
        )
        if with_odds and not finished:
            rec.odds = _odds(row, ODDS_1X2, ("1", "X", "2")) + _odds(row, ODDS_OU25, ("O2.5", "U2.5"))
        out.append(rec)
    return out


def parse_extra_csv(text: str, country_map: dict[str, str], with_odds: bool, min_season_year: int = 0,
                    source: str = "football_data_co_uk") -> list[MatchRecord]:
    """CSV des « nouvelles ligues » (Country, League, Season, Date, Time, Home, Away, HG, AG…)."""
    out: list[MatchRecord] = []
    for row in csv.DictReader(io.StringIO(text)):
        row = {(k or "").strip(): v for k, v in row.items()}
        comp = country_map.get((row.get("Country") or "").strip())
        if not comp or not row.get("Home") or not row.get("Away") or not row.get("Date"):
            continue
        season = (row.get("Season") or "").strip().replace("/", "-")
        m = re.match(r"(\d{4})", season)
        if m and int(m.group(1)) < min_season_year:
            continue
        try:
            ko = parse_kickoff(row["Date"], row.get("Time"))
        except ValueError:
            continue
        hg, ag = _int(row.get("HG")), _int(row.get("AG"))
        finished = hg is not None and ag is not None
        rec = MatchRecord(
            competition_code=comp, kickoff=ko, home_name=row["Home"].strip(), away_name=row["Away"].strip(),
            status="FINISHED" if finished else "SCHEDULED", source=source, season=season or None,
            home_goals=hg, away_goals=ag,
            source_ref=f"{row.get('Country', '').strip()}:{row['Date'].strip()}:{row['Home'].strip()}",
        )
        if with_odds and not finished:
            rec.odds = _odds(row, ODDS_1X2, ("1", "X", "2"))
        out.append(rec)
    return out


class FootballDataCoUk(Provider):
    name = "football_data_co_uk"
    label = "football-data.co.uk"
    requires_key = False
    website = "https://www.football-data.co.uk"
    capabilities = ("historique", "calendrier", "cotes 1X2 et +/-2,5", "mi-temps", "corners", "cartons")

    def is_configured(self) -> bool:
        return bool(self.settings.football_data_co_uk_enabled)

    def _get_text(self, path: str) -> str:
        url = self.settings.football_data_co_uk_base_url.rstrip("/") + path
        r = self._request(url, count=False)
        if r.status_code == 404:
            raise ProviderError(f"football-data.co.uk : fichier introuvable ({path})")
        if r.status_code >= 400:
            raise ProviderError(f"football-data.co.uk : HTTP {r.status_code} sur {path}")
        return decode(r.content)

    def season_results(self, div: str, start_year: int, internal_code: str) -> list[MatchRecord]:
        text = self._get_text(f"/mmz4281/{season_code(start_year)}/{div}.csv")
        return parse_main_csv(text, {div: internal_code}, with_odds=False, season=season_label(start_year),
                              source=self.name)

    def extra_results(self, code: str, internal_code: str, min_season_year: int) -> list[MatchRecord]:
        country = EXTRA_LEAGUES.get(code, ("", "", code))[2]
        text = self._get_text(f"/new/{code}.csv")
        return parse_extra_csv(text, {country: internal_code}, with_odds=False, min_season_year=min_season_year,
                               source=self.name)

    def upcoming_main(self, div_map: dict[str, str]) -> list[MatchRecord]:
        return parse_main_csv(self._get_text("/fixtures.csv"), div_map, with_odds=True, source=self.name)

    def upcoming_extra(self, country_map: dict[str, str]) -> list[MatchRecord]:
        return parse_extra_csv(self._get_text("/new_league_fixtures.csv"), country_map, with_odds=True,
                               source=self.name)

    def test_connection(self) -> dict:
        try:
            text = self._get_text("/fixtures.csv")
        except ProviderError as exc:
            return {"ok": False, "message": str(exc)}
        rows = max(0, len([ln for ln in text.splitlines() if ln.strip()]) - 1)
        return {"ok": True, "message": f"Connexion réussie : {rows} matchs à venir dans fixtures.csv"}


def internal_maps(competitions: Iterable) -> tuple[dict[str, str], dict[str, str]]:
    """(div -> code interne, pays CSV -> code interne) pour les compétitions actives."""
    div_map, country_map = {}, {}
    for c in competitions:
        if not c.fdcuk_code:
            continue
        if c.fdcuk_extra:
            country_map[EXTRA_LEAGUES.get(c.fdcuk_code, ("", "", c.fdcuk_code))[2]] = c.code
        else:
            div_map[c.fdcuk_code] = c.code
    return div_map, country_map
