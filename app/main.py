import logging
from datetime import datetime, time
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    Response,
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import auth
from .config import Settings, get_settings
from .occasional import OccasionalClient
from .service_logic import Service, detect_service, format_date, now_local
from .sheets import SheetError, SheetsClient

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

app = FastAPI(title="Pointage Bus", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

log = logging.getLogger("pointage")

_sheets_client: Optional[SheetsClient] = None
_occasional_client: Optional[OccasionalClient] = None


def _google_error_message(exc: Exception) -> str:
    """Journalise l'erreur réelle côté serveur et renvoie un message UI lisible."""
    log.exception("Erreur inattendue lors d'un appel Google Sheets")
    return "Connexion à Google impossible pour le moment. Vérifie le réseau et réessaie."


def get_sheets_client(settings: Settings) -> SheetsClient:
    global _sheets_client
    if _sheets_client is None:
        _sheets_client = SheetsClient(settings)
    return _sheets_client


def get_occasional_client(settings: Settings) -> OccasionalClient:
    global _occasional_client
    if _occasional_client is None:
        _occasional_client = OccasionalClient(settings)
    return _occasional_client


def _require_auth(request: Request, settings: Settings) -> Optional[RedirectResponse]:
    if not auth.is_authenticated(request, settings):
        return auth.redirect_to_login()
    return None


def _regulier_context(settings: Settings) -> dict:
    now = now_local(settings.tz)
    detected = detect_service(now, settings.morning_cutoff_hour)
    return {
        "now": now,
        "date_str": format_date(now, settings.date_format),
        "detected_service": detected,
        "cutoff_hour": settings.morning_cutoff_hour,
    }


def _parse_time(value: str, settings: Settings) -> time:
    value = (value or "").strip()
    for fmt in (settings.time_format, "%H:%M", "%H:%M:%S"):
        try:
            return datetime.strptime(value, fmt).time()
        except ValueError:
            continue
    raise HTTPException(status_code=400, detail=f"Heure invalide : {value!r}")


def _parse_date(value: str, settings: Settings):
    value = (value or "").strip()
    try:
        return datetime.strptime(value, settings.date_format).date()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Date invalide : {value!r}") from exc


# ----------------------------------------------------------------------
# Health
# ----------------------------------------------------------------------
@app.get("/healthz")
def healthz() -> JSONResponse:
    settings = get_settings()
    result: dict = {}
    status = 200

    try:
        result["sheet_regulier"] = get_sheets_client(settings).healthcheck()
    except SheetError as exc:
        result["sheet_regulier"] = {"error": str(exc)}
        status = 503
    except Exception as exc:
        result["sheet_regulier"] = {"error": repr(exc)}
        status = 503

    try:
        result["sheet_occasionnel"] = get_occasional_client(settings).healthcheck()
    except SheetError as exc:
        result["sheet_occasionnel"] = {"error": str(exc)}
        status = 503
    except Exception as exc:
        result["sheet_occasionnel"] = {"error": repr(exc)}
        status = 503

    return JSONResponse(result, status_code=status)


# ----------------------------------------------------------------------
# PWA (manifest, service worker, page hors-ligne, statut async)
# ----------------------------------------------------------------------
@app.get("/manifest.webmanifest", include_in_schema=False)
def manifest() -> FileResponse:
    return FileResponse(
        STATIC_DIR / "manifest.webmanifest", media_type="application/manifest+json"
    )


@app.get("/sw.js", include_in_schema=False)
def service_worker() -> FileResponse:
    return FileResponse(
        STATIC_DIR / "sw.js",
        media_type="application/javascript",
        headers={"Service-Worker-Allowed": "/", "Cache-Control": "no-cache"},
    )


@app.get("/offline", response_class=HTMLResponse, include_in_schema=False)
def offline(request: Request) -> Response:
    return templates.TemplateResponse(request, "offline.html", {})


@app.get("/api/status", include_in_schema=False)
def api_status(request: Request) -> JSONResponse:
    settings = get_settings()
    if not auth.is_authenticated(request, settings):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    data = {"in_progress": False}
    try:
        data["in_progress"] = get_occasional_client(settings).find_in_progress() is not None
    except Exception:
        log.warning("api_status : échec de find_in_progress", exc_info=True)
    return JSONResponse(data)


# ----------------------------------------------------------------------
# Auth
# ----------------------------------------------------------------------
@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request) -> Response:
    settings = get_settings()
    if auth.is_authenticated(request, settings):
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse(request, "login.html", {"error": None})


