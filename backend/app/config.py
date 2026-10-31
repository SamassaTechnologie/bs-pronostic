"""Configuration (variables d'environnement). Les clés API restent côté serveur."""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "SAM-Prédiction"
    slogan: str = "L'analyse avant le pronostic."
    environment: str = "development"

    # Base de données : PostgreSQL / Supabase en production, SQLite en local.
    database_url: str = "sqlite:///./sam_prediction.db"

    # Sécurité
    admin_api_token: str = ""  # jeton exigé par les routes /api/admin (en-tête X-Admin-Token)
    cron_secret: str = ""  # secret pour /api/cron/run (en-tête X-Cron-Secret)
    cors_origins: str = "http://localhost:3000"

    # Fournisseurs de données
    football_data_co_uk_enabled: bool = True
    football_data_co_uk_base_url: str = "https://www.football-data.co.uk"
    api_football_key: str = ""
    api_football_base_url: str = "https://v3.football.api-sports.io"
    api_football_daily_budget: int = 75  # marge confortable sur les 100 requêtes/jour du plan gratuit
    api_football_max_days_ahead: int = 1  # plan gratuit : hier, aujourd'hui, demain uniquement
    football_data_org_key: str = ""
    football_data_org_base_url: str = "https://api.football-data.org/v4"
    http_timeout: float = 25.0
    http_user_agent: str = "SAM-Prediction/1.0 (+analyse statistique)"

    # Planification
    enable_scheduler: bool = True
    sync_interval_minutes: int = 180
    history_seasons: int = 3  # saison en cours + 2 précédentes

    default_timezone: str = "Africa/Bamako"


@lru_cache
def get_settings() -> Settings:
    return Settings()
