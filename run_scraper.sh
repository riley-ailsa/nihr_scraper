#!/bin/bash
# NIHR Scraper - Production Cron Runner
# This script runs the scraper with proper logging and error handling

set -e  # Exit on error

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$SCRIPT_DIR/logs"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
LOG_FILE="$LOG_DIR/scraper_$TIMESTAMP.log"

# Create logs directory if it doesn't exist
mkdir -p "$LOG_DIR"

# Start logging
echo "=========================================" | tee -a "$LOG_FILE"
echo "NIHR Scraper - Started at $(date)" | tee -a "$LOG_FILE"
echo "=========================================" | tee -a "$LOG_FILE"

# Change to script directory
cd "$SCRIPT_DIR"

# Activate virtual environment if it exists
if [ -d "venv" ]; then
    echo "Activating virtual environment..." | tee -a "$LOG_FILE"
    source venv/bin/activate
fi

# Run the scraper
echo "Running ingestion..." | tee -a "$LOG_FILE"
python3 ingest_nihr.py 2>&1 | tee -a "$LOG_FILE"

# Check exit status
if [ ${PIPESTATUS[0]} -eq 0 ]; then
    echo "=========================================" | tee -a "$LOG_FILE"
    echo "✅ Scraper completed successfully at $(date)" | tee -a "$LOG_FILE"
    echo "=========================================" | tee -a "$LOG_FILE"

    # Clean up old logs (keep last 30 days)
    find "$LOG_DIR" -name "scraper_*.log" -mtime +30 -delete

    exit 0
else
    echo "=========================================" | tee -a "$LOG_FILE"
    echo "❌ Scraper failed at $(date)" | tee -a "$LOG_FILE"
    echo "=========================================" | tee -a "$LOG_FILE"
    exit 1
fi
