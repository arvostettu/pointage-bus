"""Helpers de parsing tolérants (purs, sans dépendance réseau).

Servent à relire des valeurs déjà présentes dans le Sheet, potentiellement
saisies à la main dans des formats variés. Isolés ici (sans gspread) pour être
testables sans installer les dépendances Google.
"""

from __future__ import annotations

import unicodedata
from datetime import date, datetime, time
from typing import Optional

# Formats acceptés pour relire dates/heures déjà présentes dans le Sheet.
# Le format d'écriture reste settings.date_format / time_format ; ceux-ci
# servent uniquement à matcher des lignes saisies à la main.
FALLBACK_DATE_FORMATS = (
    "%Y-%m-%d",
    "%d/%m/%Y",
    "%d/%m/%y",
    "%m/%d/%Y",
    "%d-%m-%Y",
    "%d.%m.%Y",
)
FALLBACK_TIME_FORMATS = ("%H:%M", "%H:%M:%S", "%Hh%M", "%H.%M")

# Espaces utilisées comme séparateurs de milliers : normale, insécable (U+00A0),
# fine insécable (U+202F, courante en français).
_THOUSAND_SEPARATORS = (" ", " ", " ")


def _normalize(text: str) -> str:
    """Minuscule, sans accents ni espaces de bord — pour matcher les en-têtes."""
    decomposed = unicodedata.normalize("NFD", text)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return stripped.strip().casefold()


def _parse_date_loose(value: str) -> Optional[date]:
    value = (value or "").strip()
    if not value:
        return None
    for fmt in FALLBACK_DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


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
    value = (value or "").strip()
    for sep in _THOUSAND_SEPARATORS:
        value = value.replace(sep, "")
    if not value:
        return None
    try:
        return int(float(value.replace(",", ".")))
    except ValueError:
        return None
