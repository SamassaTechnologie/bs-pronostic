"""Synchronisation des fournisseurs vers la base de données.

* Chaque étape est journalisée dans `sync_runs` (succès, erreurs réelles, volume).
* En cas d'indisponibilité d'une source, les données existantes sont conservées
  et la date de dernière actualisation réussie reste affichée.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Callable, Iterable, Optional

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import ApiUsage, Competition, Injury, Match, OddsQuote, SyncRun, Team, TeamAlias, utcnow
from ..providers.api_football import ApiFootball
from ..providers.base import MatchRecord, OddsRecord, ProviderError
from ..providers.football_data_co_uk import FootballDataCoUk, current_season_start, internal_maps
from ..providers.football_data_org import FootballDataOrg
from ..providers.names import normalize_team, similarity
from .settings_service import get_provider_flags, get_selection_settings

log = logging.getLogger("sam.sync")
UTC = timezone.utc

MATCH_FIELDS = ("home_goals", "away_goals", "ht_home_goals", "ht_away_goals", "home_corners", "away_corners",
                "home_yellow", "away_yellow", "home_red", "away_red", "home_shots", "away_shots", "home_sot",
                "away_sot", "referee")


# ---------------------------------------------------------------------------
# Résolution des équipes et des matchs
# ---------------------------------------------------------------------------

class TeamResolver:
    def __init__(self, db: Session):
        self.db = db
        self.cache: dict = {}

    def resolve(self, name: str, country: str, source: str, ext_id: Optional[int] = None) -> Team:
        norm = normalize_team(name)
        key = (source, country, norm, ext_id)
        if key in self.cache:
            return self.cache[key]
        db = self.db
        team = None
        if ext_id is not None and source == "api_football":
            team = db.scalar(select(Team).where(Team.api_football_id == ext_id))
        elif ext_id is not None and source == "football_data_org":
            team = db.scalar(select(Team).where(Team.fdorg_id == ext_id))
        if team is None:
            alias = db.scalar(select(TeamAlias).where(TeamAlias.source == source, TeamAlias.country == country,
                                                      TeamAlias.alias_norm == norm))
            if alias:
                team = db.get(Team, alias.team_id)
        if team is None:
            team = db.scalar(select(Team).where(Team.country == country, Team.norm_name == norm))
        if team is None:
            team = Team(name=name.strip(), norm_name=norm, country=country)
            db.add(team)
            db.flush()
        if ext_id is not None:
            if source == "api_football" and team.api_football_id is None:
                team.api_football_id = ext_id
            if source == "football_data_org" and team.fdorg_id is None:
                team.fdorg_id = ext_id
        exists = db.scalar(select(TeamAlias.id).where(TeamAlias.source == source, TeamAlias.country == country,
                                                      TeamAlias.alias_norm == norm))
        if exists is None:
            db.add(TeamAlias(team_id=team.id, source=source, country=country, alias=name.strip(), alias_norm=norm))
            db.flush()
        self.cache[key] = team
        return team


class MatchIndex:
    """Index en mémoire des matchs d'une compétition (évite une requête par ligne)."""

    def __init__(self, db: Session, competition_id: int):
        self.by_pair: dict = defaultdict(list)
        self.by_fixture: dict = {}
        for m in db.scalars(select(Match).where(Match.competition_id == competition_id)).unique().all():
            self.add(m)

    def add(self, m: Match) -> None:
        self.by_pair[(m.home_team_id, m.away_team_id)].append(m)
        if m.api_football_fixture_id:
            self.by_fixture[m.api_football_fixture_id] = m

    def find(self, home_id: int, away_id: int, kickoff: datetime, status: str,
             fixture_id: Optional[int] = None) -> Optional[Match]:
        if fixture_id and fixture_id in self.by_fixture:
            return self.by_fixture[fixture_id]
        cands = self.by_pair.get((home_id, away_id), [])
        near = [m for m in cands if abs(m.kickoff - kickoff) <= timedelta(hours=36)]
        if not near and status == "FINISHED":  # match reprogrammé
            near = [m for m in cands if m.status != "FINISHED" and abs(m.kickoff - kickoff) <= timedelta(days=60)]
        return min(near, key=lambda m: abs(m.kickoff - kickoff)) if near else None


