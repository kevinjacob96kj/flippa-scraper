"""Collect public Flippa listing names for US businesses under a price cap.

Uses Flippa's public search pages (the same pages a browser loads). Search is
allowed by robots.txt. Requests are paced so the crawl stays light.

Only country and maximum price are applied. Every other Flippa search filter
is left unset.

Flippa shows a listing title, not always a legal entity name. Confidential
listings keep the real name hidden.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import math
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

SEARCH_URL = "https://flippa.com/search"
USER_AGENT = "flippa-scraper/0.1 (personal research; rate-limited)"
PAGE_SIZE = 100
NONE = "none"

LISTING_SPLIT = re.compile(r'<li id="listing-')
TOTAL_RE = re.compile(
    r"of <span[^>]*>([\d,]+)</span>",
)
TITLE_RE = re.compile(
    r'class="[^"]*GTM-search-result-card"[^>]*>\s*([^<]+?)\s*</a>',
)
LOCATION_RE = re.compile(
    r"map-pin-outline[\s\S]{0,400}?<span>([^<]+)</span>",
)
SALE_LABEL_RE = re.compile(
    r'tw-font-mon tw-text-black">([^<]+)</p>',
)
STRIKETHROUGH_RE = re.compile(
    r'<span class="[^"]*line-through[^"]*">[\s\S]*?</span>',
)
PRICE_RE = re.compile(r"USD\s*\$([0-9][0-9,]*)")
TYPE_RE = re.compile(
    r">Type</p>\s*<p[^>]*>\s*([^<]+)",
)


def search_filters(max_price: int, country: str) -> list[tuple[str, str]]:
    """Every Flippa search filter. Only country and price maximum are set."""
    country_label = "United States" if country == "us" else country
    return [
        ("Keyword", NONE),
        ("Managed by", NONE),
        ("Price minimum", NONE),
        ("Price maximum", f"under ${max_price:,}"),
        ("Category type", NONE),
        ("Country", country_label),
        ("Business age minimum", NONE),
        ("Business age maximum", NONE),
        ("Monthly profit minimum", NONE),
        ("Monthly profit maximum", NONE),
        ("Monthly revenue minimum", NONE),
        ("Monthly revenue maximum", NONE),
        ("Profit multiple minimum", NONE),
        ("Profit multiple maximum", NONE),
        ("Revenue multiple minimum", NONE),
        ("Revenue multiple maximum", NONE),
        ("Industry", NONE),
        ("Monthly users minimum", NONE),
        ("Monthly users maximum", NONE),
        ("Monthly pageviews minimum", NONE),
        ("Monthly pageviews maximum", NONE),
        ("Monthly app downloads minimum", NONE),
        ("Monthly app downloads maximum", NONE),
        ("Sale type", NONE),
        ("Status", NONE),
        ("Sort", NONE),
    ]


def format_filters(filters: list[tuple[str, str]]) -> str:
    width = max(len(label) for label, _value in filters)
    lines = [f"{label:<{width}}  {value}" for label, value in filters]
    return "\n".join(lines)


def build_url(max_price: int, country: str, page: int) -> str:
    # Flippa's price filter is inclusive, so cap one dollar below the limit
    # when the caller asked for listings under that amount.
    # Status, category, sale type, sort, and the other filters stay unset.
    query = {
        "filter[price][max]": str(max_price),
        "filter[seller_location][]": country,
        "page_size": str(PAGE_SIZE),
        "pagination": "true",
    }
    if page > 1:
        query["page"] = str(page)
    return SEARCH_URL + "?" + urllib.parse.urlencode(query)


def fetch(url: str, timeout: float) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    last_error: Exception | None = None
    for attempt in range(4):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as error:
            last_error = error
            if error.code not in {429, 500, 502, 503, 504} or attempt == 3:
                raise
            time.sleep(2 ** attempt)
        except urllib.error.URLError as error:
            last_error = error
            if attempt == 3:
                raise
            time.sleep(2 ** attempt)
    raise RuntimeError(f"failed to fetch {url}: {last_error}")


def parse_price(block: str) -> int | None:
    label = SALE_LABEL_RE.search(block)
    region = block[label.end() :] if label else block
    region = STRIKETHROUGH_RE.sub("", region)
    match = PRICE_RE.search(region)
    if not match:
        return None
    return int(match.group(1).replace(",", ""))


def parse_listings(page_html: str) -> list[dict]:
    listings: list[dict] = []
    for block in LISTING_SPLIT.split(page_html)[1:]:
        listing_id = block.split('"', 1)[0]
        title_match = TITLE_RE.search(block)
        location_match = LOCATION_RE.search(block)
        type_match = TYPE_RE.search(block)
        if not title_match or not listing_id.isdigit():
            continue
        name = html.unescape(title_match.group(1)).strip()
        location = (
            html.unescape(location_match.group(1)).strip()
            if location_match
            else ""
        )
        listings.append(
            {
                "listing_id": listing_id,
                "name": name,
                "price_usd": parse_price(block),
                "location": location,
                "type": html.unescape(type_match.group(1)).strip() if type_match else "",
                "url": f"https://flippa.com/{listing_id}",
            }
        )
    return listings


def total_results(page_html: str) -> int | None:
    match = TOTAL_RE.search(page_html)
    if not match:
        return None
    return int(match.group(1).replace(",", ""))


def scrape(max_price: int, country: str, delay: float, timeout: float) -> list[dict]:
    # Ask Flippa for prices strictly below the cap.
    price_filter = max_price - 1
    print(format_filters(search_filters(max_price, country)), file=sys.stderr)
    print(file=sys.stderr)
    first_url = build_url(price_filter, country, 1)
    print(f"Fetching {first_url}", file=sys.stderr)
    first_html = fetch(first_url, timeout)
    reported = total_results(first_html)
    if reported is None:
        raise RuntimeError("Could not read the result count from the search page.")
    pages = max(1, math.ceil(reported / PAGE_SIZE))
    print(f"Flippa reports {reported} listings across {pages} pages.", file=sys.stderr)

    found: dict[str, dict] = {}
    for page in range(1, pages + 1):
        page_html = first_html if page == 1 else fetch(build_url(price_filter, country, page), timeout)
        batch = parse_listings(page_html)
        kept = 0
        for item in batch:
            price = item["price_usd"]
            location = item["location"]
            if price is None or price >= max_price:
                continue
            if "United States" not in location:
                continue
            found[item["listing_id"]] = item
            kept += 1
        print(
            f"Page {page}/{pages}: parsed {len(batch)}, kept {kept}, total {len(found)}",
            file=sys.stderr,
        )
        if page < pages:
            time.sleep(delay)
    return sorted(found.values(), key=lambda item: (item["price_usd"], item["name"].lower()))


def write_outputs(listings: list[dict], output_dir: Path, filters: list[tuple[str, str]]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "businesses.csv"
    json_path = output_dir / "businesses.json"
    names_path = output_dir / "names.txt"
    filters_path = output_dir / "filters.txt"
    filters_path.write_text(format_filters(filters) + "\n", encoding="utf-8")

    fieldnames = ["name", "price_usd", "location", "type", "listing_id", "url"]
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(listings)
    json_path.write_text(json.dumps(listings, indent=2), encoding="utf-8")
    names_path.write_text(
        "\n".join(item["name"] for item in listings) + ("\n" if listings else ""),
        encoding="utf-8",
    )
    print(f"Wrote {len(listings)} listings to {csv_path}", file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Save names of Flippa businesses in the United States under a price."
    )
    parser.add_argument(
        "--max-price",
        type=int,
        default=10000,
        help="Keep listings priced strictly below this amount in USD (default: 10000).",
    )
    parser.add_argument(
        "--country",
        default="us",
        help="Flippa seller-location code (default: us).",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=1.5,
        help="Seconds to wait between pages (default: 1.5).",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=60,
        help="HTTP timeout in seconds (default: 60).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("output"),
        help="Directory for businesses.csv, businesses.json, names.txt, and filters.txt.",
    )
    args = parser.parse_args()
    if args.max_price < 1:
        parser.error("--max-price must be at least 1")

    filters = search_filters(args.max_price, args.country)
    listings = scrape(args.max_price, args.country, args.delay, args.timeout)
    write_outputs(listings, args.output, filters)


if __name__ == "__main__":
    main()
