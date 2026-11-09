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
    api_football_daily_budget: int = 20  # petite dose (IP partagée de Render) sur les 100 requêtes/jour du plan gratuit
    api_football_max_days_ahead: int = 1  # plan gratuit : hier, aujourd'hui, demain uniquement
    football_data_org_key: str = ""
    football_data_org_base_url: str = "https://api.football-data.org/v4"
    footballdata_io_key: str = ""  # corners/cartons rapides : PL, LaLiga, C1, C3 (gratuit, 1 000 req/mois)
    sportmonks_key: str = ""  # Écosse et Danemark (gratuit) : mi-temps, corners, cartons
    allsports_key: str = ""  # AllSportsAPI : championnats africains, cotes, scores en direct
    allsports_daily_budget: int = 300  # requêtes maximum par jour (arrêt automatique au-delà)
    allsports_live_seconds: int = 300  # intervalle minimal entre deux appels « direct »
    sportapi_key: str = ""  # SportAPI.ai : résultats rapides et direct de secours (gratuit 2 000 req/jour)
    sportapi_daily_budget: int = 220  # offre gratuite : 7 000/mois à partir du 1er décembre 2026 (220 × 31 < 7 000)
    sportapi_live_seconds: int = 360  # direct de secours : un appel toutes les 6 minutes au plus
    http_timeout: float = 25.0
    http_user_agent: str = "SAM-Prediction/1.0 (+analyse statistique)"

    # Analyse rédigée par IA (gratuite) : Google Gemini en priorité, Groq en secours. Clés côté serveur uniquement.
    ai_provider: str = "auto"  # auto | gemini | groq | off
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.1-flash-lite"
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta"
    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-120b"
    groq_base_url: str = "https://api.groq.com/openai/v1"
    groq_search_model: str = "openai/gpt-oss-120b"  # modèle Groq avec recherche web intégrée (browser_search)
    ai_daily_budget: int = 400  # générations maximum par jour (toutes sources)
    ai_cache_hours: int = 12  # une analyse IA reste valable 12 h avant le match
    ai_timeout: float = 45.0
    intl_enabled: bool = True  # sélections nationales (historique public + calendrier AllSportsAPI / SportAPI.ai)
    response_cache_seconds: int = 90  # cache des réponses publiques (0 = désactivé)
    # Alertes Web Push (clés VAPID ; la clé privée reste côté serveur)
    vapid_public_key: str = ""
    vapid_private_key: str = ""
    vapid_subject: str = "https://sam-prediction.vercel.app"
    push_quiet_start: int = 23  # pas d'alerte la nuit (heure du fuseau par défaut)
    push_quiet_end: int = 7
    assistant_token: str = ""  # secret partagé avec le frontend (en-tête X-Assistant-Token)
    assistant_member_daily: int = 25  # questions par membre et par jour
    assistant_max_steps: int = 5  # appels d'outils maximum par question

    # Planification
    enable_scheduler: bool = True
    sync_interval_minutes: int = 180
    history_seasons: int = 3  # saison en cours + 2 précédentes

    default_timezone: str = "Africa/Bamako"


@lru_cache
def get_settings() -> Settings:
    return Settings()
