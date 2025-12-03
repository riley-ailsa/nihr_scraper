# NIHR Funding Scraper

Automated scraper for NIHR (National Institute for Health and Care Research) funding opportunities. Extracts grant data, generates embeddings, and maintains synchronized storage across MongoDB and Pinecone.

## Quick Start

```bash
# 1. Configure environment
cp .env.example .env  # Edit with your API keys

# 2. Test the scraper
python3 test_nihr_scraper.py

# 3. Add URLs to track
echo "https://www.nihr.ac.uk/funding/team-science-award-cohort-3/2025448" >> data/urls/nihr_urls.txt

# 4. Run manual ingestion
python3 run_ingestion.py

# 5. Set up automated scraping
./cron_job.sh  # Choose option 1 (Daily at 2:00 AM)
```

## What It Does

**Scraping**
- Extracts NIHR grant metadata (title, dates, funding, status)
- Tab-aware content parsing (Overview, Eligibility, Application Guidance)
- Resource extraction (PDFs, webpages, videos)

**Change Detection**
- Automatically rescrapes all open grants from database
- Detects status changes (Open → Closed)
- Detects deadline extensions
- Detects budget changes
- Logs all changes with details

**Storage**
- MongoDB: Structured grant metadata (shared `grants` collection)
- Pinecone: Semantic search embeddings (1536-dim vectors)
- Automatic upserts with change tracking

**Automation**
- Cron-based scheduling (daily/hourly/weekly)
- Comprehensive logging with timestamps
- Automatic cleanup of old logs (30 days)

## Configuration

### Environment Variables

Create `.env` file:

```bash
# OpenAI (for embeddings)
OPENAI_API_KEY=sk-...

# Pinecone (vector database)
PINECONE_API_KEY=pcsk_...
PINECONE_INDEX_NAME=ailsa-grants

# MongoDB
MONGO_URI=mongodb+srv://user:password@cluster.mongodb.net/?retryWrites=true&w=majority
MONGO_DB_NAME=ailsa_grants
```

### MongoDB Document Schema

```javascript
// Collection: grants (shared with Innovate UK scraper)
{
    "grant_id": "nihr_2025/448",        // Unique identifier
    "source": "nihr",                    // Source identifier
    "external_id": "2025/448",          // NIHR reference ID

    // Core metadata
    "title": "Team Science Award",
    "url": "https://www.nihr.ac.uk/funding/...",
    "description": "...",

    // Status & dates
    "status": "active",                  // "active" | "closed"
    "is_active": true,
    "opens_at": ISODate("2025-01-01"),
    "closes_at": ISODate("2025-06-30"),

    // Funding
    "total_fund_gbp": 4000000,          // Parsed numeric amount
    "total_fund_display": "£4 million", // Display text
    "project_funding_min": null,
    "project_funding_max": null,
    "competition_type": "grant",

    // Classification
    "tags": ["nihr", "health_research"],
    "sectors": ["health", "medical_research"],

    // Tab-aware content sections
    "sections": [
        { "name": "overview", "text": "...", "url": "...#tab-overview" },
        { "name": "eligibility", "text": "...", "url": "...#tab-eligibility" }
    ],

    // Resources (PDFs, links)
    "resources": [
        { "id": "...", "title": "Guidance PDF", "url": "...", "type": "pdf" }
    ],

    // Timestamps
    "scraped_at": ISODate("..."),
    "updated_at": ISODate("..."),
    "created_at": ISODate("...")
}
```

## Usage

### Manual Execution

```bash
# Test scraper
python3 test_nihr_scraper.py

# Dry run (no database writes)
python3 run_scraper.py

# Full ingestion
python3 run_ingestion.py
```

### Automated Execution

```bash
# Install cron job
./cron_job.sh

# Schedules available:
#   1) Daily at 2:00 AM (recommended)
#   2) Every 6 hours
#   3) Every 12 hours
#   4) Weekly
#   5) Custom

# Verify installation
crontab -l | grep nihr

# View logs
tail -f outputs/logs/scraper_*.log
```

