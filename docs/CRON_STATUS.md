# NIHR Cron Scraper - Setup Complete ✅

## What's Ready

### Core Files
- ✅ **ingest_nihr.py** - Main ingestion script (rescrapes open grants + new URLs)
- ✅ **run_scraper.sh** - Cron runner with logging
- ✅ **setup_cron.sh** - Interactive cron installer
- ✅ **nihr_urls.txt** - URL tracking file (add your URLs here)
- ✅ **logs/** - Log directory (auto-created)

### Features

**Automatic Change Detection:**
- ✅ Status changes (Open → Closed)
- ✅ Deadline extensions/changes
- ✅ Budget changes
- ✅ Title updates

**Smart Rescaping:**
- ✅ Automatically fetches all open NIHR grants from database
- ✅ Rescrapes to detect changes
- ✅ Also processes new URLs from nihr_urls.txt
- ✅ Deduplicates automatically

**Dual Storage:**
- ✅ PostgreSQL: Grant metadata + change tracking
- ✅ Pinecone: Embeddings for semantic search

## Quick Start

### 1. Test Manually First

```bash
# Make sure you're in the right directory
cd "/Users/rileycoleman/NIHR scraper"

# Test the ingestion (will use DB URLs + nihr_urls.txt)
python3 ingest_nihr.py

# Or test the full cron runner
./run_scraper.sh
```

### 2. Install Cron Job

```bash
./setup_cron.sh
```

Choose your schedule (recommend: **Option 1 - Daily at 2:00 AM**)

### 3. Verify

```bash
# Check cron is installed
crontab -l | grep nihr

# Watch for the first run (if running now)
tail -f logs/scraper_*.log
```

## What Happens on Each Run

```
1. Query PostgreSQL for open NIHR grants
   ↓
2. Scrape each open grant to check for changes
   ↓
3. Also scrape new URLs from nihr_urls.txt
   ↓
4. Normalize data (Grant + Documents)
   ↓
5. Generate embeddings (OpenAI)
   ↓
6. Detect changes vs. existing data
   ↓
7. Update PostgreSQL + Pinecone
   ↓
8. Log results with detailed change report
```

## Example Log Output

```
======================================================================
INGESTING NIHR GRANTS TO PRODUCTION
======================================================================
📊 Found 15 open NIHR grants in database
📁 Loaded 1 URLs from nihr_urls.txt

[1/16] Opportunity 2025448
  📥 Scraping...
  ✅ Team Science Award (Cohort 3)...
  🔄 CHANGES: Deadline: 2026-01-28 → 2026-02-15
  ✅ Saved to PostgreSQL
  🔮 Generating embedding...
  📌 Upserting to Pinecone...
  ✅ Indexed in Pinecone

======================================================================
INGESTION COMPLETE
======================================================================
✅ Success: 16
❌ Failed: 0

📊 Changes Detected:
   🆕 New: 1
   🔄 Updated: 2
   ✓ Unchanged: 13

🔄 DETAILED CHANGES:
   Opportunity 2025448:
      • Deadline: 2026-01-28 → 2026-02-15
```

## Monitoring Commands

```bash
# View latest log
ls -t logs/scraper_*.log | head -1 | xargs tail -50

# Check for errors
grep -i error logs/scraper_*.log | tail -10

# See what changed in last run
grep -A 5 "DETAILED CHANGES" logs/scraper_*.log | tail -20

# Database stats
psql $DATABASE_URL -c "
SELECT status, COUNT(*)
FROM grants
WHERE source = 'nihr'
GROUP BY status;
"
```

## File Locations

```
/Users/rileycoleman/NIHR scraper/
├── ingest_nihr.py          ← Main script
├── run_scraper.sh          ← Cron runner
├── setup_cron.sh           ← Cron installer
├── nihr_urls.txt           ← Add URLs here
├── logs/                   ← Log files
│   └── scraper_*.log
├── .env                    ← API keys
└── CRON_SETUP.md           ← Full documentation
```

## Next Steps

1. **Add URLs:** Edit nihr_urls.txt with NIHR opportunities to track
2. **Test:** Run `python3 ingest_nihr.py` manually
3. **Install Cron:** Run `./setup_cron.sh`
4. **Monitor:** Check `logs/` after first run

## Troubleshooting

**Cron not running?**
```bash
# Check cron is installed
crontab -l

# Check logs for errors
tail -100 logs/scraper_*.log
```

**Script failing?**
```bash
# Run with full error output
bash -x ./run_scraper.sh
```

**Need to update schedule?**
```bash
# Edit crontab directly
crontab -e
```

**Want to disable temporarily?**
```bash
# Comment out in crontab
crontab -e
# Add # before the line
```

## Ready to Go! 🚀

Everything is wired up and ready. Just:
1. Add URLs to `nihr_urls.txt`
2. Test with `python3 ingest_nihr.py`
3. Install with `./setup_cron.sh`

Full documentation in [CRON_SETUP.md](CRON_SETUP.md)
