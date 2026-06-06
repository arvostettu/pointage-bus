from datetime import datetime
from zoneinfo import ZoneInfo

from app.service_logic import Service, detect_service, format_date


def _dt(hour: int) -> datetime:
    return datetime(2026, 6, 6, hour, 0, tzinfo=ZoneInfo("Europe/Paris"))


def test_detect_service_before_cutoff_is_aller():
    assert detect_service(_dt(8), 12) is Service.ALLER
    assert detect_service(_dt(11), 12) is Service.ALLER


def test_detect_service_at_or_after_cutoff_is_retour():
    assert detect_service(_dt(12), 12) is Service.RETOUR  # à l'heure pile = retour
    assert detect_service(_dt(18), 12) is Service.RETOUR


def test_service_enum_values():
    assert Service.ALLER.value == "aller"
    assert Service.RETOUR.value == "retour"


def test_format_date():
    assert format_date(_dt(9), "%Y-%m-%d") == "2026-06-06"