### URL Management

Edit `data/urls/nihr_urls.txt` to add opportunities:

```
# NIHR Funding Opportunities
https://www.nihr.ac.uk/funding/team-science-award-cohort-3/2025448
https://www.nihr.ac.uk/funding/another-opportunity/2025449
```

The scraper automatically combines:
1. All open grants from database (for change detection)
2. New URLs from `data/urls/nihr_urls.txt`

## Project Structure

```
NIHR scraper/
├── run_ingestion.py          # Main ingestion script (cron target)
├── run_scraper.sh          # Cron runner with logging
├── cron_job.sh           # Interactive cron installer
├── data/urls/nihr_urls.txt           # URL tracking file
├── run_scraper.py              # Pipeline test (no DB writes)
├── test_nihr_scraper.py    # Quick validation
├── outputs/logs/                   # Execution logs
│   └── scraper_*.log
├── src/                    # Core library
│   ├── ingest/
│   │   ├── nihr_funding.py    # Main scraper
│   │   ├── pdf_parser.py      # PDF extraction
│   │   └── resource_fetcher.py
│   ├── normalize/
│   │   └── nihr.py            # Data normalization
│   ├── core/                  # Domain models
│   ├── api/                   # OpenAI embeddings
│   ├── storage/               # Database operations
│   └── enhance/               # Content processing
└── .env                    # Configuration (not in git)
```

## Monitoring

### Check Status

```bash
# View latest log
ls -t outputs/logs/scraper_*.log | head -1 | xargs tail -50

# Check for errors
grep -i "error\|failed" outputs/logs/scraper_*.log

# See detected changes
grep -A 5 "DETAILED CHANGES" outputs/logs/scraper_*.log | tail -20

# Database stats (MongoDB)
mongosh "$MONGO_URI" --eval '
use ailsa_grants;
db.grants.aggregate([
    { $match: { source: "nihr" } },
    { $group: { _id: "$status", count: { $sum: 1 } } }
]);
'
```

### Example Output

```
======================================================================
INGESTING NIHR GRANTS TO PRODUCTION
======================================================================
Found 15 open NIHR grants in database
Loaded 2 URLs from data/urls/nihr_urls.txt

Processing 17 opportunities...

[1/17] Opportunity 2025448
  Scraping...
  Team Science Award (Cohort 3)...
  CHANGES: Deadline: 2026-01-28 -> 2026-02-15
  Saved to MongoDB
  Generating embedding...
  Indexed in Pinecone

======================================================================
INGESTION COMPLETE
======================================================================
Success: 17
Failed: 0

Changes Detected:
   New: 2
   Updated: 3
   Unchanged: 12

MongoDB (NIHR):
   Total: 17 grants
   Active: 15 grants

DETAILED CHANGES:
   Opportunity 2025448:
      • Deadline: 2026-01-28 -> 2026-02-15
   Opportunity 2025450:
      • Status: Open -> Closed
======================================================================
```

## Troubleshooting

### Import Errors

```bash
# Verify Python can find src/
python3 -c "from src.ingest.nihr_funding import NihrFundingScraper; print('OK')"
```

### Database Connection

```bash
# Test MongoDB connection
mongosh "$MONGO_URI" --eval 'db.runCommand({ ping: 1 })'

# Verify grants collection exists
mongosh "$MONGO_URI" --eval 'use ailsa_grants; db.grants.countDocuments({})'
```

### Scraping Issues

```bash
# Test with debug logging
python3 -c "
import logging
logging.basicConfig(level=logging.DEBUG)
from src.ingest.nihr_funding import NihrFundingScraper
scraper = NihrFundingScraper()
opp = scraper.scrape('https://www.nihr.ac.uk/funding/team-science-award-cohort-3/2025448')
print(f'Title: {opp.title}')
print(f'Sections: {len(opp.sections)}')
"
```

