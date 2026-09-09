FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH="/app/src"

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:0.7.15 /uv /uvx /bin/
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

RUN groupadd --system svara \
    && useradd --system --gid svara --home-dir /app svara \
    && chown svara:svara /app

COPY --chown=svara:svara src ./src
COPY --chown=svara:svara alembic.ini ./alembic.ini
COPY --chown=svara:svara alembic ./alembic
COPY --chown=svara:svara certs ./certs

USER svara

EXPOSE 8000
CMD ["uvicorn", "svara_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
