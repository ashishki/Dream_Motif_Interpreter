FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN addgroup --system app && adduser --system --ingroup app app

COPY . .
RUN python -m pip install --upgrade pip \
    && python -m pip install . \
    && chown -R app:app /app

USER app

EXPOSE 8000

CMD ["python", "-m", "app.main"]