def upsert_match(db: Session, comp: Competition, rec: MatchRecord, resolver: TeamResolver,
                 index: MatchIndex) -> Optional[Match]:
    home = resolver.resolve(rec.home_name, comp.country, rec.source, rec.home_ext_id)
    away = resolver.resolve(rec.away_name, comp.country, rec.source, rec.away_ext_id)
    if home.id == away.id:
        return None
    m = index.find(home.id, away.id, rec.kickoff, rec.status, rec.fixture_ext_id)
    if m is None:
        m = Match(competition_id=comp.id, home_team_id=home.id, away_team_id=away.id, kickoff=rec.kickoff,
                  status=rec.status, source=rec.source, season=rec.season, source_ref=rec.source_ref)
        db.add(m)
        db.flush()
        index.add(m)
    else:
        if m.status != "FINISHED" or rec.status == "FINISHED":
            m.status = rec.status
        if m.kickoff != rec.kickoff and (rec.status != "FINISHED" or m.status != "FINISHED"):
            clash = [x for x in index.by_pair.get((home.id, away.id), []) if x is not m and x.kickoff == rec.kickoff]
            if not clash:
                m.kickoff = rec.kickoff
    for f in MATCH_FIELDS:
        v = getattr(rec, f)
        if v is not None:
            setattr(m, f, v)
    if rec.season:
        m.season = rec.season
    if rec.source == "api_football" and rec.fixture_ext_id:
        m.api_football_fixture_id = rec.fixture_ext_id
        index.by_fixture[rec.fixture_ext_id] = m
    if rec.odds:
        save_odds(db, m.id, rec.odds, rec.source)
    return m


def save_odds(db: Session, match_id: int, odds: Iterable[OddsRecord], source: str) -> int:
    existing = {(o.market_key, o.bookmaker): o for o in
                db.scalars(select(OddsQuote).where(OddsQuote.match_id == match_id, OddsQuote.source == source))}
    now = utcnow()
    n = 0
    for o in odds:
        q = existing.get((o.market_key, o.bookmaker))
        if q is None:
            q = OddsQuote(match_id=match_id, market_key=o.market_key, bookmaker=o.bookmaker, price=o.price,
                          source=source, collected_at=now)
            db.add(q)
            existing[(o.market_key, o.bookmaker)] = q
        else:
            q.price = o.price
            q.collected_at = now
        n += 1
    return n


# ---------------------------------------------------------------------------
# Journalisation
# ---------------------------------------------------------------------------

def _run(db: Session, provider: str, kind: str, fn: Callable[[SyncRun], tuple[int, str]]) -> dict:
    run = SyncRun(provider=provider, kind=kind, started_at=utcnow(), status="running")
    db.add(run)
    db.commit()
    try:
        items, msg = fn(run)
        run.status, run.items, run.message = "ok", items, msg
        db.commit()
    except ProviderError as exc:
        db.rollback()
        run = db.merge(run)
        run.status, run.message = "error", str(exc)
        db.commit()
        log.warning("Synchro %s/%s : %s", provider, kind, exc)
    except Exception as exc:  # erreur inattendue : journalisée, l'application continue
        db.rollback()
        run = db.merge(run)
        run.status, run.message = "error", f"Erreur interne : {exc}"
        db.commit()
        log.exception("Synchro %s/%s", provider, kind)
    run.finished_at = utcnow()
    db.commit()
    return {"provider": provider, "kind": kind, "status": run.status, "items": run.items, "message": run.message}


def _finished_count(db: Session, comp_id: int, season: str) -> int:
    return db.scalar(select(func.count(Match.id)).where(Match.competition_id == comp_id, Match.season == season,
                                                        Match.status == "FINISHED")) or 0


def _api_usage_today(db: Session, provider: str) -> int:
    row = db.get(ApiUsage, (provider, date.today().isoformat()))
    return row.requests if row else 0


def _add_api_usage(db: Session, provider: str, n: int) -> None:
    if n <= 0:
        return
    key = (provider, date.today().isoformat())
    row = db.get(ApiUsage, key)
    if row is None:
        db.add(ApiUsage(provider=provider, day=key[1], requests=n))
    else:
        row.requests += n
    db.commit()


# ---------------------------------------------------------------------------
# football-data.co.uk
# ---------------------------------------------------------------------------

