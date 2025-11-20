#!/bin/bash
# Docker entrypoint for NIHR scraper
# Supports both one-time runs and cron scheduling

set -e

MODE="${1:-once}"

case "$MODE" in
  once)
    echo "Running NIHR scraper (one-time execution)..."
    exec python3 ingest_nihr.py
    ;;

  cron)
    echo "Setting up NIHR scraper in cron mode..."

    # Default schedule if not set
    CRON_SCHEDULE="${CRON_SCHEDULE:-0 2 * * *}"

    echo "Cron schedule: $CRON_SCHEDULE"

    # Create cron job
    echo "$CRON_SCHEDULE cd /app && python3 ingest_nihr.py >> /app/logs/cron.log 2>&1" | crontab -

    # Start cron in foreground
    echo "Starting cron daemon..."
    cron -f
    ;;

  test)
    echo "Running tests..."
    python3 test_nihr_scraper.py
    ;;

  dry-run)
    echo "Running dry run (no database writes)..."
    python3 dry_run.py
    ;;

  *)
    echo "Unknown mode: $MODE"
    echo "Usage: docker-entrypoint.sh [once|cron|test|dry-run]"
    exit 1
    ;;
esac
