"""Collect public Flippa listings using the filters in output/filters.txt.

Uses Flippa's public search pages (the same pages a browser loads). Search is
allowed by robots.txt. Requests are paced so the crawl stays light.

Edit the value column in filters.txt, then run this script. A value of none
leaves that filter off. Seller ID / phone and the checklist at the bottom are
notes: they stay in the file and are not sent to Flippa.

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
PUBLIC_FIELDS = [
    "name",
    "price_usd",
    "location",
    "type",
    "monthly_profit_usd",
    "profit_multiple",
    "age",
    "verifications",
    "listing_id",
    "url",
]
ANALYTICS_BADGE = "Google Analytics"
REQUIRED = "required on the listing"

LABELS = [
    "Keyword",
    "Managed by",
    "Price minimum",
    "Price maximum",
    "Category type",
    "Country",
    "Business age minimum",
    "Business age maximum",
    "Monthly profit minimum",
    "Monthly profit maximum",
    "Monthly revenue minimum",
    "Monthly revenue maximum",
    "Profit multiple",
    "Revenue multiple minimum",
    "Revenue multiple maximum",
    "Industry",
    "Monthly users minimum",
    "Monthly users maximum",
    "Monthly pageviews minimum",
    "Monthly pageviews maximum",
    "Monthly app downloads minimum",
    "Monthly app downloads maximum",
    "Sale type",
    "Status",
    "Sort",
    "Google Analytics",
    "Verified revenue",
    "Seller ID / phone",
]

CATEGORIES = {
    "ecommerce": "ecommerce",
    "content": "content",
    "saas": "saas",
    "youtube channels": "youtube-channels",
    "amazon kdp": "amazon-kdp",
    "amazon fba": "amazon-fba",
    "ios apps": "ios-apps",
    "android apps": "android-apps",
    "digital agencies": "digital-agencies",
    "services": "services",
    "ai apps & tools": "ai-apps-and-tools",
    "marketplaces": "marketplaces",
    "social media accounts": "social-media-accounts",
    "newsletters": "newsletters",
    "plugins & extensions": "plugins-and-extensions",
    "crypto & blockchain": "crypto-and-blockchain",
    "projects & concepts": "projects-and-concepts",
    "domains": "domain",
    "other": "other",
}
MANAGED_BY = {
    "brokered by flippa": "flippa_broker",
    "listed by owner": "owner",
    "listed by partner broker": "partner_broker",
}
INDUSTRIES = {
    "automotive": "automotive",
    "business": "business",
    "design and style": "design-and-style",
    "education": "education",
    "electronics": "electronics",
    "entertainment": "entertainment",
    "lifestyle": "lifestyle",
    "food and drink": "food-and-drink",
    "general knowledge": "general-knowledge",
    "health and beauty": "health-and-beauty",
    "hobbies and games": "hobbies-and-games",
    "home and garden": "home-and-garden",
    "internet": "internet",
    "sports and outdoor": "sports-and-outdoor",
    "travel": "travel",
}
SALE_TYPES = {
    "classified": "classified",
    "auction": "auction",
}
STATUSES = {
    "open": "open",
    "recently sold": "won",
}
SORTS = {
    "most relevant": "",
    "most active": "most_active",
    "lowest price": "lowest_price",
    "highest price": "highest_price",
    "most recent": "most_recent",
    "ending soonest": "ending_soonest",
    "most profitable": "most_profitable",
}

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
METRIC_RE = {
    "type": re.compile(r">Type</p>\s*<p[^>]*>\s*([^<]+)"),
    "profit": re.compile(r">Monthly Profit</p>\s*<p[^>]*>\s*([^<]+)"),
    "revenue": re.compile(r">Monthly Revenue</p>\s*<p[^>]*>\s*([^<]+)"),
    "multiple": re.compile(r">Profit Multiple</p>\s*<p[^>]*>\s*([^<]+)"),
    "age": re.compile(r">Age</p>\s*<p[^>]*>\s*([^<]+)"),
}
MONEY_RE = re.compile(r"\$([0-9]+(?:\.[0-9]+)?)([KMB])?", re.IGNORECASE)
FILTER_MONEY_RE = re.compile(
    r"^(?:(under)\s+)?\$([0-9][0-9,]*(?:\.[0-9]+)?)([KMB])?$",
    re.IGNORECASE,
)
AGE_VALUE_RE = re.compile(
    r"^([0-9]+(?:\.[0-9]+)?)\s+(year|month)s?$",
    re.IGNORECASE,
)
AGE_RE = re.compile(r"([0-9]+(?:\.[0-9]+)?)\s*(year|month)", re.IGNORECASE)
MULTIPLE_RANGE_RE = re.compile(
    r"^([0-9]+(?:\.[0-9]+)?)x\s+to\s+([0-9]+(?:\.[0-9]+)?)x(?:\s+annual)?$",
    re.IGNORECASE,
)
MULTIPLE_ONE_RE = re.compile(
    r"^([0-9]+(?:\.[0-9]+)?)x(?:\s+annual)?$",
    re.IGNORECASE,
)
MULTIPLE_RE = re.compile(r"([0-9]+(?:\.[0-9]+)?)x", re.IGNORECASE)
FILTER_LINE_RE = re.compile(r"^(.*?)\s{2,}(\S.*?)\s*$")
BADGE_RE = re.compile(r'data-title="([^"]+)"')
COUNT_RE = re.compile(r"^[0-9][0-9,]*$")

MANUAL_CHECKS = """
Still check by hand before bidding:
- Read-only Google Analytics, Search Console, and payment processor access
- Traffic is not paid ads, bots, or one fragile keyword
- Wayback Machine history and a trademark check on the brand
- Pay through Flippa Escrow or Escrow.com
- Seller reviews, verified ID, and phone are not search filters
""".strip()


class FilterError(Exception):
    """filters.txt could not be used. The file is left unchanged."""


class Settings:
    def __init__(self, lines: list[tuple[str, str]], checklist: str) -> None:
        self.lines = lines
        self.checklist = checklist
        values = dict(lines)
        self.keyword = _optional_text(values["Keyword"])
        self.managed_by = _choice_list(values["Managed by"], MANAGED_BY, "Managed by")
        self.price_min, self.price_min_under = _money(values["Price minimum"], "Price minimum", allow_under=False)
        self.price_max, self.price_max_under = _money(values["Price maximum"], "Price maximum", allow_under=True)
        self.categories = _choice_list(values["Category type"], CATEGORIES, "Category type")
        self.country = _country(values["Country"])
        self.age_min = _age(values["Business age minimum"], "Business age minimum")
        self.age_max = _age(values["Business age maximum"], "Business age maximum")
        self.profit_min, _profit_min_under = _money(values["Monthly profit minimum"], "Monthly profit minimum", allow_under=False)
        self.profit_max, _profit_max_under = _money(values["Monthly profit maximum"], "Monthly profit maximum", allow_under=False)
        self.revenue_min, _ = _money(values["Monthly revenue minimum"], "Monthly revenue minimum", allow_under=False)
        self.revenue_max, _ = _money(values["Monthly revenue maximum"], "Monthly revenue maximum", allow_under=False)
        self.multiple_min, self.multiple_max = _multiple_bounds(values["Profit multiple"], "Profit multiple")
        self.revenue_multiple_min = _one_multiple(values["Revenue multiple minimum"], "Revenue multiple minimum")
        self.revenue_multiple_max = _one_multiple(values["Revenue multiple maximum"], "Revenue multiple maximum")
        self.industries = _choice_list(values["Industry"], INDUSTRIES, "Industry")
        self.users_min = _count(values["Monthly users minimum"], "Monthly users minimum")
        self.users_max = _count(values["Monthly users maximum"], "Monthly users maximum")
        self.pageviews_min = _count(values["Monthly pageviews minimum"], "Monthly pageviews minimum")
        self.pageviews_max = _count(values["Monthly pageviews maximum"], "Monthly pageviews maximum")
        self.downloads_min = _count(values["Monthly app downloads minimum"], "Monthly app downloads minimum")
        self.downloads_max = _count(values["Monthly app downloads maximum"], "Monthly app downloads maximum")
        self.sale_methods = _choice_list(values["Sale type"], SALE_TYPES, "Sale type")
        self.statuses = _choice_list(values["Status"], STATUSES, "Status")
        self.sort = _sort(values["Sort"])
        self.require_analytics = _required_flag(values["Google Analytics"], "Google Analytics")
        self.require_revenue = _required_flag(values["Verified revenue"], "Verified revenue")
        _check_bounds("Price", self.price_min, self.price_max)
        _check_bounds("Business age", self.age_min, self.age_max)
        _check_bounds("Monthly profit", self.profit_min, self.profit_max)
        _check_bounds("Monthly revenue", self.revenue_min, self.revenue_max)
        _check_bounds("Profit multiple", self.multiple_min, self.multiple_max)
        _check_bounds("Revenue multiple", self.revenue_multiple_min, self.revenue_multiple_max)
        _check_bounds("Monthly users", self.users_min, self.users_max)
        _check_bounds("Monthly pageviews", self.pageviews_min, self.pageviews_max)
        _check_bounds("Monthly app downloads", self.downloads_min, self.downloads_max)


def read_filters(path: Path) -> Settings:
    if not path.is_file():
        raise FilterError(f"missing {path}")
    text = path.read_text(encoding="utf-8")
    found: dict[str, str] = {}
    checklist_lines: list[str] = []
    for line_no, raw in enumerate(text.splitlines(), 1):
        if not raw.strip() or raw.strip().startswith("-") or raw.lower().lstrip().startswith("still check"):
            if raw.strip():
                checklist_lines.append(raw.strip())
            continue
        match = FILTER_LINE_RE.match(raw.rstrip())
        if not match:
            raise FilterError(f"line {line_no} is not 'Label  value'")
        label = match.group(1).strip()
        value = match.group(2).strip()
        if label not in LABELS:
            raise FilterError(f"line {line_no}: unknown filter {label!r}")
        if label in found:
            raise FilterError(f"line {line_no}: duplicate filter {label!r}")
        found[label] = value
    missing = [label for label in LABELS if label not in found]
    if missing:
        raise FilterError("missing " + ", ".join(missing))
    checklist = "\n".join(checklist_lines).strip() or MANUAL_CHECKS
    return Settings([(label, found[label]) for label in LABELS], checklist)


def _is_none(value: str) -> bool:
    return value.strip().lower() == NONE


def _optional_text(value: str) -> str | None:
    if _is_none(value):
        return None
    return value.strip()


def _split_choices(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def _choice_list(value: str, choices: dict[str, str], label: str) -> list[str]:
    if _is_none(value):
        return []
    codes: list[str] = []
    for part in _split_choices(value):
        code = choices.get(part.lower())
        if code is None:
            known = ", ".join(sorted({name.title() if name.islower() else name for name in choices}))
            raise FilterError(f"{label}: {part!r} is not one of {known}")
        if code not in codes:
            codes.append(code)
    if not codes:
        raise FilterError(f"{label}: {value!r} is empty")
    return codes


def _money(value: str, label: str, allow_under: bool) -> tuple[int | None, bool]:
    if _is_none(value):
        return None, False
    match = FILTER_MONEY_RE.match(value.strip())
    if not match:
        raise FilterError(f"{label}: {value!r} should look like $300 or under $100,000")
    under = bool(match.group(1))
    if under and not allow_under:
        raise FilterError(f"{label}: under is only for Price maximum")
    number = float(match.group(2).replace(",", ""))
    suffix = (match.group(3) or "").upper()
    scale = {"": 1, "K": 1_000, "M": 1_000_000, "B": 1_000_000_000}[suffix]
    amount = int(round(number * scale))
    if amount < 0 or (under and amount < 1):
        raise FilterError(f"{label}: {value!r} is too small")
    return amount, under


def _country(value: str) -> str | None:
    if _is_none(value):
        return None
    text = value.strip()
    if text.lower() in {"united states", "us"}:
        return "us"
    if re.fullmatch(r"[A-Za-z]{2}", text):
        return text.lower()
    raise FilterError(f"Country: {value!r} should be United States or a 2-letter Flippa code")


def _age(value: str, label: str) -> int | None:
    if _is_none(value):
        return None
    match = AGE_VALUE_RE.match(value.strip())
    if not match:
        raise FilterError(f"{label}: {value!r} should look like 12 months or 2 years")
    number = float(match.group(1))
    months = number * 12 if match.group(2).lower().startswith("year") else number
    if months < 0:
        raise FilterError(f"{label}: {value!r} is too small")
    return int(months)


def _multiple_bounds(value: str, label: str) -> tuple[float | None, float | None]:
    if _is_none(value):
        return None, None
    match = MULTIPLE_RANGE_RE.match(value.strip())
    if not match:
        raise FilterError(f"{label}: {value!r} should look like 2x to 3x annual")
    low = float(match.group(1))
    high = float(match.group(2))
    if low < 0 or high < low:
        raise FilterError(f"{label}: {value!r} is out of order")
    return low, high


def _one_multiple(value: str, label: str) -> float | None:
    if _is_none(value):
        return None
    match = MULTIPLE_ONE_RE.match(value.strip())
    if not match:
        raise FilterError(f"{label}: {value!r} should look like 2x")
    number = float(match.group(1))
    if number < 0:
        raise FilterError(f"{label}: {value!r} is too small")
    return number


def _count(value: str, label: str) -> int | None:
    if _is_none(value):
        return None
    if not COUNT_RE.match(value.strip()):
        raise FilterError(f"{label}: {value!r} should be a number")
    return int(value.strip().replace(",", ""))


def _sort(value: str) -> str | None:
    if _is_none(value):
        return None
    code = SORTS.get(value.strip().lower())
    if code is None:
        known = ", ".join(name.title() for name in SORTS)
        raise FilterError(f"Sort: {value!r} is not one of {known}")
    return code or None


def _required_flag(value: str, label: str) -> bool:
    text = value.strip().lower()
    if text == NONE:
        return False
    if text == REQUIRED:
        return True
    raise FilterError(f"{label}: {value!r} should be {REQUIRED!r} or none")


def _check_bounds(label: str, low: int | float | None, high: int | float | None) -> None:
    if low is not None and high is not None and low > high:
        raise FilterError(f"{label}: minimum is above maximum")


def format_filters(filters: list[tuple[str, str]]) -> str:
    width = max(len(label) for label, _value in filters)
    lines = [f"{label:<{width}}  {value}" for label, value in filters]
    return "\n".join(lines)


def _add(pairs: list[tuple[str, str]], key: str, value: int | float | str | None) -> None:
    if value is None:
        return
    pairs.append((key, str(value)))


def _multiple_query(value: float) -> str:
    """Flippa stores 2x as 20 and 3x as 30 in the search URL."""
    scaled = value * 10
    if float(scaled).is_integer():
        return str(int(scaled))
    return str(scaled)


def build_url(settings: Settings, page: int) -> str:
    # Flippa's price filter is inclusive, so a line that says under $100,000
    # is sent as 99999.
    pairs: list[tuple[str, str]] = []
    if settings.keyword:
        pairs.append(("query[keyword]", settings.keyword))
    for code in settings.managed_by:
        pairs.append(("filter[managed_by][]", code))
    _add(pairs, "filter[price][min]", settings.price_min)
    if settings.price_max is not None:
        sent = settings.price_max - 1 if settings.price_max_under else settings.price_max
        pairs.append(("filter[price][max]", str(sent)))
    for code in settings.categories:
        pairs.append(("filter[listing_category][]", code))
    if settings.country:
        pairs.append(("filter[seller_location][]", settings.country))
    _add(pairs, "filter[age][min]", settings.age_min)
    _add(pairs, "filter[age][max]", settings.age_max)
    _add(pairs, "filter[profit_per_month][min]", settings.profit_min)
    _add(pairs, "filter[profit_per_month][max]", settings.profit_max)
    _add(pairs, "filter[revenue_per_month][min]", settings.revenue_min)
    _add(pairs, "filter[revenue_per_month][max]", settings.revenue_max)
    if settings.multiple_min is not None:
        pairs.append(("filter[multiple][min]", _multiple_query(settings.multiple_min)))
    if settings.multiple_max is not None:
        pairs.append(("filter[multiple][max]", _multiple_query(settings.multiple_max)))
    if settings.revenue_multiple_min is not None:
        pairs.append(("filter[revenue_multiple][min]", _multiple_query(settings.revenue_multiple_min)))
    if settings.revenue_multiple_max is not None:
        pairs.append(("filter[revenue_multiple][max]", _multiple_query(settings.revenue_multiple_max)))
    for code in settings.industries:
        pairs.append(("filter[vertical][]", code))
    _add(pairs, "filter[uniques_per_month][min]", settings.users_min)
    _add(pairs, "filter[uniques_per_month][max]", settings.users_max)
    _add(pairs, "filter[page_views_per_month][min]", settings.pageviews_min)
    _add(pairs, "filter[page_views_per_month][max]", settings.pageviews_max)
    _add(pairs, "filter[downloads_per_month][min]", settings.downloads_min)
    _add(pairs, "filter[downloads_per_month][max]", settings.downloads_max)
    for code in settings.sale_methods:
        pairs.append(("filter[sale_method][]", code))
    for code in settings.statuses:
        pairs.append(("filter[status][]", code))
    if settings.sort:
        pairs.append(("sort_alias", settings.sort))
    pairs.append(("page_size", str(PAGE_SIZE)))
    pairs.append(("pagination", "true"))
    if page > 1:
        pairs.append(("page", str(page)))
    return SEARCH_URL + "?" + urllib.parse.urlencode(pairs)


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


def parse_money(text: str) -> int | None:
    match = MONEY_RE.search(text)
    if not match:
        return None
    number = float(match.group(1))
    suffix = (match.group(2) or "").upper()
    scale = {"": 1, "K": 1_000, "M": 1_000_000, "B": 1_000_000_000}[suffix]
    return int(number * scale)


def parse_age_months(text: str) -> int | None:
    match = AGE_RE.search(text)
    if not match:
        return None
    value = float(match.group(1))
    if match.group(2).lower().startswith("year"):
        return int(value * 12)
    return int(value)


def parse_multiple(text: str) -> float | None:
    match = MULTIPLE_RE.search(text)
    if not match:
        return None
    return float(match.group(1))


def metric_text(block: str, name: str) -> str:
    match = METRIC_RE[name].search(block)
    if not match:
        return ""
    return html.unescape(match.group(1)).strip()


def parse_listings(page_html: str) -> list[dict]:
    listings: list[dict] = []
    for block in LISTING_SPLIT.split(page_html)[1:]:
        listing_id = block.split('"', 1)[0]
        title_match = TITLE_RE.search(block)
        location_match = LOCATION_RE.search(block)
        if not title_match or not listing_id.isdigit():
            continue
        name = html.unescape(title_match.group(1)).strip()
        location = (
            html.unescape(location_match.group(1)).strip()
            if location_match
            else ""
        )
        badges = BADGE_RE.findall(block)
        sale_label = SALE_LABEL_RE.search(block)
        listings.append(
            {
                "listing_id": listing_id,
                "name": name,
                "price_usd": parse_price(block),
                "location": location,
                "type": metric_text(block, "type"),
                "monthly_profit_usd": parse_money(metric_text(block, "profit")),
                "monthly_revenue_usd": parse_money(metric_text(block, "revenue")),
                "profit_multiple": parse_multiple(metric_text(block, "multiple")),
                "age": metric_text(block, "age"),
                "age_months": parse_age_months(metric_text(block, "age")),
                "sale_type": html.unescape(sale_label.group(1)).strip() if sale_label else "",
                "verifications": ", ".join(badges),
                "analytics_verified": ANALYTICS_BADGE in badges,
                "revenue_verified": any(badge != ANALYTICS_BADGE for badge in badges),
                "url": f"https://flippa.com/{listing_id}",
            }
        )
    return listings


def total_results(page_html: str) -> int | None:
    match = TOTAL_RE.search(page_html)
    if not match:
        return None
    return int(match.group(1).replace(",", ""))


def _below(amount: int | None, limit: int | float | None) -> bool:
    return limit is not None and (amount is None or amount < limit)


def _above(amount: int | float | None, limit: int | float | None) -> bool:
    return limit is not None and (amount is None or amount > limit)


def keep_listing(item: dict, settings: Settings) -> bool:
    price = item["price_usd"]
    if settings.price_min is not None and (price is None or price < settings.price_min):
        return False
    if settings.price_max is not None:
        if price is None:
            return False
        if settings.price_max_under and price >= settings.price_max:
            return False
        if not settings.price_max_under and price > settings.price_max:
            return False
    if settings.country == "us" and "United States" not in item["location"]:
        return False
    if _below(item["monthly_profit_usd"], settings.profit_min):
        return False
    if _above(item["monthly_profit_usd"], settings.profit_max):
        return False
    if _below(item["monthly_revenue_usd"], settings.revenue_min):
        return False
    if _above(item["monthly_revenue_usd"], settings.revenue_max):
        return False
    if _below(item["age_months"], settings.age_min):
        return False
    if _above(item["age_months"], settings.age_max):
        return False
    if _below(item["profit_multiple"], settings.multiple_min):
        return False
    if _above(item["profit_multiple"], settings.multiple_max):
        return False
    sale = item["sale_type"].lower()
    if settings.sale_methods == ["classified"] and sale == "auction":
        return False
    if settings.sale_methods == ["auction"] and sale != "auction":
        return False
    if settings.require_analytics and not item["analytics_verified"]:
        return False
    if settings.require_revenue and not item["revenue_verified"]:
        return False
    return True


def excluded_listing_ids(output_dir: Path) -> set[str]:
    """Listing numbers in deleted.json, saved.json, or first_access.json."""
    found: set[str] = set()
    deleted_path = output_dir / "deleted.json"
    if deleted_path.is_file():
        raw = deleted_path.read_text(encoding="utf-8").strip()
        data = json.loads(raw) if raw else []
        for item in data:
            if isinstance(item, dict):
                item = item.get("listing_id", "")
            number = str(item).strip()
            if number:
                found.add(number)
    saved_path = output_dir / "saved.json"
    if saved_path.is_file():
        raw = saved_path.read_text(encoding="utf-8").strip()
        data = json.loads(raw) if raw else []
        for item in data:
            if isinstance(item, dict):
                number = str(item.get("listing_id", "")).strip()
                if number:
                    found.add(number)
    first_access_path = output_dir / "first_access.json"
    if first_access_path.is_file():
        raw = first_access_path.read_text(encoding="utf-8").strip()
        data = json.loads(raw) if raw else []
        for item in data:
            if isinstance(item, dict):
                number = str(item.get("listing_id", "")).strip()
                if number:
                    found.add(number)
    return found


def scrape(settings: Settings, delay: float, timeout: float, excluded: set[str] | None = None) -> list[dict]:
    print(format_filters(settings.lines), file=sys.stderr)
    print(file=sys.stderr)
    first_url = build_url(settings, 1)
    print(f"Fetching {first_url}", file=sys.stderr)
    first_html = fetch(first_url, timeout)
    reported = total_results(first_html)
    if reported is None:
        raise RuntimeError("Could not read the result count from the search page.")
    pages = max(1, math.ceil(reported / PAGE_SIZE))
    print(f"Flippa reports {reported} listings across {pages} pages.", file=sys.stderr)
    skipped = excluded or set()
    if skipped:
        print(
            f"Skipping {len(skipped)} listing numbers already deleted, saved, or in first access.",
            file=sys.stderr,
        )

    found: dict[str, dict] = {}
    for page in range(1, pages + 1):
        page_html = first_html if page == 1 else fetch(build_url(settings, page), timeout)
        batch = parse_listings(page_html)
        kept = 0
        for item in batch:
            if item["listing_id"] in skipped:
                continue
            if not keep_listing(item, settings):
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


def write_outputs(listings: list[dict], output_dir: Path, settings: Settings) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "businesses.csv"
    json_path = output_dir / "businesses.json"
    names_path = output_dir / "names.txt"
    filters_path = output_dir / "filters.txt"
    filters_path.write_text(
        format_filters(settings.lines) + "\n\n" + settings.checklist + "\n",
        encoding="utf-8",
    )

    fieldnames = PUBLIC_FIELDS
    rows = [{key: item.get(key, "") for key in fieldnames} for item in listings]
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    json_path.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    names_path.write_text(
        "\n".join(item["name"] for item in listings) + ("\n" if listings else ""),
        encoding="utf-8",
    )
    print(f"Wrote {len(listings)} listings to {csv_path}", file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Save Flippa listings that match output/filters.txt."
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
        help="Directory for filters.txt, businesses.csv, businesses.json, and names.txt.",
    )
    args = parser.parse_args()
    if args.delay < 0:
        parser.error("--delay must be 0 or more")
    if args.timeout <= 0:
        parser.error("--timeout must be greater than 0")

    try:
        settings = read_filters(args.output / "filters.txt")
    except FilterError as error:
        print(f"filters.txt: {error}", file=sys.stderr)
        sys.exit(1)

    listings = scrape(settings, args.delay, args.timeout, excluded_listing_ids(args.output))
    write_outputs(listings, args.output, settings)


if __name__ == "__main__":
    main()