def _fdcuk_history(db: Session, fd: FootballDataCoUk, comps: list[Competition], now: datetime, force: bool) -> dict:
    def work(run: SyncRun) -> tuple[int, str]:
        resolver = TeamResolver(db)
        n_seasons = get_settings().history_seasons
        total, errors = 0, []
        for comp in comps:
            index = MatchIndex(db, comp.id)
            if comp.fdcuk_extra:
                try:
                    recs = fd.extra_results(comp.fdcuk_code, comp.code, now.year - n_seasons)
                    for r in recs:
                        upsert_match(db, comp, r, resolver, index)
                    db.commit()
                    total += len(recs)
                except ProviderError as exc:
                    db.rollback()
                    errors.append(f"{comp.name} : {exc}")
                continue
            cur = current_season_start(now)
            for y in range(cur, cur - n_seasons, -1):
                label = f"{y}-{y + 1}"
                if y != cur and not force and _finished_count(db, comp.id, label) >= 150:
                    continue  # saison passée déjà complète en base
                try:
                    recs = fd.season_results(comp.fdcuk_code, y, comp.code)
                    for r in recs:
                        upsert_match(db, comp, r, resolver, index)
                    db.commit()
                    total += len(recs)
                except ProviderError as exc:
                    db.rollback()
                    resolver.cache.clear()
                    index = MatchIndex(db, comp.id)
                    if "introuvable" not in str(exc):  # fichier absent : saison non publiée / non couverte
                        errors.append(f"{comp.name} {label} : {exc}")
        msg = f"{total} résultats traités pour {len(comps)} compétitions"
        if errors:
            msg += " — erreurs : " + " | ".join(errors[:5])
            if total == 0:
                raise ProviderError(msg)
        return total, msg

    return _run(db, fd.name, "historique", work)


def _fdcuk_upcoming(db: Session, fd: FootballDataCoUk, comps: list[Competition], now: datetime) -> dict:
    def work(run: SyncRun) -> tuple[int, str]:
        div_map, country_map = internal_maps(comps)
        by_code = {c.code: c for c in comps}
        recs: list[MatchRecord] = []
        if div_map:
            recs += fd.upcoming_main(div_map)
        if country_map:
            recs += fd.upcoming_extra(country_map)
        resolver = TeamResolver(db)
        indexes: dict[int, MatchIndex] = {}
        n = 0
        for r in recs:
            if r.kickoff < now - timedelta(hours=3):
                continue
            comp = by_code[r.competition_code]
            idx = indexes.setdefault(comp.id, MatchIndex(db, comp.id))
            if upsert_match(db, comp, r, resolver, idx):
                n += 1
        db.commit()
        return n, f"{n} matchs à venir (avec cotes quand disponibles)"

    return _run(db, fd.name, "calendrier", work)


# ---------------------------------------------------------------------------
# API-Football
# ---------------------------------------------------------------------------

def _season_year(comp: Competition, now: datetime) -> int:
    return now.year if comp.calendar_year else current_season_start(now)


def _af_history(db: Session, af: ApiFootball, comps: list[Competition], now: datetime, force: bool) -> dict:
    def work(run: SyncRun) -> tuple[int, str]:
        resolver = TeamResolver(db)
        total = 0
        for comp in comps:
            index = MatchIndex(db, comp.id)
            cur = _season_year(comp, now)
            for y in (cur, cur - 1):
                label = str(y)
                if y != cur and not force and _finished_count(db, comp.id, label) >= 100:
                    continue
                fixtures = af.fixtures_by_league(comp.api_football_id, y)
                for fx in fixtures:
                    rec = af.to_record(fx, comp.code)
                    if rec:
                        upsert_match(db, comp, rec, resolver, index)
                        total += 1
                db.commit()
        return total, f"{total} matchs traités ({af.requests_made} requêtes)"

    return _run(db, af.name, "historique", work)


