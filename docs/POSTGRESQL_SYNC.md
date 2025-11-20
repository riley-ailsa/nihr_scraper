# PostgreSQL Sync & Budget Extraction

## Overview

This document describes the PostgreSQL synchronization and budget extraction pipeline for NIHR grants.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Data Flow Pipeline                        │
└─────────────────────────────────────────────────────────────┘

1. SCRAPING (ingest_nihr.py)
   └─> Fetch NIHR grant pages
       └─> Extract metadata + documents (PDFs, linked pages)
           └─> Store in Pinecone as embeddings

2. SYNC (sync_pinecone_to_postgres.py) - ONE-TIME SETUP
   └─> Query Pinecone for grant metadata
       └─> Extract unique grants from document chunks
           └─> Insert into PostgreSQL grants table

3. BUDGET EXTRACTION (extract_funding_from_docs.py) - AUTOMATED
   └─> Query Pinecone for document chunks
       └─> Search for funding patterns (£X million, up to £X, etc.)
           └─> Update PostgreSQL with extracted budgets

4. CRON (run_scraper.sh) - AUTOMATED DAILY
   └─> Run ingest_nihr.py (scraping + Pinecone)
       └─> Run extract_funding_from_docs.py (budget extraction)
```

## Scripts

### 1. sync_pinecone_to_postgres.py (One-Time Setup)

**Purpose:** Initial sync of existing Pinecone data to PostgreSQL.

**Usage:**
```bash
python3 sync_pinecone_to_postgres.py
```

**What it does:**
- Queries Pinecone for all NIHR document chunks
- Extracts unique grant metadata (grant_id, title, status, dates, etc.)
- Inserts 450 grants into PostgreSQL
- Uses UPSERT to handle existing records

**When to run:**
- First time setting up PostgreSQL
- After major Pinecone data refresh
- To backfill missing grants

**Output:**
```
✅ Found 450 unique NIHR grants
✅ Inserted: 450
📊 PostgreSQL (NIHR):
   Total: 450 grants
   Open: 70 grants
   Closed: 380 grants
```

### 2. extract_funding_from_docs.py (Automated)

**Purpose:** Extract budget information from embedded documents.

**Usage:**
```bash
python3 extract_funding_from_docs.py
```

**What it does:**
- Queries Pinecone for document chunks (20 batches of 10k vectors)
- Searches text for funding patterns:
  - "up to £X million"
  - "funding of £X"
  - "budget limit of £X"
  - "awards of £X"
- Selects most reliable amount per grant (prioritizes official sections)
- Updates PostgreSQL with extracted budgets

**Pattern Recognition:**
- Uses regex to find currency amounts
- Handles formats: £4m, £600,000, £1.5M, £4 million
- Prioritizes doc types:
  1. `nihr_section::overview` (priority 10)
  2. `nihr_section::research-specification` (priority 9)
  3. `pdf` (priority 7)
  4. `linked_page` (priority 5)

**When to run:**
- After every ingestion run (automated in cron)
- When budget coverage needs improvement
- After scraping new grants

**Output:**
```
✅ Found funding info for 422 grants
✅ Updated: 324
⏭️  Skipped (already has funding): 98
📊 PostgreSQL (NIHR):
   With budget: 422 (93%)
   Without budget: 28 (6%)
```

### 3. run_scraper.sh (Cron Runner)

**Purpose:** Automated pipeline runner for cron jobs.

**Usage:**
```bash
./run_scraper.sh
```

**Pipeline:**
```bash
1. Activate virtual environment
2. Run ingest_nihr.py
   └─> Scrape grants → PostgreSQL + Pinecone
3. Run extract_funding_from_docs.py
   └─> Extract budgets → PostgreSQL