### Cron Not Running

```bash
# Check crontab
crontab -l

# Check system logs (macOS)
grep CRON /var/log/system.log | tail -20

# Test script manually
bash -x ./run_scraper.sh
```

### Permission Issues

```bash
# Fix script permissions
chmod +x run_scraper.sh cron_job.sh run_ingestion.py

# Fix log directory
mkdir -p logs && chmod 755 logs
```

## Key Features

**Tab-Aware Parsing**
- Detects NIHR's tabbed navigation (`#tab-overview`, `#tab-eligibility`)
- Extracts content from each tab panel
- Creates separate documents per tab

**Change Detection**
- Compares new scrape vs existing database record
- Tracks: status, deadlines, budgets, titles
- Logs all changes with before/after values

**Smart URL Management**
- Automatically queries database for open grants
- Combines with URLs from `data/urls/nihr_urls.txt`
- Deduplicates and prioritizes database URLs

**Embedding Generation**
- OpenAI text-embedding-3-small (1536 dimensions)
- Combines: title, description, funding, key sections
- Context limit: ~3000 tokens per grant

## API Reference

### Main Scraper

```python
from src.ingest.nihr_funding import NihrFundingScraper

scraper = NihrFundingScraper()
opportunity = scraper.scrape(url)

# Returns NihrFundingOpportunity with:
# - title, reference_id, status
# - opening_date, closing_date
# - funding_text, sections, resources
```

### Normalizer

```python
from src.normalize.nihr import normalize_nihr_opportunity

grant, documents = normalize_nihr_opportunity(opportunity)

# Returns:
# - Grant: Structured metadata
# - List[IndexableDocument]: Content for embeddings
```

### Domain Models

```python
from src.core.domain_models import Grant, IndexableDocument

# Grant attributes
grant.id                 # Unique identifier
grant.source            # "nihr"
grant.external_id       # Reference ID (e.g., "2025/448")
grant.title
grant.url
grant.opens_at          # datetime
grant.closes_at         # datetime
grant.total_fund_gbp    # Parsed amount
grant.is_active         # bool
grant.tags              # List[str]

# IndexableDocument attributes
doc.id
doc.grant_id
doc.text                # Extracted content
doc.section_name        # "overview", "eligibility", etc.
doc.source_url          # With fragment (#tab-xyz)
```

## Performance

Typical execution (15 grants):
- Scraping: ~30 seconds
- Embeddings: ~10 seconds
- Database: ~5 seconds
- Total: ~45-60 seconds

API costs:
- OpenAI: ~$0.01-0.02 per run
- Daily schedule: ~$0.30-0.60/month

## Advanced Configuration

### Cron Schedule Examples

```bash
# Daily at 2 AM
0 2 * * *

# Every 6 hours
0 */6 * * *

# Weekdays at 9 AM
0 9 * * 1-5

# First day of month at midnight
0 0 1 * *
```

### Custom Embedding Context

Edit `run_ingestion.py`, function `extract_embedding_text()` to customize what goes into embeddings.

### Database Connection Pooling

For high-frequency runs, consider using connection pooling in `src/storage/`.

## Documentation

- `README.md` - This file (overview & quick reference)
- `docs/CRON_SETUP.md` - Detailed cron setup guide
- `docs/CRON_STATUS.md` - Quick commands & examples
- `docs/SCRAPER_STATUS.md` - Technical architecture
- `docs/DOCKER.md` - Docker deployment guide

## Support

Check logs first: `outputs/logs/scraper_*.log`

Common solutions:
- Import errors: Ensure in project root directory
- DB errors: Verify DATABASE_URL in .env
- Scraping errors: Test with run_scraper.py
- Cron errors: Check permissions on .sh scripts

## License

Internal project - All rights reserved