def _af_fixtures(db: Session, af: ApiFootball, comps: list[Competition], now: datetime, days_ahead: int) -> dict:
    """Calendrier par date. Compétitions « API-Football » : création des matchs.
    Autres compétitions : rattachement de l'identifiant API-Football (pour blessures et cotes)."""

    def work(run: SyncRun) -> tuple[int, str]:
        by_league = {c.api_football_id: c for c in comps if c.api_football_id}
        resolver = TeamResolver(db)
        indexes: dict[int, MatchIndex] = {}
        created, linked = 0, 0
        skipped: list[str] = []
        for d in range(-1, days_ahead + 1):
            day = (now + timedelta(days=d)).date().isoformat()
            try:
                fixtures = af.fixtures_by_date(day)
            except ProviderError as exc:
                if any(w in str(exc).lower() for w in ("quota", "budget", "access:", "suspended", "token")):
                    raise  # problème de compte : inutile d'insister sur les autres dates
                skipped.append(f"{day} ({exc})")  # ex. plan gratuit limité à hier → demain
                continue
            for fx in fixtures:
                comp = by_league.get((fx.get("league") or {}).get("id"))
                if comp is None:
                    continue
                rec = af.to_record(fx, comp.code)
                if rec is None:
                    continue
                idx = indexes.setdefault(comp.id, MatchIndex(db, comp.id))
                if comp.primary_source == "api_football":
                    if upsert_match(db, comp, rec, resolver, idx):
                        created += 1
                elif link_fixture(db, comp, rec):
                    linked += 1
            db.commit()
        msg = f"{created} matchs mis à jour, {linked} rattachés ({af.requests_made} requêtes)"
        if skipped:
            msg += f" ; dates non couvertes par le plan : {len(skipped)} — " + skipped[0]
            if created + linked == 0 and len(skipped) == days_ahead + 2:
                raise ProviderError(msg)
        return created + linked, msg

    return _run(db, af.name, "calendrier", work)


def link_fixture(db: Session, comp: Competition, rec: MatchRecord) -> Optional[Match]:
    """Rattache un match API-Football à un match existant (même jour, noms proches)."""
    cands = db.scalars(select(Match).where(
        Match.competition_id == comp.id,
        Match.kickoff >= rec.kickoff - timedelta(hours=30),
        Match.kickoff <= rec.kickoff + timedelta(hours=30))).unique().all()
    best, best_score = None, 0.0
    for m in cands:
        s = min(similarity(rec.home_name, m.home_team.name), similarity(rec.away_name, m.away_team.name))
        if s > best_score:
            best, best_score = m, s
    if best is None or best_score < 80:
        return None
    best.api_football_fixture_id = rec.fixture_ext_id
    for team, ext in ((best.home_team, rec.home_ext_id), (best.away_team, rec.away_ext_id)):
        if ext and team.api_football_id is None:
            clash = db.scalar(select(Team.id).where(Team.api_football_id == ext))
            if clash is None:
                team.api_football_id = ext
    return best


def _af_enrich(db: Session, af: ApiFootball, now: datetime, max_fixtures: int) -> dict:
    """Blessures/suspensions et cotes multi-marchés pour les matchs des 48 prochaines heures."""

    def work(run: SyncRun) -> tuple[int, str]:
        ms = db.scalars(select(Match).where(
            Match.api_football_fixture_id.is_not(None), Match.status == "SCHEDULED",
            Match.kickoff >= now, Match.kickoff <= now + timedelta(hours=48))
            .order_by(Match.kickoff)).unique().all()
        todo = [m for m in ms if m.enriched_at is None or m.enriched_at < now - timedelta(hours=12)][:max_fixtures]
        n_inj, n_odds, done, errors = 0, 0, 0, []
        for m in todo:
            try:
                injuries = af.injuries_for_fixture(m.api_football_fixture_id)
                odds = af.odds_for_fixture(m.api_football_fixture_id)
            except ProviderError as exc:
                db.rollback()
                errors.append(str(exc))
                if any(w in str(exc).lower() for w in ("budget", "access:", "suspended", "token")):
                    break  # problème de compte : on s'arrête
                continue
            db.execute(delete(Injury).where(Injury.match_id == m.id, Injury.source == af.name))
            for inj in injuries:
                team_id = (m.home_team_id if (inj.team_ext_id and inj.team_ext_id == m.home_team.api_football_id)
                           or similarity(inj.team_name, m.home_team.name) >= 80 else m.away_team_id)
                db.add(Injury(match_id=m.id, team_id=team_id, player=inj.player, kind=inj.kind,
                              reason=inj.reason, source=af.name))
            n_inj += len(injuries)
            n_odds += save_odds(db, m.id, odds, af.name)
            m.enriched_at = utcnow()
            db.commit()
            done += 1
        msg = f"{done} matchs enrichis : {n_inj} absences, {n_odds} cotes ({af.requests_made} requêtes)"
        if errors:
            msg += f" ; {len(errors)} échec(s) : {errors[0]}"
            if done == 0:
                raise ProviderError(msg)
        return done, msg

    return _run(db, af.name, "blessures-cotes", work)


# ---------------------------------------------------------------------------
# football-data.org
# ---------------------------------------------------------------------------

