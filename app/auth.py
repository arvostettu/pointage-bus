import hmac

from fastapi import Request
from fastapi.responses import RedirectResponse
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from .config import Settings

COOKIE_NAME = "pointage_session"
SESSION_VALUE = "ok"


def _serializer(settings: Settings) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings.session_secret, salt="pointage-session")


def password_matches(submitted: str, settings: Settings) -> bool:
    return hmac.compare_digest(submitted.encode(), settings.app_password.encode())


def issue_session_cookie(response, settings: Settings) -> None:
    token = _serializer(settings).dumps(SESSION_VALUE)
    max_age = settings.session_lifetime_days * 24 * 3600
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        max_age=max_age,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        path="/",
    )


def clear_session_cookie(response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/")


def is_authenticated(request: Request, settings: Settings) -> bool:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return False
    max_age = settings.session_lifetime_days * 24 * 3600
    try:
        value = _serializer(settings).loads(token, max_age=max_age)
    except (BadSignature, SignatureExpired):
        return False
    return value == SESSION_VALUE


def redirect_to_login() -> RedirectResponse:
    return RedirectResponse(url="/login", status_code=303)
