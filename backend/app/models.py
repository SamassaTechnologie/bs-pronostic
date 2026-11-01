"""Schéma de la base de données (SQLAlchemy 2, compatible PostgreSQL/Supabase et SQLite)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text,
                        UniqueConstraint, event, inspect)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UTCDateTime(TypeDecorator):
    """Dates toujours en UTC « aware », quel que soit le moteur SQL."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        value = value.astimezone(timezone.utc)
        return value.replace(tzinfo=None) if dialect.name == "sqlite" else value

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class Competition(Base):
    __tablename__ = "competitions"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    country: Mapped[str] = mapped_column(String(80))
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    primary_source: Mapped[str] = mapped_column(String(40), default="football_data_co_uk")
    fdcuk_code: Mapped[Optional[str]] = mapped_column(String(16))
    fdcuk_extra: Mapped[bool] = mapped_column(Boolean, default=False)
    api_football_id: Mapped[Optional[int]] = mapped_column(Integer)
    fdorg_code: Mapped[Optional[str]] = mapped_column(String(16))
    calendar_year: Mapped[bool] = mapped_column(Boolean, default=False)  # saison = année civile
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Team(Base):
    __tablename__ = "teams"
    __table_args__ = (UniqueConstraint("country", "norm_name", name="uq_team_country_name"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    norm_name: Mapped[str] = mapped_column(String(120), index=True)
    country: Mapped[str] = mapped_column(String(80))
    api_football_id: Mapped[Optional[int]] = mapped_column(Integer, index=True)
    fdorg_id: Mapped[Optional[int]] = mapped_column(Integer, index=True)


class TeamAlias(Base):
    __tablename__ = "team_aliases"
    __table_args__ = (UniqueConstraint("source", "country", "alias_norm", name="uq_alias"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"), index=True)
    source: Mapped[str] = mapped_column(String(40))
    country: Mapped[str] = mapped_column(String(80))
    alias: Mapped[str] = mapped_column(String(120))
    alias_norm: Mapped[str] = mapped_column(String(120))


class Match(Base):
    __tablename__ = "matches"
    __table_args__ = (
        UniqueConstraint("competition_id", "home_team_id", "away_team_id", "kickoff", name="uq_match"),
        Index("ix_match_comp_kickoff", "competition_id", "kickoff"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    competition_id: Mapped[int] = mapped_column(ForeignKey("competitions.id", ondelete="CASCADE"))
    season: Mapped[Optional[str]] = mapped_column(String(9))
    kickoff: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    home_team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), index=True)
    away_team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), index=True)
    status: Mapped[str] = mapped_column(String(16), default="SCHEDULED", index=True)
    home_goals: Mapped[Optional[int]] = mapped_column(Integer)
    away_goals: Mapped[Optional[int]] = mapped_column(Integer)
    ht_home_goals: Mapped[Optional[int]] = mapped_column(Integer)
    ht_away_goals: Mapped[Optional[int]] = mapped_column(Integer)
    home_corners: Mapped[Optional[int]] = mapped_column(Integer)
    away_corners: Mapped[Optional[int]] = mapped_column(Integer)
    home_yellow: Mapped[Optional[int]] = mapped_column(Integer)
    away_yellow: Mapped[Optional[int]] = mapped_column(Integer)
    home_red: Mapped[Optional[int]] = mapped_column(Integer)
    away_red: Mapped[Optional[int]] = mapped_column(Integer)
    home_shots: Mapped[Optional[int]] = mapped_column(Integer)
    away_shots: Mapped[Optional[int]] = mapped_column(Integer)
    home_sot: Mapped[Optional[int]] = mapped_column(Integer)
    away_sot: Mapped[Optional[int]] = mapped_column(Integer)
    referee: Mapped[Optional[str]] = mapped_column(String(120))
    source: Mapped[str] = mapped_column(String(40))
    source_ref: Mapped[Optional[str]] = mapped_column(String(80))
    api_football_fixture_id: Mapped[Optional[int]] = mapped_column(Integer, index=True)
    enriched_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime)  # blessures/cotes API-Football
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)

    competition: Mapped[Competition] = relationship(lazy="joined")
    home_team: Mapped[Team] = relationship(foreign_keys=[home_team_id], lazy="joined")
    away_team: Mapped[Team] = relationship(foreign_keys=[away_team_id], lazy="joined")


class OddsQuote(Base):
    __tablename__ = "odds"
    __table_args__ = (UniqueConstraint("match_id", "market_key", "bookmaker", "source", name="uq_odds"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id", ondelete="CASCADE"), index=True)
    market_key: Mapped[str] = mapped_column(String(16))
    bookmaker: Mapped[str] = mapped_column(String(40))
    price: Mapped[float] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(40))
    collected_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Injury(Base):
    __tablename__ = "injuries"
    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id", ondelete="CASCADE"), index=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"))
    player: Mapped[str] = mapped_column(String(120))
    kind: Mapped[Optional[str]] = mapped_column(String(60))
    reason: Mapped[Optional[str]] = mapped_column(String(160))
    source: Mapped[str] = mapped_column(String(40))
    fetched_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Analysis(Base):
    """Dernière analyse d'un match à venir (recalculée à chaque synchronisation)."""

    __tablename__ = "analyses"
    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id", ondelete="CASCADE"), unique=True)
    computed_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    engine_version: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16))
    match_confidence: Mapped[int] = mapped_column(Integer, default=0)
    n_picks: Mapped[int] = mapped_column(Integer, default=0)
    payload: Mapped[dict] = mapped_column(JSON)

    match: Mapped[Match] = relationship(lazy="joined")


