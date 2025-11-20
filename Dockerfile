# NIHR Scraper - Production Docker Image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    postgresql-client \
    cron \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first (better caching)
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create logs directory
RUN mkdir -p logs

# Make scripts executable
RUN chmod +x run_scraper.sh docker-entrypoint.sh ingest_nihr.py

# Create non-root user
RUN useradd -m -u 1000 scraper && \
    chown -R scraper:scraper /app

# Switch to non-root user
USER scraper

# Health check
HEALTHCHECK --interval=60s --timeout=10s --start-period=10s --retries=3 \
    CMD python3 -c "import sys; from src.ingest.nihr_funding import NihrFundingScraper; sys.exit(0)" || exit 1

# Default command (run once)
CMD ["python3", "ingest_nihr.py"]

# For cron mode, use:
# CMD ["./docker-entrypoint.sh", "cron"]
