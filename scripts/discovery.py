#!/usr/bin/env python3
"""
NIHR Funding Opportunities Discovery

Discovers new funding opportunities from the NIHR website by:
1. Scraping the funding opportunities page
2. Extracting all opportunity URLs
3. Comparing against existing URLs in database
4. Adding new URLs to the data/urls/nihr_urls.txt file

Target URL: https://www.nihr.ac.uk/funding-opportunities
"""

import os
import re
import sys
import logging
from pathlib import Path
from datetime import datetime
from typing import List, Set, Optional
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from pymongo import MongoClient

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Load environment
load_dotenv()

# Constants
NIHR_FUNDING_URL = "https://www.nihr.ac.uk/funding-opportunities"
NIHR_BASE_URL = "https://www.nihr.ac.uk"
URLS_FILE = Path(__file__).parent.parent / "data" / "urls" / "nihr_urls.txt"

# HTTP headers
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1"
}


def fetch_page(url: str) -> Optional[str]:
    """Fetch HTML content from URL."""
    try:
        response = requests.get(url, headers=HEADERS, timeout=30)
        response.raise_for_status()
        return response.text
    except requests.RequestException as e:
        logger.error(f"Failed to fetch {url}: {e}")
        return None


def extract_opportunity_urls(html: str) -> List[str]:
    """
    Extract funding opportunity URLs from the NIHR funding opportunities page.

    Looks for links that match the pattern:
    - /funding/{programme}/{opportunity-slug}
    - /funding/{programme}/{opportunity-slug}/{id}

    Returns:
        List of absolute URLs
    """
    soup = BeautifulSoup(html, "lxml")
    urls = []
    seen = set()

    # Find all links
    for link in soup.find_all("a", href=True):
        href = link.get("href", "").strip()

        if not href:
            continue

        # Make absolute URL
        if href.startswith("/"):
            href = urljoin(NIHR_BASE_URL, href)

        # Skip non-NIHR URLs
        if not href.startswith(NIHR_BASE_URL):
            continue

        # Parse URL path
        parsed = urlparse(href)
        path = parsed.path.rstrip("/")
        parts = [p for p in path.split("/") if p]

        # Must be a funding opportunity (at least /funding/programme/opportunity)
        if len(parts) < 3:
            continue

        if parts[0] != "funding":
            continue

        # Skip programme overview pages (e.g., /funding/programme)
        # Valid opportunities have at least 3 parts: /funding/programme/opportunity

        # Skip known non-opportunity pages
        skip_patterns = [
            "/funding-opportunities",
            "/funding/apply",
            "/funding/how-to-apply",
            "/funding/guidance",
            "/funding/support",
        ]

        if any(pattern in href.lower() for pattern in skip_patterns):
            continue

        # Deduplicate
        if href in seen:
            continue
        seen.add(href)

        urls.append(href)
        logger.debug(f"Found opportunity URL: {href}")

    return urls


def scrape_pagination(base_url: str) -> List[str]:
    """
    Scrape all pages of funding opportunities (handles pagination).

    Returns:
        Combined list of all opportunity URLs
    """
    all_urls = []
    page = 0
    max_pages = 20  # Safety limit

    while page < max_pages:
        # Construct paginated URL
        if page == 0:
            url = base_url
        else:
            url = f"{base_url}?page={page}"

        logger.info(f"Fetching page {page + 1}: {url}")

        html = fetch_page(url)
        if not html:
            break

        urls = extract_opportunity_urls(html)

        if not urls:
            logger.info(f"No more opportunities found on page {page + 1}")
            break

        # Check if we got the same URLs (indicates no more pages)
        new_urls = [u for u in urls if u not in all_urls]
        if not new_urls:
            logger.info(f"No new opportunities on page {page + 1}, stopping")
            break

        all_urls.extend(new_urls)
        logger.info(f"Found {len(new_urls)} new opportunities on page {page + 1}")

        page += 1

    return all_urls


