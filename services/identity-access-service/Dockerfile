# syntax=docker/dockerfile:1
FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /srv

# Pinned, reproducible dependency layer (regenerate requirements.lock when pyproject.toml changes).
COPY requirements.lock ./
RUN pip install --no-deps -r requirements.lock

COPY app ./app
COPY migrations ./migrations
COPY alembic.ini ./

# Non-root runtime user. No .env or credentials are baked in: configuration arrives via environment variables.
RUN useradd --system --uid 10001 --no-create-home iam && chown -R iam /srv
USER iam

EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health/live', timeout=2).status == 200 else 1)"

CMD ["uvicorn", "app.main:factory", "--factory", "--host", "0.0.0.0", "--port", "8000", "--no-server-header"]