4. Log results with timestamps
5. Clean up logs older than 30 days
```

**Exit codes:**
- `0`: Both ingestion and extraction succeeded
- `1`: Either step failed

## Data Quality

### Current State

| Metric | Value |
|--------|-------|
| Total NIHR grants | 450 |
| Open grants | 70 (16%) |
| Closed grants | 380 (84%) |
| **Grants with budget** | **422 (93%)** |
| Grants without budget | 28 (6%) |

### Budget Distribution

| Range | Count | Percentage |
|-------|-------|------------|
| No budget | 28 | 6% |
| < £100k | 265 | 59% |
| £100k - £500k | 28 | 6% |
| £500k - £1m | 23 | 5% |
| £1m - £5m | 31 | 7% |
| £5m+ | 75 | 17% |

### Improvement

**Before budget extraction:**
- 98 grants with budget (22%)
- 352 grants missing budgets (78%)

**After budget extraction:**
- 422 grants with budget (93%) ✅
- 28 grants without budgets (6%)
- **+324 grants improved** 🎉

## Storage Architecture

### PostgreSQL (Relational Data)

**Purpose:** Fast filtering, user interactions, analytics

**Schema:**
```sql
CREATE TABLE grants (
    grant_id VARCHAR(255) PRIMARY KEY,
    source VARCHAR(50) NOT NULL,
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    status VARCHAR(50),
    open_date DATE,
    close_date DATE,
    budget_min BIGINT,
    budget_max BIGINT,
    tags TEXT[],
    description_summary TEXT,
    scraped_at TIMESTAMP,
    updated_at TIMESTAMP,
    ...
);
```

**Queries enabled:**
- Filter by status: `WHERE status = 'Open'`
- Filter by deadline: `WHERE close_date > NOW()`
- Filter by budget: `WHERE budget_max BETWEEN 100000 AND 500000`
- Search by tags: `WHERE 'research' = ANY(tags)`

### Pinecone (Vector Embeddings)

**Purpose:** Semantic search, document retrieval

**Index:** `ailsa-grants`
- **Total vectors:** 112,468
- **Dimensions:** 1536 (OpenAI text-embedding-3-small)
- **NIHR vectors:** ~40,000 (document chunks)

**Metadata structure:**
```json
{
  "grant_id": "nihr_97053",
  "doc_id": "nihr_97053_link_7efd7c591681e0c6",
  "doc_type": "linked_page",
  "source": "nihr",
  "title": "THCS Partnership Joint Transnational Call 2026",
  "status": "open",
  "closes_at": "2026-02-02T00:00:00",
  "total_fund_gbp": 0.0,
  "text": "Are you eligible for funding?..."
}
```

**Document types:**
- `linked_page`: External guidance pages
- `pdf`: PDF documents
- `nihr_section::overview`: Grant overview
- `nihr_section::research-specification`: Research requirements
- `nihr_section::application-guidance`: Application instructions

## Cron Schedule

### Recommended: Daily at 2:00 AM

```bash
0 2 * * * /Users/rileycoleman/NIHR\ scraper/run_scraper.sh >> /Users/rileycoleman/NIHR\ scraper/logs/cron.log 2>&1
```

**Setup:**
```bash
./setup_cron.sh
# Choose option 1: Daily at 2:00 AM
```

**Why daily?**
- NIHR grants change infrequently (not like Horizon Europe)
- Catches deadline extensions and status changes
- Low API costs (~$0.45/month)
- Runs during off-peak hours

## Monitoring

### Check Latest Run

```bash
ls -lt logs/scraper_*.log | head -1 | awk '{print $9}' | xargs tail -50
```

### Verify Budget Coverage

```bash
psql $DATABASE_URL -c "
SELECT
    COUNT(*) FILTER (WHERE budget_max > 0) as with_budget,
    COUNT(*) FILTER (WHERE budget_max IS NULL OR budget_max = 0) as without_budget,
    ROUND(100.0 * COUNT(*) FILTER (WHERE budget_max > 0) / COUNT(*), 1) as coverage_pct
FROM grants
WHERE source = 'nihr';
"
```

Expected output:
```
 with_budget | without_budget | coverage_pct
-------------+----------------+--------------
         422 |             28 |         93.8