def _fo_history(db: Session, fo: FootballDataOrg, comps: list[Competition], now: datetime, force: bool) -> dict:
    def work(run: SyncRun) -> tuple[int, str]:
        resolver = TeamResolver(db)
        total = 0
        for comp in comps:
            index = MatchIndex(db, comp.id)
            cur = _season_year(comp, now)
            for y in (cur, cur - 1):
                if y != cur and not force and db.scalar(select(func.count(Match.id)).where(
                        Match.competition_id == comp.id, Match.status == "FINISHED",
                        Match.season.like(f"{y}%"))) >= 100:
                    continue
                for m in fo.competition_matches(comp.fdorg_code, y):
                    rec = fo.to_record(m, comp.code)
                    if rec:
                        upsert_match(db, comp, rec, resolver, index)
                        total += 1
                db.commit()
        return total, f"{total} matchs traités"

    return _run(db, fo.name, "historique", work)


def _fo_upcoming(db: Session, fo: FootballDataOrg, comps: list[Competition], now: datetime, days_ahead: int) -> dict:
    def work(run: SyncRun) -> tuple[int, str]:
        by_code = {c.fdorg_code: c for c in comps}
        resolver = TeamResolver(db)
        indexes: dict[int, MatchIndex] = {}
        n = 0
        d_from = (now - timedelta(days=1)).date().isoformat()
        d_to = (now + timedelta(days=days_ahead + 1)).date().isoformat()  # dateTo exclusif
        for m in fo.matches_between(d_from, d_to):
            comp = by_code.get((m.get("competition") or {}).get("code"))
            if comp is None:
                continue
            rec = fo.to_record(m, comp.code)
            if rec:
                idx = indexes.setdefault(comp.id, MatchIndex(db, comp.id))
                if upsert_match(db, comp, rec, resolver, idx):
                    n += 1
        db.commit()
        return n, f"{n} matchs mis à jour"

    return _run(db, fo.name, "calendrier", work)


# ---------------------------------------------------------------------------
# Point d'entrée
# ---------------------------------------------------------------------------

def run_sync(db: Session, kinds: Iterable[str] = ("history", "upcoming", "enrich"), force: bool = False,
             now: Optional[datetime] = None) -> list[dict]:
    now = now or utcnow()
    kinds = set(kinds)
    cfg = get_settings()
    flags = get_provider_flags(db)
    sel = get_selection_settings(db)
    comps = db.scalars(select(Competition).where(Competition.enabled.is_(True))).all()
    results: list[dict] = []

    fd = FootballDataCoUk()
    fd_comps = [c for c in comps if c.primary_source == "football_data_co_uk" and c.fdcuk_code]
    if fd.is_configured() and flags["football_data_co_uk"] and fd_comps:
        if "history" in kinds:
            results.append(_fdcuk_history(db, fd, fd_comps, now, force))
        if "upcoming" in kinds:
            results.append(_fdcuk_upcoming(db, fd, fd_comps, now))

    used = _api_usage_today(db, "api_football")
    af = ApiFootball(budget_check=lambda _: used + af.requests_made < cfg.api_football_daily_budget)
    if af.is_configured() and flags["api_football"]:
        af_primary = [c for c in comps if c.primary_source == "api_football" and c.api_football_id]
        if "history" in kinds and af_primary:
            results.append(_af_history(db, af, af_primary, now, force))
        if "upcoming" in kinds and any(c.api_football_id for c in comps):
            results.append(_af_fixtures(db, af, comps, now, int(sel["days_ahead"])))
        if "enrich" in kinds:
            remaining = cfg.api_football_daily_budget - used - af.requests_made
            if remaining >= 2:
                results.append(_af_enrich(db, af, now, max_fixtures=min(10, remaining // 2)))
        _add_api_usage(db, af.name, af.requests_made)

    fo = FootballDataOrg()
    fo_comps = [c for c in comps if c.primary_source == "football_data_org" and c.fdorg_code]
    if fo.is_configured() and flags["football_data_org"] and fo_comps:
        if "history" in kinds:
            results.append(_fo_history(db, fo, fo_comps, now, force))
        if "upcoming" in kinds:
            results.append(_fo_upcoming(db, fo, fo_comps, now, int(sel["days_ahead"])))
    if not results:
        results.append({"provider": "-", "kind": "-", "status": "skipped", "items": 0,
                        "message": "Aucune source active pour les compétitions activées"})
    return results


def last_successful_sync(db: Session) -> Optional[datetime]:
    return db.scalar(select(func.max(SyncRun.finished_at)).where(SyncRun.status == "ok"))
