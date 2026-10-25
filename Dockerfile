FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=5000 \
    DATABASE_PATH=/app/instance/campuscare.db

WORKDIR /app

# Create a non-root user for running the application.
RUN groupadd --gid 1000 campuscare \
    && useradd --uid 1000 --gid campuscare --create-home campuscare

# Install dependencies first for better layer caching.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code. instance/, *.db, .git, .venv, caches, etc. are excluded by .dockerignore.
COPY . .

# Make only the database directory writable by the non-root application user.
RUN mkdir -p /app/instance \
    && chown campuscare:campuscare /app/instance

USER campuscare

EXPOSE 5000

# Fail fast if SECRET_KEY is missing, then run Gunicorn.
CMD ["sh", "-c", ": \"${SECRET_KEY:?SECRET_KEY environment variable is required}\"; exec gunicorn --bind 0.0.0.0:${PORT} --workers ${GUNICORN_WORKERS:-2} --access-logfile - --error-logfile - app:app"]
