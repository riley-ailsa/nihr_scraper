#!/usr/bin/env python3
"""Test extracting resources from NIHR grants."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.ingest.nihr_funding import NihrFundingScraper
import json

def test_nihr_resources():
    """Test resource extraction from NIHR pages."""

    # Test URL from existing database
    test_url = "https://www.nihr.ac.uk/funding/research-patient-benefit-november-2025/2025425-2025426-2025437"

    scraper = NihrFundingScraper()

    print(f"Testing URL: {test_url}")
    print("=" * 80)

    try:
        opportunity = scraper.scrape(test_url)

        print(f"Title: {opportunity.title}")
        print(f"Sections found: {len(opportunity.sections)}")
        print(f"Resources found: {len(opportunity.resources)}")

        if opportunity.resources:
            print("\nResources extracted:")
            for i, resource in enumerate(opportunity.resources, 1):
                print(f"\n{i}. {resource.get('title', 'Untitled')}")
                print(f"   Type: {resource.get('type', 'unknown')}")
                print(f"   URL: {resource.get('url', 'no url')[:100]}...")
                if resource.get('description'):
                    print(f"   Description: {resource['description'][:100]}...")
        else:
            print("\nNo resources found!")

        # Let's check sections for PDFs
        print("\n" + "=" * 80)
        print("Checking sections for PDF links:")
        for section in opportunity.sections:
            if section.get('content'):
                # Simple check for PDF links in content
                content = section['content'].lower()
                if '.pdf' in content or 'download' in content:
                    print(f"\nSection '{section.get('name', 'unknown')}' may contain PDFs/downloads")

        # Save full data for inspection
        with open('/tmp/nihr_opportunity_data.json', 'w') as f:
            json.dump({
                'title': opportunity.title,
                'sections': opportunity.sections,
                'resources': opportunity.resources,
                'key_dates': opportunity.key_dates
            }, f, indent=2, default=str)
            print(f"\nFull data saved to /tmp/nihr_opportunity_data.json for inspection")

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_nihr_resources()