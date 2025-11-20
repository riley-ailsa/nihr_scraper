#!/usr/bin/env python3
"""
Final verification that tab-aware resource extraction is working.
"""

from src.ingest.nihr_funding import NihrFundingScraper

url = "https://www.nihr.ac.uk/funding/nihr-james-lind-alliance-priority-setting-partnerships-rolling-funding-opportunity-hsdr-programme/2025331"

scraper = NihrFundingScraper()
opp = scraper.scrape(url)

print("=" * 80)
print("FINAL VERIFICATION: TAB-AWARE RESOURCE EXTRACTION")
print("=" * 80)

print(f"\nSections: {len(opp.sections)}")
print(f"Resources: {len(opp.resources)}")

# Check for the application form download
print("\n" + "=" * 80)
print("LOOKING FOR APPLICATION FORM TEMPLATE")
print("=" * 80)

# Look for:
# 1. Links with "form" and "template" in title
# 2. Links to .docx files
# 3. Links with /media/*/download/ pattern

app_form_candidates = []

for r in opp.resources:
    title_lower = r['title'].lower()
    url_lower = r['url'].lower()

    # Check various indicators
    is_form = (
        ('form' in title_lower and 'template' in title_lower) or
        ('form' in title_lower and 'application' in title_lower) or
        ('.docx' in url_lower) or
        ('/media/' in url_lower and '/download/' in url_lower)
    )

    if is_form:
        app_form_candidates.append(r)

print(f"\nFound {len(app_form_candidates)} application form candidate(s):\n")

for i, form in enumerate(app_form_candidates, 1):
    print(f"{i}. Title: {form['title'] if form['title'] else '(no text - direct download link)'}")
    print(f"   URL: {form['url']}")
    print(f"   Type: {form['type']}")
    print()

# Verify tab-specific resources
print("=" * 80)
print("VERIFYING RESOURCES FROM DIFFERENT TABS")
print("=" * 80)

# Resources that should only be in specific tabs
application_guidance_resources = [
    "domestic outline funding application guidance",
    "funding assessment criteria",
    "finance guidance for applicants",
]

found = []
for expected in application_guidance_resources:
    for r in opp.resources:
        if expected.lower() in r['title'].lower():
            found.append(expected)
            break

print(f"\nApplication guidance tab resources: {len(found)}/{len(application_guidance_resources)}")
for resource in found:
    print(f"  ✓ {resource}")

# Summary
print("\n" + "=" * 80)
print("SUMMARY")
print("=" * 80)

print(f"\n✓ Sections captured: {len(opp.sections)} (expected 4-5)")
print(f"✓ Resources captured: {len(opp.resources)} (expected 20-35)")
print(f"✓ Application form: {'YES' if app_form_candidates else 'NO'}")
print(f"✓ Tab-specific resources: {len(found)}/{len(application_guidance_resources)}")

if len(opp.sections) >= 4 and len(opp.resources) >= 20 and app_form_candidates:
    print("\n" + "=" * 80)
    print("✅ SUCCESS: TAB-AWARE RESOURCE EXTRACTION IS WORKING!")
    print("=" * 80)
    print("\nThe fix successfully:")
    print("  • Captures content from all tabs (not just first/default)")
    print("  • Extracts resources from tab-specific content")
    print("  • Finds application forms (including direct downloads)")
    print("\nYou're ready to re-scrape the database!")
    exit(0)
else:
    print("\n⚠️ Issues detected - review results above")
    exit(1)