@app.post("/login")
def login_submit(request: Request, password: str = Form(...)) -> Response:
    settings = get_settings()
    if not auth.password_matches(password, settings):
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": "Mot de passe incorrect."},
            status_code=401,
        )
    response = RedirectResponse(url="/", status_code=303)
    auth.issue_session_cookie(response, settings)
    return response


@app.post("/logout")
def logout() -> Response:
    response = RedirectResponse(url="/login", status_code=303)
    auth.clear_session_cookie(response)
    return response


# ----------------------------------------------------------------------
# Accueil
# ----------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
def home(request: Request) -> Response:
    settings = get_settings()
    redirect = _require_auth(request, settings)
    if redirect:
        return redirect
    # Rendu instantané ; l'état « trajet en cours » est chargé via /api/status.
    return templates.TemplateResponse(request, "home.html", {})


# ----------------------------------------------------------------------
# Service régulier
# ----------------------------------------------------------------------
def _render_regulier(
    request: Request,
    settings: Settings,
    *,
    flash: Optional[dict] = None,
    sheet_error: Optional[str] = None,
    submitted_count: Optional[int] = None,
) -> Response:
    ctx = _regulier_context(settings)
    client = get_sheets_client(settings)
    today = None
    if sheet_error is None:
        try:
            today = client.today_values(now_local(settings.tz).date())
        except SheetError as exc:
            sheet_error = str(exc)
        except Exception as exc:
            sheet_error = _google_error_message(exc)
    return templates.TemplateResponse(
        request,
        "regulier.html",
        {
            "date_str": ctx["date_str"],
            "detected_service": ctx["detected_service"].value,
            "cutoff_hour": ctx["cutoff_hour"],
            "max_passengers": settings.max_passengers,
            "sheet_error": sheet_error,
            "last_write": client.last_write,
            "flash": flash,
            "today": today,
            "submitted_count": submitted_count,
        },
    )


@app.get("/regulier", response_class=HTMLResponse)
def regulier(request: Request) -> Response:
    settings = get_settings()
    redirect = _require_auth(request, settings)
    if redirect:
        return redirect
    return _render_regulier(request, settings)


def _validate_count(count: int, settings: Settings) -> int:
    if count < 0 or count > settings.max_passengers:
        raise HTTPException(status_code=400, detail="Nombre de passagers invalide.")
    return count


def _resolve_service(override: Optional[str], settings: Settings) -> Service:
    if override is None or override == "":
        return detect_service(now_local(settings.tz), settings.morning_cutoff_hour)
    if override == Service.ALLER.value:
        return Service.ALLER
    if override == Service.RETOUR.value:
        return Service.RETOUR
    raise HTTPException(status_code=400, detail="Service override invalide.")


