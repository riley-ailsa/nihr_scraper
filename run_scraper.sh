#!/bin/bash
# NIHR Scraper - Production Cron Runner
# This script runs discovery and scraper with proper logging and error handling

set -e  # Exit on error

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$SCRIPT_DIR/outputs/logs"
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

# Step 1: Run discovery to find new opportunities
echo "" | tee -a "$LOG_FILE"
echo "Step 1: Running discovery..." | tee -a "$LOG_FILE"
python3 scripts/discovery.py 2>&1 | tee -a "$LOG_FILE"

DISCOVERY_EXIT=$?

if [ $DISCOVERY_EXIT -ne 0 ]; then
    echo "⚠️  Discovery had issues, continuing with scraper..." | tee -a "$LOG_FILE"
fi

# Step 2: Run the scraper
echo "" | tee -a "$LOG_FILE"
echo "Step 2: Running ingestion..." | tee -a "$LOG_FILE"
python3 run_ingestion.py 2>&1 | tee -a "$LOG_FILE"

INGEST_EXIT=$?

# Step 3: If ingestion succeeded, extract budget info from documents
if [ $INGEST_EXIT -eq 0 ]; then
    echo "" | tee -a "$LOG_FILE"
    echo "Step 3: Extracting budget info from documents..." | tee -a "$LOG_FILE"
    python3 scripts/extract_funding_from_docs.py 2>&1 | tee -a "$LOG_FILE"
    EXTRACT_EXIT=$?
else
    EXTRACT_EXIT=1
fi

# Check exit status
if [ $INGEST_EXIT -eq 0 ] && [ $EXTRACT_EXIT -eq 0 ]; then
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
