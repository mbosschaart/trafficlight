# Use Python 3.11 slim image based on Debian Trixie for security patches
FROM python:3.11-slim-trixie

# Set working directory in container
WORKDIR /app

# Set environment variables
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1
ENV FLASK_APP=app.py
ENV FLASK_ENV=production
ENV PORT=8065

# Install system dependencies
RUN apt-get update && apt-get upgrade -y && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first to leverage Docker layer caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code (includes .env for internal demo)
COPY . .

# Create a non-root user and writable DB directory (volume mount target)
RUN useradd -m -u 1000 appuser \
    && mkdir -p /app/var \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8065

# Health check (uses PORT)
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:${PORT}/api/traffic-light/status || exit 1

# Production WSGI server (1 worker: in-memory demo state must stay shared)
CMD ["sh", "-c", "gunicorn --config gunicorn_conf.py app:app"]
