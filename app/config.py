from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    google_sheet_id: str = Field(..., description="ID du Google Sheet (extrait de l'URL).")
    google_sheet_tab: str = Field("Sheet1", description="Nom de l'onglet à utiliser.")
    google_service_account_file: str = Field(
        "/secrets/service-account.json",
        description="Chemin vers la clé JSON du compte de service.",
    )

    col_date: str = "Date"
    col_aller: str = "Aller"
    col_retour: str = "Retour"
    date_format: str = "%Y-%m-%d"
    time_format: str = "%H:%M"

    # --- Service occasionnel (Sheet2) ---
    google_sheet_tab_occasionnel: str = "Sheet2"
    col_occ_date: str = "Date"
    col_occ_heure_depart: str = "Heure départ"
    col_occ_heure_arrivee: str = "Heure arrivée"
    col_occ_km_depart: str = "Km départ"
    col_occ_km_arrivee: str = "Km arrivée"
    col_occ_km_total: str = "Km total"
    col_occ_adultes: str = "Adultes"
    col_occ_enfants: str = "Enfants"
    max_km: int = 9_999_999
    max_passengers_occ: int = 99

    tz: str = "Europe/Paris"
    morning_cutoff_hour: int = Field(12, ge=0, le=23)

    app_password: str = Field(..., description="Mot de passe d'accès à l'app.")
    session_secret: str = Field(..., min_length=16, description="Clé de signature des cookies.")
    session_lifetime_days: int = Field(30, ge=1, le=365)

    max_passengers: int = 999


@lru_cache
def get_settings() -> Settings:
    return Settings()