@app.post("/regulier/submit")
def regulier_submit(
    request: Request,
    count: int = Form(...),
    service_override: Optional[str] = Form(None),
) -> Response:
    settings = get_settings()
    redirect = _require_auth(request, settings)
    if redirect:
        return redirect

    _validate_count(count, settings)
    service = _resolve_service(service_override, settings)
    now = now_local(settings.tz)
    client = get_sheets_client(settings)

    flash: dict
    try:
        last = client.upsert(now.date(), service, count)
        action = "remplacé" if last.previous_value not in ("", "0") else "enregistré"
        flash = {
            "kind": "success",
            "message": (
                f"{service.value.capitalize()} {action} : {count} passagers "
                f"pour le {last.date_str}."
            ),
        }
    except SheetError as exc:
        flash = {"kind": "error", "message": str(exc)}
    except Exception as exc:
        flash = {"kind": "error", "message": _google_error_message(exc)}

    # En cas d'échec, on réinjecte le nombre saisi pour ne pas le perdre.
    submitted_count = count if flash["kind"] == "error" else None
    return _render_regulier(request, settings, flash=flash, submitted_count=submitted_count)


@app.post("/regulier/correct")
def regulier_correct(request: Request, count: int = Form(...)) -> Response:
    settings = get_settings()
    redirect = _require_auth(request, settings)
    if redirect:
        return redirect

    _validate_count(count, settings)
    client = get_sheets_client(settings)

    flash: dict
    try:
        last = client.correct_last(count)
        flash = {
            "kind": "success",
            "message": (
                f"Correction : {last.service.value} du {last.date_str} → {count} passagers."
            ),
        }
    except SheetError as exc:
        flash = {"kind": "error", "message": str(exc)}
    except Exception as exc:
        flash = {"kind": "error", "message": _google_error_message(exc)}

    return _render_regulier(request, settings, flash=flash)


# ----------------------------------------------------------------------
# Service occasionnel
# ----------------------------------------------------------------------
def _render_occasionnel(
    request: Request,
    settings: Settings,
    *,
    sheet_error: Optional[str] = None,
    flash: Optional[dict] = None,
    form: Optional[dict] = None,
) -> Response:
    client = get_occasional_client(settings)
    in_progress = None
    km_suggestion = None
    if sheet_error is None:
        try:
            in_progress = client.find_in_progress()
            if in_progress is None:
                try:
                    km_suggestion = client.last_km_arrivee()
                except Exception:
                    log.warning("Lecture du dernier km a échoué", exc_info=True)
        except SheetError as exc:
            sheet_error = str(exc)
        except Exception as exc:
            sheet_error = _google_error_message(exc)

    now = now_local(settings.tz)
    return templates.TemplateResponse(
        request,
        "occasionnel.html",
        {
            "in_progress": in_progress,
            "date_str": format_date(now, settings.date_format),
            "time_str": now.strftime(settings.time_format),
            "max_km": settings.max_km,
            "max_pax": settings.max_passengers_occ,
            "sheet_error": sheet_error,
            "flash": flash,
            "form": form,
            "km_suggestion": km_suggestion,
        },
    )


def _validate_km(km: int, settings: Settings) -> int:
    if km < 0 or km > settings.max_km:
        raise HTTPException(status_code=400, detail="Kilométrage invalide.")
    return km


def _validate_pax(n: int, settings: Settings) -> int:
    if n < 0 or n > settings.max_passengers_occ:
        raise HTTPException(status_code=400, detail="Nombre de passagers invalide.")
    return n


@app.get("/occasionnel", response_class=HTMLResponse)
def occasionnel(request: Request) -> Response:
    settings = get_settings()
    redirect = _require_auth(request, settings)
    if redirect:
        return redirect
    return _render_occasionnel(request, settings)


