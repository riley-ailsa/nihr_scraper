#!/bin/bash
# Setup cron job for NIHR scraper
# Run this script to install the cron job

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUNNER_SCRIPT="$SCRIPT_DIR/run_scraper.sh"

echo "========================================="
echo "NIHR Scraper - Cron Setup"
echo "========================================="
echo ""
echo "This will set up automated scraping on a schedule."
echo ""
echo "Available schedules:"
echo "  1) Daily at 2:00 AM"
echo "  2) Tuesday & Friday at 2:00 AM (recommended)"
echo "  3) Every 6 hours"
echo "  4) Every 12 hours"
echo "  5) Weekly (Sundays at 2:00 AM)"
echo "  6) Custom (you specify)"
echo ""
read -p "Choose option (1-6): " choice

case $choice in
    1)
        CRON_SCHEDULE="0 2 * * *"
        DESCRIPTION="Daily at 2:00 AM"
        ;;
    2)
        CRON_SCHEDULE="0 2 * * 2,5"
        DESCRIPTION="Tuesday & Friday at 2:00 AM"
        ;;
    3)
        CRON_SCHEDULE="0 */6 * * *"
        DESCRIPTION="Every 6 hours"
        ;;
    4)
        CRON_SCHEDULE="0 */12 * * *"
        DESCRIPTION="Every 12 hours"
        ;;
    5)
        CRON_SCHEDULE="0 2 * * 0"
        DESCRIPTION="Weekly on Sundays at 2:00 AM"
        ;;
    6)
        echo ""
        echo "Enter cron schedule (e.g., '0 2 * * *' for daily at 2am):"
        read -p "Schedule: " CRON_SCHEDULE
        DESCRIPTION="Custom: $CRON_SCHEDULE"
        ;;
    *)
        echo "Invalid option. Exiting."
        exit 1
        ;;
esac

# Create cron entry
CRON_ENTRY="$CRON_SCHEDULE $RUNNER_SCRIPT >> $SCRIPT_DIR/outputs/logs/cron.log 2>&1"

echo ""
echo "========================================="
echo "Cron Job Configuration"
echo "========================================="
echo "Schedule: $DESCRIPTION"
echo "Script: $RUNNER_SCRIPT"
echo "Cron entry: $CRON_ENTRY"
echo ""
read -p "Install this cron job? (y/n): " confirm

if [ "$confirm" != "y" ]; then
    echo "Cancelled."
    exit 0
fi

# Backup existing crontab
crontab -l > /tmp/crontab_backup_$(date +%Y%m%d_%H%M%S).txt 2>/dev/null || true

# Add new cron job (only if not already present)
(crontab -l 2>/dev/null | grep -v "$RUNNER_SCRIPT"; echo "$CRON_ENTRY") | crontab -

echo ""
echo "✅ Cron job installed successfully!"
echo ""
echo "Current crontab:"
crontab -l | grep "$RUNNER_SCRIPT"
echo ""
echo "To view all cron jobs: crontab -l"
echo "To remove this job: crontab -e"
echo ""
echo "Logs will be written to: $SCRIPT_DIR/outputs/logs/"
