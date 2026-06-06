from datetime import date, time

from app.parsing import (
    _normalize,
    _parse_date_loose,
    _parse_int_loose,
    _parse_time_loose,
)


def test_normalize_strips_accents_and_case():
    assert _normalize("Heure départ") == _normalize("HEURE DEPART")
    assert _normalize("  Été  ") == "ete"
    assert _normalize("Km arrivée") == "km arrivee"


def test_parse_date_loose_formats():
    assert _parse_date_loose("2026-06-06") == date(2026, 6, 6)
    assert _parse_date_loose("06/06/2026") == date(2026, 6, 6)
    assert _parse_date_loose("06-06-2026") == date(2026, 6, 6)
    assert _parse_date_loose("06.06.2026") == date(2026, 6, 6)


def test_parse_date_loose_invalid_and_empty():
    assert _parse_date_loose("") is None
    assert _parse_date_loose("   ") is None
    assert _parse_date_loose("pas une date") is None


def test_parse_time_loose_formats():
    assert _parse_time_loose("07:45") == time(7, 45)
    assert _parse_time_loose("07:45:30") == time(7, 45, 30)
    assert _parse_time_loose("7h45") == time(7, 45)
    assert _parse_time_loose("07.45") == time(7, 45)


def test_parse_time_loose_invalid_and_empty():
    assert _parse_time_loose("") is None
    assert _parse_time_loose("xx") is None


def test_parse_int_loose_thousands_and_decimal():
    assert _parse_int_loose("1234") == 1234
    assert _parse_int_loose("1 234") == 1234  # espace normale
    assert _parse_int_loose("1 234") == 1234  # espace insécable
    assert _parse_int_loose("1 234") == 1234  # fine insécable (FR)
    assert _parse_int_loose("12,5") == 12  # virgule décimale, tronquée
    assert _parse_int_loose("12.9") == 12


def test_parse_int_loose_invalid_and_empty():
    assert _parse_int_loose("") is None
    assert _parse_int_loose("abc") is None
