FROM python:3.11-slim

WORKDIR /app

ENV PYTHONPATH=/app/src
ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

# Install system dependencies
RUN apt-get update && apt-get install -y \
    git \
    libx11-6 \
    libxss1 \
    libnss3 \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browsers
RUN playwright install --with-deps chromium && \
    chmod -R a+rX /ms-playwright

# Copy Alembic configuration and migrations so startup can run upgrades
COPY alembic.ini /app/alembic.ini
COPY migrations/ /app/migrations/

# Copy application code
COPY src/ /app/src/

# Create runtime directories and non-root user
RUN groupadd --system appuser && \
    useradd --system --gid appuser --home /app --shell /usr/sbin/nologin appuser && \
    mkdir -p /app/data /app/logs && \
    chown -R appuser:appuser /app

USER appuser

# Run application
CMD ["python", "-m", "app.main"]
