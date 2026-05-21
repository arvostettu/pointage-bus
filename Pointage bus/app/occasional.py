"""Service occasionnel : trajet ponctuel saisi en deux temps (Sheet2).

Le Sheet2 sert de stockage des trajets en cours : une ligne avec
`heure_depart` rempli mais `heure_arrivee` vide est considérée
comme un trajet à compléter (phase 2).
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Optional

import gspread
from google.oauth2.service_account import Credentials

from .config import Settings
from .sheets import SheetError, _normalize, _parse_date_loose

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
]

# Formats acceptés pour les heures déjà présentes dans le Sheet (relecture).
FALLBACK_TIME_FORMATS = ("%H:%M", "%H:%M:%S", "%Hh%M", "%H.%M")


def _parse_time_loose(value: str) -> Optional[time]:
    value = (value or "").strip()
    if not value:
        return None
    for fmt in FALLBACK_TIME_FORMATS:
        try:
            return datetime.strptime(value, fmt).time()
        except ValueError:
            continue
    return None


def _parse_int_loose(value: str) -> Optional[int]:
    value = (value or "").strip().replace(" ", "").replace(" ", "")
    if not value:
        return None
    try:
        return int(float(value.replace(",", ".")))
    except ValueError:
        return None


@dataclass
class OccasionalColumns:
    date: int
    heure_depart: int
    heure_arrivee: int
    km_depart: int
    km_arrivee: int
    km_total: int
    adultes: int
    enfants: int


@dataclass
class InProgressTrip:
    row: int
    date_str: str
    heure_depart_str: str
    km_depart: Optional[int]
    adultes: Optional[int]
    enfants: Optional[int]


class OccasionalClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._lock = threading.Lock()
        self._client: Optional[gspread.Client] = None

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
        tab = self._settings.google_sheet_tab_occasionnel
        try:
            return sh.worksheet(tab)
        except gspread.WorksheetNotFound as exc:
            raise SheetError(f"Onglet '{tab}' introuvable dans le Sheet.") from exc

    def _columns(self, ws: gspread.Worksheet) -> OccasionalColumns:
        header = ws.row_values(1)
        s = self._settings
        wanted = {
            "date": _normalize(s.col_occ_date),
            "heure_depart": _normalize(s.col_occ_heure_depart),
            "heure_arrivee": _normalize(s.col_occ_heure_arrivee),
            "km_depart": _normalize(s.col_occ_km_depart),
            "km_arrivee": _normalize(s.col_occ_km_arrivee),
            "km_total": _normalize(s.col_occ_km_total),
            "adultes": _normalize(s.col_occ_adultes),
            "enfants": _normalize(s.col_occ_enfants),
        }
        found: dict[str, int] = {}
        for idx, value in enumerate(header, start=1):
            key = _normalize(value)
            for name, target in wanted.items():
                if key == target and name not in found:
                    found[name] = idx
        missing = [n for n in wanted if n not in found]
        if missing:
            expected = ", ".join(
                f"{n} (`{getattr(s, 'col_occ_' + n)}`)" for n in missing
            )
            raise SheetError(
                f"En-têtes manquants en ligne 1 de l'onglet "
                f"'{s.google_sheet_tab_occasionnel}' : {expected}."
            )
        return OccasionalColumns(**found)

    # ------------------------------------------------------------------
    # Lecture
    # ------------------------------------------------------------------
    def healthcheck(self) -> dict:
        ws = self._worksheet()
        cols = self._columns(ws)
        return {
            "tab": ws.title,
            "columns": {
                "date": cols.date,
                "heure_depart": cols.heure_depart,
                "heure_arrivee": cols.heure_arrivee,
                "km_depart": cols.km_depart,
                "km_arrivee": cols.km_arrivee,
                "km_total": cols.km_total,
                "adultes": cols.adultes,
                "enfants": cols.enfants,
            },
        }

    def find_in_progress(self) -> Optional[InProgressTrip]:
        ws = self._worksheet()
        cols = self._columns(ws)
        all_values = ws.get_all_values()
        # On parcourt du bas vers le haut, en sautant la ligne d'en-têtes.
        for row_idx in range(len(all_values), 1, -1):
            row = all_values[row_idx - 1]

            def cell(col_idx: int) -> str:
                return row[col_idx - 1] if col_idx - 1 < len(row) else ""

            heure_depart = cell(cols.heure_depart).strip()
            heure_arrivee = cell(cols.heure_arrivee).strip()
            if heure_depart and not heure_arrivee:
                return InProgressTrip(
                    row=row_idx,
                    date_str=cell(cols.date).strip(),
                    heure_depart_str=heure_depart,
                    km_depart=_parse_int_loose(cell(cols.km_depart)),
                    adultes=_parse_int_loose(cell(cols.adultes)),
                    enfants=_parse_int_loose(cell(cols.enfants)),
                )
        return None

    # ------------------------------------------------------------------
    # Écriture
    # ------------------------------------------------------------------
    def start(
        self,
        today: date,
        heure_depart: time,
        km_depart: int,
        adultes: int,
        enfants: int,
    ) -> int:
        with self._lock:
            ws = self._worksheet()
            cols = self._columns(ws)
            date_str = today.strftime(self._settings.date_format)
            heure_str = heure_depart.strftime(self._settings.time_format)

            width = max(
                cols.date,
                cols.heure_depart,
                cols.heure_arrivee,
                cols.km_depart,
                cols.km_arrivee,
                cols.km_total,
                cols.adultes,
                cols.enfants,
            )
            new_row: list = [""] * width
            new_row[cols.date - 1] = date_str
            new_row[cols.heure_depart - 1] = heure_str
            new_row[cols.km_depart - 1] = km_depart
            new_row[cols.adultes - 1] = adultes
            new_row[cols.enfants - 1] = enfants
            ws.append_row(new_row, value_input_option="USER_ENTERED")
            return len(ws.col_values(cols.date))

    def update_montee(
        self,
        row: int,
        today: date,
        heure_depart: time,
        km_depart: int,
        adultes: int,
        enfants: int,
    ) -> None:
        with self._lock:
            ws = self._worksheet()
            cols = self._columns(ws)
            date_str = today.strftime(self._settings.date_format)
            heure_str = heure_depart.strftime(self._settings.time_format)
            ws.batch_update(
                [
                    {"range": gspread.utils.rowcol_to_a1(row, cols.date), "values": [[date_str]]},
                    {"range": gspread.utils.rowcol_to_a1(row, cols.heure_depart), "values": [[heure_str]]},
                    {"range": gspread.utils.rowcol_to_a1(row, cols.km_depart), "values": [[km_depart]]},
                    {"range": gspread.utils.rowcol_to_a1(row, cols.adultes), "values": [[adultes]]},
                    {"range": gspread.utils.rowcol_to_a1(row, cols.enfants), "values": [[enfants]]},
                ],
                value_input_option="USER_ENTERED",
            )

    def finish(self, row: int, heure_arrivee: time, km_arrivee: int) -> int:
        """Complète le trajet ; retourne le km total calculé."""
        with self._lock:
            ws = self._worksheet()
            cols = self._columns(ws)
            km_depart_raw = ws.cell(row, cols.km_depart).value
            km_depart = _parse_int_loose(km_depart_raw or "")
            if km_depart is None:
                raise SheetError(
                    "Km départ illisible sur la ligne du trajet en cours."
                )
            if km_arrivee < km_depart:
                raise SheetError(
                    f"Km arrivée ({km_arrivee}) inférieur au km départ ({km_depart})."
                )
            km_total = km_arrivee - km_depart
            heure_str = heure_arrivee.strftime(self._settings.time_format)
            ws.batch_update(
                [
                    {"range": gspread.utils.rowcol_to_a1(row, cols.heure_arrivee), "values": [[heure_str]]},
                    {"range": gspread.utils.rowcol_to_a1(row, cols.km_arrivee), "values": [[km_arrivee]]},
                    {"range": gspread.utils.rowcol_to_a1(row, cols.km_total), "values": [[km_total]]},
                ],
                value_input_option="USER_ENTERED",
            )
            return km_total

    def abandon(self, row: int) -> None:
        with self._lock:
            ws = self._worksheet()
            ws.delete_rows(row)
