"""Service occasionnel : trajet ponctuel saisi en deux temps (Sheet2).

Le Sheet2 sert de stockage des trajets en cours : une ligne avec `heure_depart`
rempli mais `heure_arrivee` vide est considérée comme un trajet à compléter
(phase 2). Connexion, cache de l'onglet et retry viennent de `BaseSheetClient`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time
from typing import Optional

import gspread
from gspread.utils import rowcol_to_a1

from .config import Settings
from .sheets_base import (
    BaseSheetClient,
    SheetError,
    _normalize,
    _parse_int_loose,
    with_retry,
)

__all__ = ["OccasionalClient", "OccasionalColumns", "InProgressTrip"]


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


class OccasionalClient(BaseSheetClient):
    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self._cols: Optional[OccasionalColumns] = None

    def _tab_name(self) -> str:
        return self._settings.google_sheet_tab_occasionnel

    # ------------------------------------------------------------------
    # Lecture
    # ------------------------------------------------------------------
    def _columns(
        self, ws: gspread.Worksheet, *, refresh: bool = False
    ) -> OccasionalColumns:
        if self._cols is not None and not refresh:
            return self._cols
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
        found = self._locate_columns(ws, wanted)
        missing = [n for n in wanted if n not in found]
        if missing:
            expected = ", ".join(f"{n} (`{getattr(s, 'col_occ_' + n)}`)" for n in missing)
            raise SheetError(
                f"En-têtes manquants en ligne 1 de l'onglet "
                f"'{s.google_sheet_tab_occasionnel}' : {expected}."
            )
        self._cols = OccasionalColumns(**found)
        return self._cols

    def healthcheck(self) -> dict:
        ws = self._worksheet()
        cols = self._columns(ws, refresh=True)
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
        all_values = with_retry(lambda: ws.get_all_values())
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
            # append_row n'est pas idempotent → pas de retry (éviter un doublon).
            ws.append_row(new_row, value_input_option="USER_ENTERED")
            return len(with_retry(lambda: ws.col_values(cols.date)))

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
            with_retry(
                lambda: ws.batch_update(
                    [
                        {"range": rowcol_to_a1(row, cols.date), "values": [[date_str]]},
                        {"range": rowcol_to_a1(row, cols.heure_depart), "values": [[heure_str]]},
                        {"range": rowcol_to_a1(row, cols.km_depart), "values": [[km_depart]]},
                        {"range": rowcol_to_a1(row, cols.adultes), "values": [[adultes]]},
                        {"range": rowcol_to_a1(row, cols.enfants), "values": [[enfants]]},
                    ],
                    value_input_option="USER_ENTERED",
                )
            )

    def finish(self, row: int, heure_arrivee: time, km_arrivee: int) -> int:
        """Complète le trajet ; retourne le km total calculé."""
        with self._lock:
            ws = self._worksheet()
            cols = self._columns(ws)
            km_depart_raw = with_retry(lambda: ws.cell(row, cols.km_depart).value)
            km_depart = _parse_int_loose(km_depart_raw or "")
            if km_depart is None:
                raise SheetError("Km départ illisible sur la ligne du trajet en cours.")
            if km_arrivee < km_depart:
                raise SheetError(
                    f"Km arrivée ({km_arrivee}) inférieur au km départ ({km_depart})."
                )
            km_total = km_arrivee - km_depart
            heure_str = heure_arrivee.strftime(self._settings.time_format)
            with_retry(
                lambda: ws.batch_update(
                    [
                        {"range": rowcol_to_a1(row, cols.heure_arrivee), "values": [[heure_str]]},
                        {"range": rowcol_to_a1(row, cols.km_arrivee), "values": [[km_arrivee]]},
                        {"range": rowcol_to_a1(row, cols.km_total), "values": [[km_total]]},
                    ],
                    value_input_option="USER_ENTERED",
                )
            )
            return km_total

    def abandon(self, row: int) -> None:
        with self._lock:
            ws = self._worksheet()
            # delete_rows n'est pas idempotent → pas de retry.
            ws.delete_rows(row)
