FROM python:3.11-slim

ARG BUILD_SHA=unknown

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    BUILD_SHA=${BUILD_SHA}

WORKDIR /app

RUN addgroup --system app && adduser --system --ingroup app app

COPY pyproject.toml README.md alembic.ini requirements.lock ./
COPY app ./app
COPY alembic ./alembic

RUN python -m pip install --no-cache-dir --require-hashes -r requirements.lock \
    && python -m pip install --no-cache-dir --no-deps . \
    && python -m pip check

RUN mkdir -p /var/lib/dream-voice /var/lib/dream-motif \
    && chown -R app:app /var/lib/dream-voice /var/lib/dream-motif

USER app

CMD ["python", "-m", "app.telegram"]
