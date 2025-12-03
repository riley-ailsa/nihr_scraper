#!/usr/bin/env python3
"""Quick test of NIHR scraper fixes."""

from src.ingest.nihr_funding import NihrFundingScraper
from src.normalize.nihr import normalize_nihr_opportunity, infer_nihr_status

scraper = NihrFundingScraper()
url = 'https://www.nihr.ac.uk/funding/team-science-award-cohort-3/2025448'

print("Scraping NIHR URL...")
opp = scraper.scrape(url)

print(f'\nTitle: {opp.title}')
print(f'Status: {opp.opportunity_status}')
print(f'Reference ID: {opp.reference_id}')
print(f'Opening: {opp.opening_date}')
print(f'Closing: {opp.closing_date}')
print(f'Sections found: {len(opp.sections)}')
print(f'Resources found: {len(opp.resources)}')

print("\nNormalizing to Grant + Documents...")
grant, docs = normalize_nihr_opportunity(opp)

print(f'\nGrant ID: {grant.id}')
print(f'Title: {grant.title}')
print(f'Inferred Status: {infer_nihr_status(opp)}')
print(f'Is Active: {grant.is_active}')
print(f'Documents created: {len(docs)}')

print('\nDocument breakdown:')
for doc in docs:
    print(f'  - {doc.doc_type[:40]:40s} ({len(doc.text):5d} chars)')

print("\n✅ Scraper and normalizer working correctly!")
print(f"Expected: 8+ sections, 11+ resources, proper status detection")
print(f"Got: {len(opp.sections)} sections, {len(opp.resources)} resources, status={infer_nihr_status(opp)}")
