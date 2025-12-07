# NIHR Scraper v3 - Installation Guide

This update adapts your **existing NIHR scraper** to use the new `ailsa_shared` v3 schema.
Your existing code (link following, PDF enhancement, etc.) is **preserved unchanged**.

## Files to Install

Copy these two files to your `~/Ailsa/NIHR scraper/` directory:

1. `normalize_nihr_v3.py` - New normalizer that converts scraper output to v3 schema
2. `run_pipeline_v3.py` - Updated pipeline runner that uses the v3 normalizer

## Installation Steps

```bash
# 1. Navigate to your NIHR scraper directory
cd ~/Ailsa/"NIHR scraper"

# 2. Copy the new files (assuming they're in Downloads)
cp ~/Downloads/normalize_nihr_v3.py .
cp ~/Downloads/run_pipeline_v3.py .

# 3. Ensure ailsa_shared is installed
cd ~/Ailsa/ailsa-shared-pkg
pip install -e .

# 4. Return to NIHR scraper
cd ~/Ailsa/"NIHR scraper"
```

## Usage

### Basic test (10 grants, Excel export)
```bash
python run_pipeline_v3.py --limit 10 --dry-run
```

### With link following (slower, more data)
```bash
python run_pipeline_v3.py --limit 10 --dry-run --follow-links
```

### Full run (no limit, no dry-run)
```bash
python run_pipeline_v3.py
```

## What Changed

### Architecture (Preserved)
```
src/
├── ingest/nihr_funding.py      ← UNCHANGED (your existing scraper)
├── enhance/link_follower.py    ← UNCHANGED (your link following)
├── enhance/pdf_enhancer.py     ← UNCHANGED (your PDF extraction)
├── core/money.py               ← UNCHANGED (your money parser)
└── normalize/nihr.py           ← OLD normalizer (kept for reference)

normalize_nihr_v3.py            ← NEW: v3 normalizer
run_pipeline_v3.py              ← NEW: pipeline using v3 normalizer
```

### Output Format (Changed)

**Old format:** Flat Grant + List[IndexableDocument]

**New format:** Sectioned Grant with nested sections:
```python
Grant(
    grant_id="nihr_22_173",
    source=GrantSource.NIHR,
    title="...",
    status=GrantStatus.OPEN,
    sections=GrantSections(
        summary=SummarySection(text="...", programme_name="HTA"),
        eligibility=EligibilitySection(text="...", who_can_apply=[...]),
        scope=ScopeSection(text="...", themes=["Mental Health"]),
        dates=DatesSection(opens_at=..., closes_at=...),
        funding=FundingSection(total_pot_gbp=..., total_pot_display="..."),
        how_to_apply=HowToApplySection(text="...", apply_url="..."),
        assessment=AssessmentSection(guidance_text="..."),
        supporting_info=SupportingInfoSection(documents=[...]),
        contacts=ContactsSection(helpdesk_email="..."),
    ),
    programme=ProgrammeInfo(name="HTA", funder="NIHR", code="HTA"),
    tags=["nihr", "health_research", "hta"],
)
```

## Section Mapping

| NIHR Tab/Section | v3 Section |
|------------------|------------|
| Overview | `summary` |
| Research specification | `scope` |
| Application guidance | `assessment.guidance_text` |
| Application process | `how_to_apply` |
| Contact Details | `contacts` |
| PDFs/Resources | `supporting_info.documents` |

## Expected Output

Running `python run_pipeline_v3.py --limit 10 --dry-run` should produce:

```
======================================================================
NIHR SCRAPER PIPELINE v3
======================================================================
Loaded 10 URLs from data/urls/nihr_urls.txt
Processing 10 opportunities...

[1/10] https://www.nihr.ac.uk/funding/...
✅ 2023 NIHR Academic Clinical Fellowships in Dentistry...

...

======================================================================
PIPELINE COMPLETE
======================================================================
Processed: 10
Success: 10
Failed: 0

Status breakdown:
  closed: 8
  open: 2

Section extraction rates:
  ✅ summary              10/10 (100%)
  ✅ eligibility           9/10 (90%)
  ✅ scope                10/10 (100%)
  ✅ dates                10/10 (100%)
  ⚠️ funding               1/10 (10%)
  ⚠️ how_to_apply          2/10 (20%)
  ✅ assessment            9/10 (90%)
  ✅ supporting_info      10/10 (100%)
  ✅ contacts             10/10 (100%)

Exported 10 grants to grant_test_export_20251204_140000.xlsx
```

## Troubleshooting

### ImportError: No module named 'ailsa_shared'
```bash
cd ~/Ailsa/ailsa-shared-pkg
pip install -e .
```

### ImportError: No module named 'src.ingest.nihr_funding'
Make sure you're running from the NIHR scraper directory:
```bash
cd ~/Ailsa/"NIHR scraper"
python run_pipeline_v3.py --limit 10 --dry-run
```

### pytz not found
```bash
pip install pytz
```
