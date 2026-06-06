"""Base commune aux clients Google Sheets (service régulier + occasionnel).

Regroupe ce qui était dupliqué entre `sheets.py` et `occasional.py` :
connexion gspread, ouverture + cache de l'onglet, localisation des colonnes par
nom d'en-tête, et un petit retry/backoff sur les erreurs transitoires de l'API.
"""

from __future__ import annotations

import logging
import threading
import time as _time
from typing import Callable, Optional, TypeVar

import gspread
from google.oauth2.service_account import Credentials
from gspread.exceptions import APIError

from .config import Settings
from .parsing import (  # ré-export : point d'import unique pour les clients
    _normalize,
    _parse_date_loose,
    _parse_int_loose,
    _parse_time_loose,
)

__all__ = [
    "SCOPES",
    "SheetError",
    "BaseSheetClient",
    "with_retry",
    "_normalize",
    "_parse_date_loose",
    "_parse_time_loose",
    "_parse_int_loose",
]

log = logging.getLogger("pointage.sheets")

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
]


class SheetError(RuntimeError):
    """Erreur fonctionnelle remontée à l'utilisateur."""


T = TypeVar("T")


def _status_of(exc: APIError) -> Optional[int]:
    resp = getattr(exc, "response", None)
    return getattr(resp, "status_code", None)


def with_retry(func: Callable[[], T], *, tries: int = 3, base_delay: float = 0.5) -> T:
    """Exécute `func`, en réessayant sur erreurs transitoires (429 / 5xx).

    À réserver aux appels **idempotents** (lectures, ``update_cell``,
    ``batch_update``). NE PAS envelopper ``append_row`` / ``delete_rows`` : un
    5xx survenant après application créerait/supprimerait une ligne en double.
    """
    last_exc: Optional[APIError] = None
    for attempt in range(tries):
        try:
            return func()
        except APIError as exc:
            status = _status_of(exc)
            transient = status == 429 or (status is not None and status >= 500)
            if not transient:
                raise
            last_exc = exc
            if attempt < tries - 1:
                delay = base_delay * (2 ** attempt)
                log.warning("API Google %s — nouvel essai dans %.1fs", status, delay)
                _time.sleep(delay)
    assert last_exc is not None  # tries >= 1 garantit au moins une tentative
    raise last_exc


class BaseSheetClient:
    """Connexion gspread + cache de l'onglet, partagés par les deux clients.

    Le handle de l'onglet est mis en cache pour éviter de ré-ouvrir le classeur
    (appel réseau) à chaque opération. Les sous-classes mettent en cache leurs
    indices de colonnes et les rafraîchissent dans ``healthcheck``.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._lock = threading.Lock()
        self._client: Optional[gspread.Client] = None
        self._ws: Optional[gspread.Worksheet] = None

    def _tab_name(self) -> str:  # défini par la sous-classe
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Connexion
    # ------------------------------------------------------------------
    def _gspread_client(self) -> gspread.Client:
        if self._client is None:
            creds = Credentials.from_service_account_file(
                self._settings.google_service_account_file, scopes=SCOPES
            )
            self._client = gspread.authorize(creds)
        return self._client

    def _worksheet(self) -> gspread.Worksheet:
        if self._ws is None:
            tab = self._tab_name()
            sh = with_retry(
                lambda: self._gspread_client().open_by_key(self._settings.google_sheet_id)
            )
            try:
                self._ws = with_retry(lambda: sh.worksheet(tab))
            except gspread.WorksheetNotFound as exc:
                raise SheetError(f"Onglet '{tab}' introuvable dans le Sheet.") from exc
        return self._ws

    # ------------------------------------------------------------------
    # Localisation des colonnes par nom d'en-tête (insensible casse/accents)
    # ------------------------------------------------------------------
    def _locate_columns(
        self, ws: gspread.Worksheet, wanted: dict[str, str]
    ) -> dict[str, int]:
        """Renvoie {nom_logique: index_colonne (1-based)} pour les en-têtes trouvés.

        `wanted` mappe un nom logique vers le nom de colonne **déjà normalisé**.
        """
        header = with_retry(lambda: ws.row_values(1))
        found: dict[str, int] = {}
        for idx, value in enumerate(header, start=1):
            key = _normalize(value)
            for name, target in wanted.items():
                if key == target and name not in found:
                    found[name] = idx
        return found
