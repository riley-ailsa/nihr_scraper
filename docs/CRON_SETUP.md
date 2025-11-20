# NIHR Scraper - Automated Cron Setup

## Overview

This setup enables automated scraping of NIHR funding opportunities on a schedule. The scraper will:
- **Rescrape all open NIHR grants** from the database to detect changes
- **Ingest new grants** from `nihr_urls.txt`
- **Detect and log changes** (status, deadline, budget)
- **Update PostgreSQL** with latest data
- **Update Pinecone** with fresh embeddings

## Quick Start

### 1. Add URLs to Track

Edit `nihr_urls.txt` and add NIHR opportunity URLs:

```bash
# NIHR Funding Opportunity URLs
https://www.nihr.ac.uk/funding/team-science-award-cohort-3/2025448
https://www.nihr.ac.uk/funding/another-opportunity/2025449
# Add more URLs...
```

### 2. Install Cron Job

Run the setup script:

```bash
./setup_cron.sh
```

Choose a schedule:
- **Option 1:** Daily at 2:00 AM (recommended for NIHR)
- **Option 2:** Every 6 hours
- **Option 3:** Every 12 hours
- **Option 4:** Weekly (Sundays at 2:00 AM)
- **Option 5:** Custom schedule

### 3. Verify Installation

Check that the cron job was installed:

```bash
crontab -l | grep nihr
```

You should see something like:
```
0 2 * * * /Users/rileycoleman/NIHR scraper/run_scraper.sh >> /Users/rileycoleman/NIHR scraper/logs/cron.log 2>&1
```

## How It Works

### Automatic Change Detection

The scraper automatically:

1. **Queries database** for all open NIHR grants
2. **Rescrapes each opportunity** to check for changes
3. **Compares** with existing data:
   - Status changes (Open → Closed)
   - Deadline changes
   - Budget changes
   - Title changes

4. **Logs changes** in detail:
   ```
   🔄 CHANGES: Status: Open → Closed, Deadline: 2026-01-28 → 2026-02-15
   ```

5. **Updates storage**:
   - PostgreSQL: Grant metadata
   - Pinecone: Embeddings with updated content

### What Gets Scraped

**Priority 1: Open Grants (from DB)**
- All grants with `status = 'Open'` and `source = 'nihr'`
- Ensures we catch deadline extensions, status changes, etc.

**Priority 2: New Grants (from file)**
- URLs listed in `nihr_urls.txt`
- Deduplicated with database grants

## File Structure

```
NIHR scraper/
├── ingest_nihr.py          # Main ingestion script
├── run_scraper.sh          # Cron runner wrapper
├── setup_cron.sh           # Cron installation script
├── nihr_urls.txt           # URLs to scrape
├── logs/                   # Log files
│   ├── scraper_20251120_020000.log
│   ├── scraper_20251121_020000.log
│   └── cron.log
└── .env                    # API keys & DB connection
```

## Logs

### View Latest Log

```bash
ls -lt logs/scraper_*.log | head -1 | awk '{print $9}' | xargs cat
```

### View Live (when running manually)

```bash
tail -f logs/scraper_$(date +%Y%m%d)*.log
```

### Log Retention

- Logs older than 30 days are automatically deleted
- Each run creates a timestamped log file

## Manual Testing

Before setting up the cron job, test manually:

```bash
# Test the ingestion script directly
python3 ingest_nihr.py

# Test the cron runner
./run_scraper.sh
```

## Managing the Cron Job

### View All Cron Jobs

```bash
crontab -l
```

### Edit Cron Jobs

```bash
crontab -e
```

### Remove NIHR Cron Job

```bash
crontab -l | grep -v "run_scraper.sh" | crontab -
```

### Temporarily Disable

Comment out the line in crontab:

```bash
crontab -e
# Add # at the start of the line:
# 0 2 * * * /Users/rileycoleman/NIHR scraper/run_scraper.sh ...
```

## Monitoring

### Check Last Run

```bash
ls -lht logs/ | head -5
```

### Check for Errors

```bash
grep -i "error\|failed" logs/scraper_*.log
```

### Check Changes Detected

```bash
grep -A 3 "CHANGES:" logs/scraper_*.log | tail -20
```

### Database Stats

