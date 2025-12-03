# NIHR Cron Scraper - Setup Complete ✅

## What's Ready

### Core Files
- ✅ **run_ingestion.py** - Main ingestion script (rescrapes open grants + new URLs)
- ✅ **run_scraper.sh** - Cron runner with logging
- ✅ **cron_job.sh** - Interactive cron installer
- ✅ **data/urls/nihr_urls.txt** - URL tracking file (add your URLs here)
- ✅ **outputs/logs/** - Log directory (auto-created)

### Features

**Automatic Change Detection:**
- ✅ Status changes (Open → Closed)
- ✅ Deadline extensions/changes
- ✅ Budget changes
- ✅ Title updates

**Smart Rescaping:**
- ✅ Automatically fetches all open NIHR grants from database
- ✅ Rescrapes to detect changes
- ✅ Also processes new URLs from data/urls/nihr_urls.txt
- ✅ Deduplicates automatically

**Dual Storage:**
- ✅ MongoDB: Grant metadata + change tracking
- ✅ Pinecone: Embeddings for semantic search

## Quick Start

### 1. Test Manually First

```bash
# Make sure you're in the right directory
cd "/Users/rileycoleman/NIHR scraper"

# Test the ingestion (will use DB URLs + data/urls/nihr_urls.txt)
python3 run_ingestion.py

# Or test the full cron runner
./run_scraper.sh
```

### 2. Install Cron Job

```bash
./cron_job.sh
```

Choose your schedule (recommend: **Option 1 - Daily at 2:00 AM**)

### 3. Verify

```bash
# Check cron is installed
crontab -l | grep nihr

# Watch for the first run (if running now)
tail -f outputs/logs/scraper_*.log
```

## What Happens on Each Run

```
1. Query MongoDB for open NIHR grants
   ↓
2. Scrape each open grant to check for changes
   ↓
3. Also scrape new URLs from data/urls/nihr_urls.txt
   ↓
4. Normalize data (Grant + Documents)
   ↓
5. Generate embeddings (OpenAI)
   ↓
6. Detect changes vs. existing data
   ↓
7. Update MongoDB + Pinecone
   ↓
8. Log results with detailed change report
```

## Example Log Output

```
======================================================================
INGESTING NIHR GRANTS TO PRODUCTION
======================================================================
📊 Found 15 open NIHR grants in database
📁 Loaded 1 URLs from data/urls/nihr_urls.txt

[1/16] Opportunity 2025448
  📥 Scraping...
  ✅ Team Science Award (Cohort 3)...
  🔄 CHANGES: Deadline: 2026-01-28 → 2026-02-15
  ✅ Saved to MongoDB
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
ls -t outputs/logs/scraper_*.log | head -1 | xargs tail -50

# Check for errors
grep -i error outputs/logs/scraper_*.log | tail -10

# See what changed in last run
grep -A 5 "DETAILED CHANGES" outputs/logs/scraper_*.log | tail -20

# Database stats
mongosh -c "
SELECT status, COUNT(*)
FROM grants
WHERE source = 'nihr'
GROUP BY status;
"
```

## File Locations

```
/Users/rileycoleman/NIHR scraper/
├── run_ingestion.py          ← Main script
├── run_scraper.sh          ← Cron runner
├── cron_job.sh           ← Cron installer
├── data/urls/nihr_urls.txt           ← Add URLs here
├── outputs/logs/                   ← Log files
│   └── scraper_*.log
├── .env                    ← API keys
└── CRON_SETUP.md           ← Full documentation
```

## Next Steps

1. **Add URLs:** Edit data/urls/nihr_urls.txt with NIHR opportunities to track
2. **Test:** Run `python3 run_ingestion.py` manually
3. **Install Cron:** Run `./cron_job.sh`
4. **Monitor:** Check `outputs/logs/` after first run

## Troubleshooting

**Cron not running?**
```bash
# Check cron is installed
crontab -l

# Check logs for errors
tail -100 outputs/logs/scraper_*.log
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
1. Add URLs to `data/urls/nihr_urls.txt`
2. Test with `python3 run_ingestion.py`
3. Install with `./cron_job.sh`

Full documentation in [CRON_SETUP.md](CRON_SETUP.md)
