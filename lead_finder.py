"""
lead_finder.py — Find real local businesses via Google Maps/Search

Searches Google Maps for businesses by type and location,
returns structured lead data ready for outreach.

Usage:
    from lead_finder import find_leads, search_google_maps
    leads = await find_leads("restaurants", "Flagstaff AZ", limit=10)
"""

import os
import json
import re
import time
import logging
import asyncio
import httpx
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("lead_finder")

LEADS_DIR = "./data/leads"
SERPAPI_KEY = os.getenv("SERPAPI_KEY", "")  # Optional: for structured Google results


async def search_google_maps(query: str, location: str = "Flagstaff, AZ", limit: int = 10) -> list[dict]:
    """
    Search Google Maps for businesses.
    Uses SerpAPI if key available, falls back to web scraping.
    Returns list of business dicts with name, address, phone, rating, etc.
    """
    businesses = []

    # Try SerpAPI first (structured, reliable)
    if SERPAPI_KEY:
        businesses = await _search_serpapi(query, location, limit)

    # Fallback: DuckDuckGo + Google Maps scraping
    if not businesses:
        businesses = await _search_web_fallback(query, location, limit)

    return businesses[:limit]


async def _search_serpapi(query: str, location: str, limit: int) -> list[dict]:
    """Search via SerpAPI Google Maps endpoint."""
    try:
        params = {
            "engine": "google_maps",
            "q": f"{query} in {location}",
            "type": "search",
            "api_key": SERPAPI_KEY,
            "num": min(limit, 20),
        }
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get("https://serpapi.com/search", params=params)
            if resp.status_code != 200:
                logger.warning(f"SerpAPI returned {resp.status_code}")
                return []
            data = resp.json()

        results = []
        for place in data.get("local_results", []):
            results.append({
                "business_name": place.get("title", ""),
                "address": place.get("address", ""),
                "phone": place.get("phone", ""),
                "website": place.get("website", ""),
                "rating": place.get("rating"),
                "reviews": place.get("reviews"),
                "business_type": place.get("type", query),
                "hours": place.get("hours", ""),
                "gps_coordinates": place.get("gps_coordinates", {}),
                "place_id": place.get("place_id", ""),
                "source": "serpapi_google_maps",
            })
        return results
    except Exception as e:
        logger.error(f"SerpAPI search failed: {e}")
        return []


async def _search_web_fallback(query: str, location: str, limit: int) -> list[dict]:
    """Fallback: use multiple search strategies to find individual businesses."""
    results = []

    # Strategy 1: Search for specific individual businesses with phone numbers
    searches = [
        f"{query} {location} phone number site:yelp.com",
        f"best {query} in {location} phone address",
        f"{query} near {location} contact",
    ]

    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        for search_query in searches:
            if len(results) >= limit:
                break
            try:
                resp = await client.get(
                    "https://html.duckduckgo.com/html/",
                    params={"q": search_query},
                    headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}
                )
                html = resp.text

                # Extract result blocks
                blocks = re.findall(
                    r'<a[^>]*class="result__a"[^>]*href="([^"]*)"[^>]*>(.*?)</a>.*?<a[^>]*class="result__snippet"[^>]*>(.*?)</a>',
                    html, re.DOTALL
                )

                for url, title, snippet in blocks:
                    title = re.sub(r'<[^>]+>', '', title).strip()
                    snippet = re.sub(r'<[^>]+>', '', snippet).strip()

                    # Extract phone numbers
                    phones = re.findall(r'\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}', snippet)
                    phone = phones[0] if phones else ""

                    # Clean business name from title
                    name = title.split(" - ")[0].split(" | ")[0].split(" :: ")[0].strip()

                    # Skip aggregator/list pages
                    skip_words = ['best 10', 'top 10', 'best restaurants', 'the best', 'top rated',
                                  'tripadvisor', 'yelp.com/search', 'yellowpages', 'list of', 'directory']
                    if any(sw in name.lower() for sw in skip_words):
                        continue
                    if any(sw in name.lower() for sw in skip_words):
                        continue

                    # For Yelp URLs, extract the business name more cleanly
                    if 'yelp.com/biz/' in url:
                        # Yelp title format: "Business Name - Yelp"
                        name = title.replace(" - Yelp", "").replace(" - Updated", "").strip()
                        name = re.sub(r'\s*\d+\s*$', '', name)  # Remove trailing numbers

                    # Skip generic/useless results
                    if len(name) < 4 or len(name) > 80:
                        continue
                    if query.lower().replace(' ', '') == name.lower().replace(' ', ''):
                        continue

                    # Extract address from snippet
                    address = _extract_address(snippet, location)

                    # Get actual website (not yelp/tripadvisor)
                    website = ""
                    if 'yelp.com' not in url and 'tripadvisor.com' not in url and 'facebook.com' not in url:
                        # Unwrap DuckDuckGo redirect
                        if 'uddg=' in url:
                            import urllib.parse
                            parsed = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
                            website = parsed.get('uddg', [''])[0]
                        else:
                            website = url

                    results.append({
                        "business_name": name,
                        "address": address,
                        "phone": phone,
                        "website": website,
                        "rating": None,
                        "reviews": None,
                        "business_type": query,
                        "hours": "",
                        "source": "web_search",
                        "snippet": snippet[:200],
                    })
            except Exception as e:
                logger.warning(f"Search query failed: {search_query} — {e}")
                continue

    # Deduplicate by business name
    seen = set()
    unique = []
    for r in results:
        name_key = re.sub(r'[^a-z0-9]', '', r["business_name"].lower())
        if name_key not in seen and len(name_key) > 3:
            seen.add(name_key)
            unique.append(r)

    return unique[:limit]