```bash
psql $DATABASE_URL -c "
SELECT
    status,
    COUNT(*) as count,
    MIN(close_date) as earliest_deadline,
    MAX(close_date) as latest_deadline
FROM grants
WHERE source = 'nihr'
GROUP BY status;
"
```

## Troubleshooting

### Cron Not Running

1. Check cron service is running:
   ```bash
   sudo launchctl list | grep cron
   ```

2. Check system logs:
   ```bash
   grep CRON /var/log/system.log
   ```

3. Verify script permissions:
   ```bash
   ls -l run_scraper.sh
   # Should show: -rwxr-xr-x
   ```

### Script Failing

1. Check the log file:
   ```bash
   tail -50 logs/scraper_*.log | tail -1
   ```

2. Test manually with full output:
   ```bash
   bash -x ./run_scraper.sh
   ```

3. Verify environment variables:
   ```bash
   source .env
   echo $DATABASE_URL
   echo $PINECONE_API_KEY
   ```

### Database Connection Issues

1. Check PostgreSQL is running:
   ```bash
   pg_isready -h localhost -p 5432
   ```

2. Test connection:
   ```bash
   psql $DATABASE_URL -c "SELECT 1;"
   ```

### Pinecone Issues

1. Verify API key:
   ```bash
   python3 -c "
   from dotenv import load_dotenv
   import os
   load_dotenv()
   print('API key loaded:', bool(os.getenv('PINECONE_API_KEY')))
   "
   ```

2. Test connection:
   ```bash
   python3 dry_run.py
   ```

## Example Output

Successful run:

```
=========================================
NIHR Scraper - Started at Wed Nov 20 02:00:00 GMT 2024
=========================================
Running ingestion...
======================================================================
INGESTING NIHR GRANTS TO PRODUCTION
======================================================================
📊 Found 15 open NIHR grants in database
📁 Loaded 2 URLs from nihr_urls.txt

📋 Processing 17 opportunities:
   🔄 15 open grants (rescraping for changes)
   📁 2 from file

🚀 Processing 17 opportunities...

[1/17] Opportunity 2025448
  📥 Scraping...
  ✅ Team Science Award (Cohort 3)...
  🔄 CHANGES: Deadline: 2026-01-28 → 2026-02-15
  ✅ Saved to PostgreSQL
  🔮 Generating embedding...
  📌 Upserting to Pinecone...
  ✅ Indexed in Pinecone

[2/17] Opportunity 2025449
  📥 Scraping...
  ✅ Research Fellowship Programme...
  ✓ No changes
  ✅ Saved to PostgreSQL
  ...

======================================================================
INGESTION COMPLETE
======================================================================
✅ Success: 17
❌ Failed: 0

📊 Changes Detected:
   🆕 New: 2
   🔄 Updated: 3
   ✓ Unchanged: 12

📊 PostgreSQL (NIHR):
   Total: 45 grants
   Open: 15 grants
📊 Pinecone (Total): 112,485 vectors

🔄 DETAILED CHANGES:

   Opportunity 2025448:
      • Deadline: 2026-01-28 → 2026-02-15

   Opportunity 2025450:
      • Status: Open → Closed

   Opportunity 2025452:
      • Budget: £50,000 → £75,000
======================================================================
=========================================
✅ Scraper completed successfully at Wed Nov 20 02:15:23 GMT 2024
=========================================
```

## Recommended Schedule

**For NIHR:** Daily at 2:00 AM
- Catches deadline changes quickly
- Runs during low-traffic hours
- Balances freshness vs. API costs

**For high-priority grants:** Every 6 hours
- Use if you need near-real-time updates
- Higher API costs (4x daily runs)

**For archived tracking:** Weekly
- Sufficient for closed grants
- Minimal API usage

## API Costs

Approximate costs per run:
- **OpenAI embeddings:** ~$0.0001 per 1,000 tokens
- **Typical run (15 grants):** ~$0.015
- **Daily:** ~$0.45/month
- **Every 6 hours:** ~$1.80/month

## Next Steps

1. ✅ Verify `.env` file has all credentials
2. ✅ Add initial URLs to `nihr_urls.txt`
3. ✅ Test manually: `./run_scraper.sh`
4. ✅ Install cron: `./setup_cron.sh`
5. ✅ Monitor first few runs in `logs/`