```

### Check Recent Updates

```bash
psql $DATABASE_URL -c "
SELECT grant_id, title, budget_max, updated_at
FROM grants
WHERE source = 'nihr'
ORDER BY updated_at DESC
LIMIT 10;
"
```

## Troubleshooting

### Budget extraction finds no grants

**Problem:** `Found funding info for 0 grants`

**Solutions:**
1. Check Pinecone has NIHR data:
   ```bash
   python3 test_connections.py
   ```
2. Verify document chunks exist:
   ```bash
   python3 -c "
   from pinecone import Pinecone
   import os
   pc = Pinecone(api_key=os.getenv('PINECONE_API_KEY'))
   index = pc.Index('ailsa-grants')
   results = index.query(vector=[0]*1536, top_k=1, filter={'source': 'nihr'})
   print(f'Found {len(results[\"matches\"])} NIHR vectors')
   "
   ```

### PostgreSQL sync creates duplicates

**Problem:** Multiple grants with same ID

**Solution:**
- This shouldn't happen due to UPSERT (`ON CONFLICT DO UPDATE`)
- If it does, check for race conditions in concurrent runs
- Verify PRIMARY KEY constraint exists:
  ```sql
  SELECT constraint_name
  FROM information_schema.table_constraints
  WHERE table_name = 'grants' AND constraint_type = 'PRIMARY KEY';
  ```

### Budget amounts seem incorrect

**Problem:** Budget shows £600m for a small grant

**Explanation:**
- Some grants mention total programme budgets (e.g., "part of £600m initiative")
- Pattern matching can pick up these larger context amounts

**Solutions:**
1. Add upper bound validation (e.g., max £100m per grant)
2. Improve pattern matching to distinguish grant vs. programme budgets
3. Manually correct outliers in database

## Manual Operations

### Re-sync specific grant

```bash
python3 -c "
from src.ingest.nihr_funding import NihrFundingScraper
from src.normalize.nihr import normalize_nihr_opportunity
import psycopg2
import os

scraper = NihrFundingScraper()
opp = scraper.scrape('https://www.nihr.ac.uk/funding/...')
grant, docs = normalize_nihr_opportunity(opp)

conn = psycopg2.connect(os.getenv('DATABASE_URL'))
cursor = conn.cursor()
cursor.execute('''
    UPDATE grants
    SET title = %s, status = %s, budget_max = %s, updated_at = NOW()
    WHERE grant_id = %s
''', (grant.title, 'Open' if grant.is_active else 'Closed', grant.total_fund_gbp, grant.id))
conn.commit()
print(f'Updated {grant.id}')
"
```

### Bulk budget re-extraction

```bash
# Clear all budgets
psql $DATABASE_URL -c "
UPDATE grants
SET budget_min = NULL, budget_max = NULL
WHERE source = 'nihr';
"

# Re-extract from documents
python3 extract_funding_from_docs.py
```

### Export to CSV

```bash
psql $DATABASE_URL -c "
COPY (
    SELECT grant_id, title, status, open_date, close_date, budget_max, url
    FROM grants
    WHERE source = 'nihr'
    ORDER BY close_date DESC NULLS LAST
) TO STDOUT WITH CSV HEADER
" > nihr_grants_export.csv
```

## Future Improvements

### 1. Smarter Budget Extraction

- Use LLM to parse complex funding descriptions
- Distinguish between grant budget vs. programme budget
- Extract budget ranges (min/max) separately

### 2. Real-Time Updates

- Webhook from NIHR RSS feed
- Event-driven ingestion on new grants
- Instant notifications for changes

### 3. Historical Tracking

- Store grant snapshots in `grants_history` table
- Track all changes over time
- Analyze deadline extension patterns

### 4. Budget Validation

- Add sanity checks (e.g., max £100m per grant)
- Flag outliers for manual review
- Cross-reference with official NIHR data

## Related Documentation

- [CRON_SETUP.md](CRON_SETUP.md) - Automated scheduling
- [DOCKER.md](DOCKER.md) - Docker deployment
- [DEPLOYMENT.md](../DEPLOYMENT.md) - Production setup
- [schema.sql](../schema.sql) - Database schema

## Support

For issues or questions:
1. Check logs: `tail -f logs/scraper_*.log`
2. Verify connections: `python3 test_connections.py`
3. Review this documentation
4. Check GitHub issues: [NIHR Scraper Issues](https://github.com/riley-ailsa/nihr_scraper/issues)