def _extract_address(text: str, location: str) -> str:
    """Try to extract a street address from text."""
    # Look for patterns like "123 N Main St, Flagstaff"
    addr_pattern = r'\d+\s+[A-Z][a-zA-Z\s]+(?:St|Ave|Rd|Dr|Blvd|Way|Ln|Ct|Pl|Hwy|Route)\b[^,]*,?\s*(?:Flagstaff|' + re.escape(location.split(',')[0]) + r')[^,]*'
    match = re.search(addr_pattern, text, re.IGNORECASE)
    if match:
        return match.group(0).strip().rstrip(',')
    return ""


async def find_leads(
    business_type: str,
    location: str = "Flagstaff, AZ",
    limit: int = 10,
    save: bool = True,
) -> list[dict] | list[str]:
    """
    Find real business leads by type and location.
    Searches Google Maps, enriches data, optionally saves to leads dir.

    Args:
        business_type: "restaurants", "barbershops", "dental offices", "auto shops", "real estate"
        location: City and state
        limit: Max results
        save: Save to /data/leads/ as JSON files

    Returns:
        List of lead dicts or list of saved file paths if save is True
    """
    logger.info(f"Finding {business_type} in {location} (limit={limit})")

    os.makedirs(LEADS_DIR, exist_ok=True)
    all_leads = []
    saved_lead_paths = []

    # Search for businesses
    raw = await search_google_maps(business_type, location, limit)

    if not raw:
        logger.warning(f"No results for {business_type} in {location}")
        return []

    # Enrich and format as leads
    leads = []
    ts = datetime.now(timezone.utc)

    for biz in raw:
        if not biz.get("business_name"):
            continue

        # Slugify name
        slug = re.sub(r'[^a-z0-9]+', '-', biz["business_name"].lower()).strip('-')[:40]
        ts_str = ts.strftime("%Y%m%d_%H%M%S")
        lead_id = f"lead-{ts_str}-{slug}"

        lead = {
            "lead_id": lead_id,
            "business_name": biz["business_name"],
            "business_type": business_type,
            "owner_name": "",  # Unknown from search — fill in after contact
            "phone": biz.get("phone", ""),
            "email": "",  # Unknown from search
            "website_url": biz.get("website", ""),
            "address": biz.get("address", ""),
            "rating": biz.get("rating"),
            "reviews": biz.get("reviews"),
            "hours": biz.get("hours", ""),
            "services": [],
            "budget": None,
            "notes": biz.get("snippet", ""),
            "source": f"google_search_{business_type}",
            "created_at": ts.isoformat(),
            "status": "prospecting",
        }

        if save:
            Path(LEADS_DIR).mkdir(parents=True, exist_ok=True)
            lead_path = os.path.join(LEADS_DIR, f"{ts_str}_{slug}.json")
            with open(lead_path, "w") as f:
                json.dump(lead, f, indent=2)
            saved_lead_paths.append(lead_path)

        leads.append(lead)
        # Small delay to avoid rate limiting
        ts = datetime.now(timezone.utc)

    logger.info(f"Found {len(leads)} leads for {business_type} in {location}")
    return saved_lead_paths if save else leads


async def find_leads_multi(
    business_types: list[str],
    location: str = "Flagstaff, AZ",
    limit_per_type: int = 5,
) -> dict[str, list[dict]]:
    """
    Search for multiple business types at once.
    Returns dict mapping type -> leads list.
    """
    results = {}
    for btype in business_types:
        results[btype] = await find_leads(btype, location, limit_per_type, save=True)
    return results

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Find business leads.")
    parser.add_argument("business_type", type=str, help="Type of business to search for (e.g., 'restaurants', 'dental').")
    parser.add_argument("location", type=str, default="Flagstaff, AZ", help="Location to search in.")
    parser.add_argument("--limit", type=int, default=10, help="Maximum number of leads to find.")
    parser.add_argument("--save", action="store_true", help="Save leads to JSON files.")
    args = parser.parse_args()

    asyncio.run(find_leads(args.business_type, args.location, args.limit, args.save))