def get_existing_urls_from_db() -> Set[str]:
    """Get all existing NIHR grant URLs from MongoDB."""
    try:
        mongo_uri = os.getenv("MONGO_URI", "mongodb://localhost:27017")
        mongo_db_name = os.getenv("MONGO_DATABASE", "nihr_grants")

        client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
        db = client[mongo_db_name]

        # Get all URLs from database
        cursor = db.grants.find({"source": "nihr"}, {"url": 1})
        urls = {doc["url"] for doc in cursor if doc.get("url")}

        client.close()

        logger.info(f"Found {len(urls)} existing URLs in database")
        return urls

    except Exception as e:
        logger.warning(f"Could not connect to MongoDB: {e}")
        return set()


def get_existing_urls_from_file() -> Set[str]:
    """Get existing URLs from the URLs file."""
    urls = set()

    if not URLS_FILE.exists():
        return urls

    with open(URLS_FILE) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                urls.add(line)

    logger.info(f"Found {len(urls)} existing URLs in file")
    return urls


def save_urls_to_file(urls: List[str], append: bool = True):
    """Save URLs to the URLs file."""
    # Ensure directory exists
    URLS_FILE.parent.mkdir(parents=True, exist_ok=True)

    # Read existing content
    existing_content = ""
    if URLS_FILE.exists():
        with open(URLS_FILE) as f:
            existing_content = f.read()

    # Add new URLs
    mode = "a" if append else "w"

    with open(URLS_FILE, mode) as f:
        if append and not existing_content.endswith("\n"):
            f.write("\n")

        f.write(f"\n# Discovered {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        for url in urls:
            f.write(f"{url}\n")

    logger.info(f"Saved {len(urls)} URLs to {URLS_FILE}")


def discover_opportunities(dry_run: bool = False) -> dict:
    """
    Main discovery function.

    Args:
        dry_run: If True, don't write to file

    Returns:
        dict with discovery results
    """
    print("=" * 70)
    print("NIHR FUNDING OPPORTUNITIES DISCOVERY")
    print("=" * 70)
    print(f"\nTarget: {NIHR_FUNDING_URL}")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    # Get existing URLs
    existing_db = get_existing_urls_from_db()
    existing_file = get_existing_urls_from_file()
    existing_all = existing_db | existing_file

    print(f"\n📊 Existing URLs:")
    print(f"   In database: {len(existing_db)}")
    print(f"   In file: {len(existing_file)}")
    print(f"   Total unique: {len(existing_all)}")

    # Discover new opportunities
    print(f"\n🔍 Discovering opportunities from NIHR website...")
    discovered_urls = scrape_pagination(NIHR_FUNDING_URL)

    print(f"\n📋 Discovery Results:")
    print(f"   Total found: {len(discovered_urls)}")

    # Find new URLs
    new_urls = [url for url in discovered_urls if url not in existing_all]

    print(f"   New (not in DB or file): {len(new_urls)}")

    if new_urls:
        print(f"\n🆕 New opportunities discovered:")
        for url in new_urls:
            print(f"   • {url}")

        if not dry_run:
            save_urls_to_file(new_urls, append=True)
            print(f"\n✅ Added {len(new_urls)} new URLs to {URLS_FILE}")
        else:
            print(f"\n⚠️  DRY RUN: Would add {len(new_urls)} URLs to {URLS_FILE}")
    else:
        print(f"\n✓ No new opportunities found")

    print("\n" + "=" * 70)
    print("DISCOVERY COMPLETE")
    print("=" * 70)

    return {
        "discovered": len(discovered_urls),
        "new": len(new_urls),
        "existing_db": len(existing_db),
        "existing_file": len(existing_file),
        "new_urls": new_urls
    }


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Discover new NIHR funding opportunities"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be discovered without writing to file"
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging"
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    try:
        results = discover_opportunities(dry_run=args.dry_run)
        sys.exit(0 if results["new"] >= 0 else 1)
    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted")
        sys.exit(1)
    except Exception as e:
        logger.exception(f"Discovery failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
