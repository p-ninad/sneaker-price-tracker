FROM python:3.11-slim

WORKDIR /app

ENV PYTHONPATH=/app/src
ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1

# Install system dependencies
RUN apt-get update && apt-get install -y \
    git \
    libgtk-3-0 \
    libx11-6 \
    libxss1 \
    libappindicator1 \
    libindicator7 \
    libnss3 \
    libc++1 \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browsers
RUN playwright install

# Copy application code
COPY src/ /app/src/

# Create runtime directories and non-root user
RUN groupadd --system appuser && \
    useradd --system --gid appuser --home /app --shell /usr/sbin/nologin appuser && \
    mkdir -p /app/data /app/logs && \
    chown -R appuser:appuser /app

USER appuser

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD python -c "import sqlite3; conn = sqlite3.connect('/app/data/price_tracker.db'); conn.execute('SELECT 1'); conn.close()"

# Run application
CMD ["python", "-m", "app.main"]
