"""Service régulier (Sheet1) : une ligne par jour, colonnes Date / Aller / Retour.

Les en-têtes sont localisés par nom en ligne 1, ce qui rend l'app robuste si
l'utilisateur ajoute d'autres colonnes. La connexion, le cache de l'onglet et le
retry sont fournis par `BaseSheetClient`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional

import gspread

from .config import Settings
from .service_logic import Service
from .sheets_base import (
    BaseSheetClient,
    SheetError,
    _normalize,
    _parse_date_loose,
    with_retry,
)

# Ré-exporté pour compatibilité (main.py fait `from .sheets import SheetError`).
__all__ = ["SheetError", "SheetsClient", "Columns", "LastWrite"]


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


class SheetsClient(BaseSheetClient):
    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self._cols: Optional[Columns] = None
        self._last_write: Optional[LastWrite] = None

    def _tab_name(self) -> str:
        return self._settings.google_sheet_tab

    # ------------------------------------------------------------------
    # Lecture
    # ------------------------------------------------------------------
    def _columns(self, ws: gspread.Worksheet, *, refresh: bool = False) -> Columns:
        if self._cols is not None and not refresh:
            return self._cols
        s = self._settings
        found = self._locate_columns(
            ws,
            {
                "date": _normalize(s.col_date),
                "aller": _normalize(s.col_aller),
                "retour": _normalize(s.col_retour),
            },
        )
        missing = [n for n in ("date", "aller", "retour") if n not in found]
        if missing:
            raise SheetError(
                "En-têtes manquants en ligne 1 du Sheet : "
                + ", ".join(missing)
                + f" (attendus : {s.col_date}, {s.col_aller}, {s.col_retour})."
            )
        self._cols = Columns(date=found["date"], aller=found["aller"], retour=found["retour"])
        return self._cols

    def _find_date_row(
        self, ws: gspread.Worksheet, cols: Columns, target: date
    ) -> Optional[int]:
        values = with_retry(lambda: ws.col_values(cols.date))
        for idx, raw in enumerate(values, start=1):
            if idx == 1:  # header
                continue
            if _parse_date_loose(raw) == target:
                return idx
        return None

    def healthcheck(self) -> dict:
        ws = self._worksheet()
        cols = self._columns(ws, refresh=True)
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
                # append_row n'est pas idempotent → pas de retry (éviter un doublon).
                ws.append_row(new_row, value_input_option="USER_ENTERED")
                appended_row = len(with_retry(lambda: ws.col_values(cols.date)))
                last = LastWrite(
                    row=appended_row,
                    col=target_col,
                    service=service,
                    date_str=date_str,
                    previous_value="",
                )
            else:
                previous = with_retry(lambda: ws.cell(row, target_col).value) or ""
                with_retry(lambda: ws.update_cell(row, target_col, count))
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
            lw = self._last_write
            previous = with_retry(lambda: ws.cell(lw.row, lw.col).value) or ""
            with_retry(lambda: ws.update_cell(lw.row, lw.col, count))
            self._last_write = LastWrite(
                row=lw.row,
                col=lw.col,
                service=lw.service,
                date_str=lw.date_str,
                previous_value=str(previous),
            )
            return self._last_write

    @property
    def last_write(self) -> Optional[LastWrite]:
        return self._last_write
