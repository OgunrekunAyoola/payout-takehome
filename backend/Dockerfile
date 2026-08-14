# Deployment shape, not dev parity: DEBUG must be off, which means the image refuses to
# boot without an explicit PROVIDER_WEBHOOK_SECRET (settings.py fails fast on the dev
# fallback outside DEBUG — the point of that guard is exactly a deploy like this one).
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt ./
# gunicorn belongs to the container, not to requirements.txt — local dev and CI run the
# test suite against runserver/TestCase and never need it.
RUN pip install --no-cache-dir -r requirements.txt gunicorn==23.0.0

COPY . .

EXPOSE 8000

# migrate on boot: SQLite lives inside the container, so a fresh container is a fresh
# ledger and the schema must be applied before the first request.
CMD ["sh", "-c", "python manage.py migrate --no-input && exec gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 2"]
