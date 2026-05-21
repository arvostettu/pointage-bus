"""Wrapper autour de gspread pour le pointage bus.

Source de vérité : un Google Sheet avec une ligne par jour et trois colonnes
nommées (Date, Aller, Retour). Les en-têtes sont localisés par nom en ligne 1,
ce qui rend l'app robuste si l'utilisateur ajoute d'autres colonnes.
"""

from __future__ import annotations

import threading
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional

import gspread
from google.oauth2.service_account import Credentials

from .config import Settings
from .service_logic import Service

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
]

# Formats acceptés pour les dates déjà présentes dans le Sheet.
# Le format d'écriture est settings.date_format ; ces formats servent
# uniquement pour matcher des lignes existantes saisies à la main.
FALLBACK_DATE_FORMATS = (
    "%Y-%m-%d",
    "%d/%m/%Y",
    "%d/%m/%y",
    "%m/%d/%Y",
    "%d-%m-%Y",
    "%d.%m.%Y",
)


class SheetError(RuntimeError):
    """Erreur fonctionnelle remontée à l'utilisateur."""


@dataclass
class Columns:
    date: int
    aller: int
    retour: int


@dataclass
class LastWrite:
    row: int
    col: int
    service: Service
    date_str: str
    previous_value: str


def _normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", text)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return stripped.strip().casefold()


def _parse_date_loose(value: str) -> Optional[date]:
    value = value.strip()
    if not value:
        return None
    for fmt in FALLBACK_DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


class SheetsClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._lock = threading.Lock()
        self._client: Optional[gspread.Client] = None
        self._last_write: Optional[LastWrite] = None

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
        sh = self._gspread_client().open_by_key(self._settings.google_sheet_id)
        try:
            return sh.worksheet(self._settings.google_sheet_tab)
        except gspread.WorksheetNotFound as exc:
            raise SheetError(
                f"Onglet '{self._settings.google_sheet_tab}' introuvable dans le Sheet."
            ) from exc

    # ------------------------------------------------------------------
    # Lecture
    # ------------------------------------------------------------------
    def _columns(self, ws: gspread.Worksheet) -> Columns:
        header = ws.row_values(1)
        wanted = {
            "date": _normalize(self._settings.col_date),
            "aller": _normalize(self._settings.col_aller),
            "retour": _normalize(self._settings.col_retour),
        }
        found: dict[str, int] = {}
        for idx, value in enumerate(header, start=1):
            key = _normalize(value)
            for name, target in wanted.items():
                if key == target and name not in found:
                    found[name] = idx
        missing = [n for n in ("date", "aller", "retour") if n not in found]
        if missing:
            raise SheetError(
                "En-têtes manquants en ligne 1 du Sheet : "
                + ", ".join(missing)
                + f" (attendus : {self._settings.col_date}, "
                f"{self._settings.col_aller}, {self._settings.col_retour})."
            )
        return Columns(date=found["date"], aller=found["aller"], retour=found["retour"])

    def _find_date_row(
        self, ws: gspread.Worksheet, cols: Columns, target: date
    ) -> Optional[int]:
        values = ws.col_values(cols.date)
        for idx, raw in enumerate(values, start=1):
            if idx == 1:  # header
                continue
            parsed = _parse_date_loose(raw)
            if parsed == target:
                return idx
        return None

    def healthcheck(self) -> dict:
        ws = self._worksheet()
        cols = self._columns(ws)
        return {
            "sheet": "ok",
            "tab": ws.title,
            "columns": {"date": cols.date, "aller": cols.aller, "retour": cols.retour},
        }

    # ------------------------------------------------------------------
    # Écriture
    # ------------------------------------------------------------------
    def upsert(self, today: date, service: Service, count: int) -> LastWrite:
        with self._lock:
            ws = self._worksheet()
            cols = self._columns(ws)
            row = self._find_date_row(ws, cols, today)
            target_col = cols.aller if service is Service.ALLER else cols.retour
            date_str = today.strftime(self._settings.date_format)

            if row is None:
                # Append : on construit une nouvelle ligne sur la largeur du header.
                width = max(cols.date, cols.aller, cols.retour)
                new_row = [""] * width
                new_row[cols.date - 1] = date_str
                new_row[target_col - 1] = count
                ws.append_row(new_row, value_input_option="USER_ENTERED")
                # `row_count` reflète la dernière ligne après append.
                appended_row = len(ws.col_values(cols.date))
                last = LastWrite(
                    row=appended_row,
                    col=target_col,
                    service=service,
                    date_str=date_str,
                    previous_value="",
                )
            else:
                previous = ws.cell(row, target_col).value or ""
                ws.update_cell(row, target_col, count)
                last = LastWrite(
                    row=row,
                    col=target_col,
                    service=service,
                    date_str=date_str,
                    previous_value=str(previous),
                )

            self._last_write = last
            return last

    def correct_last(self, count: int) -> LastWrite:
        with self._lock:
            if self._last_write is None:
                raise SheetError(
                    "Aucune saisie récente à corriger. Refaites une saisie normale."
                )
            ws = self._worksheet()
            previous = ws.cell(self._last_write.row, self._last_write.col).value or ""
            ws.update_cell(self._last_write.row, self._last_write.col, count)
            self._last_write = LastWrite(
                row=self._last_write.row,
                col=self._last_write.col,
                service=self._last_write.service,
                date_str=self._last_write.date_str,
                previous_value=str(previous),
            )
            return self._last_write

    @property
    def last_write(self) -> Optional[LastWrite]:
        return self._last_write
