FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY pyproject.toml ./
RUN pip install --no-cache-dir \
        "fastapi>=0.115" \
        "uvicorn[standard]>=0.32" \
        "jinja2>=3.1" \
        "itsdangerous>=2.2" \
        "pydantic>=2.9" \
        "pydantic-settings>=2.6" \
        "gspread>=6.1" \
        "google-auth>=2.35" \
        "python-multipart>=0.0.12"

COPY app ./app

EXPOSE 8088

HEALTHCHECK --interval=60s --timeout=10s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; \
        r=urllib.request.urlopen('http://127.0.0.1:8088/healthz', timeout=5); \
        sys.exit(0 if r.status == 200 else 1)" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8088"]