@app.post("/occasionnel/montee")
def occasionnel_montee(
    request: Request,
    trip_date: str = Form(...),
    heure_depart: str = Form(...),
    km_depart: int = Form(...),
    adultes: int = Form(...),
    enfants: int = Form(...),
) -> Response:
    settings = get_settings()
    redirect = _require_auth(request, settings)
    if redirect:
        return redirect

    d = _parse_date(trip_date, settings)
    t = _parse_time(heure_depart, settings)
    _validate_km(km_depart, settings)
    _validate_pax(adultes, settings)
    _validate_pax(enfants, settings)

    client = get_occasional_client(settings)
    montee_form = {
        "trip_date": trip_date,
        "heure_depart": heure_depart,
        "km_depart": km_depart,
        "adultes": adultes,
        "enfants": enfants,
    }
    try:
        client.start(d, t, km_depart, adultes, enfants)
        flash = {
            "kind": "success",
            "message": (
                f"Montée enregistrée : {adultes} adultes, {enfants} enfants, "
                f"km {km_depart}, départ {t.strftime(settings.time_format)}."
            ),
        }
    except SheetError as exc:
        return _render_occasionnel(
            request, settings, flash={"kind": "error", "message": str(exc)}, form=montee_form
        )
    except Exception as exc:
        return _render_occasionnel(
            request,
            settings,
            flash={"kind": "error", "message": _google_error_message(exc)},
            form=montee_form,
        )

    return _render_occasionnel(request, settings, flash=flash)


@app.post("/occasionnel/montee/edit")
def occasionnel_montee_edit(
    request: Request,
    row: int = Form(...),
    trip_date: str = Form(...),
    heure_depart: str = Form(...),
    km_depart: int = Form(...),
    adultes: int = Form(...),
    enfants: int = Form(...),
) -> Response:
    settings = get_settings()
    redirect = _require_auth(request, settings)
    if redirect:
        return redirect

    d = _parse_date(trip_date, settings)
    t = _parse_time(heure_depart, settings)
    _validate_km(km_depart, settings)
    _validate_pax(adultes, settings)
    _validate_pax(enfants, settings)

    client = get_occasional_client(settings)
    try:
        client.update_montee(row, d, t, km_depart, adultes, enfants)
        flash = {"kind": "success", "message": "Informations de montée mises à jour."}
    except SheetError as exc:
        return _render_occasionnel(
            request, settings, flash={"kind": "error", "message": str(exc)}
        )
    except Exception as exc:
        return _render_occasionnel(
            request, settings, flash={"kind": "error", "message": _google_error_message(exc)}
        )

    return _render_occasionnel(request, settings, flash=flash)


@app.post("/occasionnel/descente")
def occasionnel_descente(
    request: Request,
    row: int = Form(...),
    heure_arrivee: str = Form(...),
    km_arrivee: int = Form(...),
) -> Response:
    settings = get_settings()
    redirect = _require_auth(request, settings)
    if redirect:
        return redirect

    t = _parse_time(heure_arrivee, settings)
    _validate_km(km_arrivee, settings)

    client = get_occasional_client(settings)
    descente_form = {"heure_arrivee": heure_arrivee, "km_arrivee": km_arrivee}
    try:
        km_total = client.finish(row, t, km_arrivee)
        flash = {
            "kind": "success",
            "message": (
                f"Trajet terminé. Km total : {km_total} "
                f"(arrivée {t.strftime(settings.time_format)})."
            ),
        }
    except SheetError as exc:
        return _render_occasionnel(
            request, settings, flash={"kind": "error", "message": str(exc)}, form=descente_form
        )
    except Exception as exc:
        return _render_occasionnel(
            request,
            settings,
            flash={"kind": "error", "message": _google_error_message(exc)},
            form=descente_form,
        )

    return _render_occasionnel(request, settings, flash=flash)


@app.post("/occasionnel/abandonner")
def occasionnel_abandonner(request: Request, row: int = Form(...)) -> Response:
    settings = get_settings()
    redirect = _require_auth(request, settings)
    if redirect:
        return redirect

    client = get_occasional_client(settings)
    try:
        client.abandon(row)
        flash = {"kind": "success", "message": "Trajet abandonné et supprimé."}
    except SheetError as exc:
        return _render_occasionnel(
            request, settings, flash={"kind": "error", "message": str(exc)}
        )
    except Exception as exc:
        return _render_occasionnel(
            request, settings, flash={"kind": "error", "message": _google_error_message(exc)}
        )

    return _render_occasionnel(request, settings, flash=flash)