PREDICTION_LOCKED_FIELDS = ("created_at", "match_id", "market_key", "probability", "confidence", "tier",
                            "odds", "implied_probability", "engine_version")


class Prediction(Base):
    """Historique des pronostics publiés. Les champs annoncés sont figés : seul le
    règlement (résultat) peut être complété ensuite."""

    __tablename__ = "predictions"
    __table_args__ = (UniqueConstraint("match_id", "market_key", name="uq_prediction"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id", ondelete="CASCADE"), index=True)
    market_key: Mapped[str] = mapped_column(String(16))
    market_label: Mapped[str] = mapped_column(String(80))
    probability: Mapped[float] = mapped_column(Float)
    confidence: Mapped[int] = mapped_column(Integer)
    confidence_level: Mapped[str] = mapped_column(String(16))
    tier: Mapped[str] = mapped_column(String(1))
    odds: Mapped[Optional[float]] = mapped_column(Float)
    bookmaker: Mapped[Optional[str]] = mapped_column(String(40))
    implied_probability: Mapped[Optional[float]] = mapped_column(Float)
    engine_version: Mapped[str] = mapped_column(String(32))
    explanation: Mapped[Optional[str]] = mapped_column(Text)
    featured: Mapped[bool] = mapped_column(Boolean, default=False, index=True)  # Sélection SAM du jour
    featured_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime)
    value_pick: Mapped[bool] = mapped_column(Boolean, default=False, index=True)  # Pronostic à cote
    result: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    settled_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime)

    match: Mapped[Match] = relationship(lazy="joined")


@event.listens_for(Prediction, "before_update")
def _protect_prediction(mapper, connection, target):  # pragma: no cover - exercé par les tests
    state = inspect(target)
    for f in PREDICTION_LOCKED_FIELDS:
        if state.attrs[f].history.has_changes():
            raise ValueError(f"Historique immuable : le champ « {f} » d'un pronostic publié ne peut pas être modifié")


class SyncRun(Base):
    __tablename__ = "sync_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(40), index=True)
    kind: Mapped[str] = mapped_column(String(40))
    started_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime)
    status: Mapped[str] = mapped_column(String(16), default="running")  # running | ok | error | skipped
    message: Mapped[Optional[str]] = mapped_column(Text)
    items: Mapped[int] = mapped_column(Integer, default=0)
    requests_used: Mapped[int] = mapped_column(Integer, default=0)


class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class Calibration(Base):
    __tablename__ = "calibrations"
    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    method: Mapped[str] = mapped_column(String(32), default="platt")
    n_matches: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    payload: Mapped[dict] = mapped_column(JSON)


class ApiUsage(Base):
    __tablename__ = "api_usage"
    provider: Mapped[str] = mapped_column(String(40), primary_key=True)
    day: Mapped[str] = mapped_column(String(10), primary_key=True)
    requests: Mapped[int] = mapped_column(Integer, default=0)


class AiAnalysis(Base):
    """Analyse rédigée par une IA à partir du seul dossier de données SAM (mise en cache par match)."""

    __tablename__ = "ai_analyses"
    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id", ondelete="CASCADE"), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    based_on: Mapped[Optional[datetime]] = mapped_column(UTCDateTime)  # date de l'analyse SAM utilisée
    provider: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(80))
    content: Mapped[dict] = mapped_column(JSON)
    removed: Mapped[int] = mapped_column(Integer, default=0)  # phrases écartées (chiffres non vérifiables)


class Wallet(Base):
    """Portefeuille de jetons virtuels d'un membre (section « Jouer », aucun argent réel)."""

    __tablename__ = "wallets"
    member_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(60), default="Membre")
    balance: Mapped[int] = mapped_column(Integer, default=1000)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    last_bonus: Mapped[Optional[str]] = mapped_column(String(10))  # jour du dernier bonus quotidien


class Bet(Base):
    __tablename__ = "bets"
    id: Mapped[int] = mapped_column(primary_key=True)
    member_id: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    kind: Mapped[str] = mapped_column(String(10))  # simple | combine
    stake: Mapped[int] = mapped_column(Integer)
    total_odds: Mapped[float] = mapped_column(Float)
    sam_probability: Mapped[Optional[float]] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(10), default="pending", index=True)  # pending|won|lost|void
    payout: Mapped[int] = mapped_column(Integer, default=0)
    settled_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime)

    legs: Mapped[list["BetLeg"]] = relationship(lazy="selectin", cascade="all, delete-orphan", order_by="BetLeg.id")


class BetLeg(Base):
    __tablename__ = "bet_legs"
    id: Mapped[int] = mapped_column(primary_key=True)
    bet_id: Mapped[int] = mapped_column(ForeignKey("bets.id", ondelete="CASCADE"), index=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id", ondelete="CASCADE"), index=True)
    market_key: Mapped[str] = mapped_column(String(16))
    label: Mapped[str] = mapped_column(String(80))
    odds: Mapped[float] = mapped_column(Float)
    odds_source: Mapped[str] = mapped_column(String(10))  # bookmaker | sam
    probability: Mapped[Optional[float]] = mapped_column(Float)
    result: Mapped[str] = mapped_column(String(10), default="pending")

    match: Mapped[Match] = relationship(lazy="joined")
