from datetime import datetime
from enum import StrEnum
from zoneinfo import ZoneInfo


class Service(StrEnum):
    ALLER = "aller"
    RETOUR = "retour"


def now_local(tz: str) -> datetime:
    return datetime.now(ZoneInfo(tz))


def detect_service(now: datetime, cutoff_hour: int) -> Service:
    return Service.ALLER if now.hour < cutoff_hour else Service.RETOUR


def format_date(now: datetime, fmt: str) -> str:
    return now.strftime(fmt)
