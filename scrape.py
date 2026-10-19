"""Collect public Flippa listings using the filters in output/filters.txt.

Uses Flippa's public search pages (the same pages a browser loads). Search is
allowed by robots.txt. Requests are paced so the crawl stays light.

Edit the value column in filters.txt, then run this script. A value of none
leaves that filter off. Pass --url with a Flippa search link to replace the
filter values from that link. serve.py edits this same file from a local page.

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


class FilterError(Exception):
    """filters.txt could not be used. The file is left unchanged."""


class Settings:
    def __init__(self, lines: list[tuple[str, str]]) -> None:
        self.lines = lines
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


def _is_retired_note(raw: str) -> bool:
    """Blank lines, the old seller note, and the old bidding checklist."""
    stripped = raw.strip()
    if not stripped:
        return True
    lowered = stripped.lower()
    return (
        lowered.startswith("-")
        or lowered.startswith("still check")
        or lowered.startswith("seller id / phone")
    )


def read_filters(path: Path) -> Settings:
    if not path.is_file():
        raise FilterError(f"missing {path}")
    text = path.read_text(encoding="utf-8")
    found: dict[str, str] = {}
    for line_no, raw in enumerate(text.splitlines(), 1):
        if _is_retired_note(raw):
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
    return Settings([(label, found[label]) for label in LABELS])


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
    text = value.strip()
    match = MULTIPLE_RANGE_RE.match(text)
    if match:
        low = float(match.group(1))
        high = float(match.group(2))
        if low < 0 or high < low:
            raise FilterError(f"{label}: {value!r} is out of order")
        return low, high
    minimum = MULTIPLE_ONE_RE.match(text)
    if minimum:
        number = float(minimum.group(1))
        if number < 0:
            raise FilterError(f"{label}: {value!r} is too small")
        return number, None
    maximum = re.fullmatch(r"to\s+([0-9]+(?:\.[0-9]+)?)x(?:\s+annual)?", text, re.IGNORECASE)
    if maximum:
        number = float(maximum.group(1))
        if number < 0:
            raise FilterError(f"{label}: {value!r} is too small")
        return None, number
    raise FilterError(f"{label}: {value!r} should look like 2x to 3x annual")


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


IGNORED_QUERY_KEYS = {"page", "page_size", "pagination", "preview", "initial"}


def _phrase(name: str) -> str:
    words = []
    for index, word in enumerate(name.split()):
        words.append(word if index and word == "and" else word.capitalize())
    return " ".join(words)


def _managed_label(code: str) -> str:
    labels = {
        "flippa_broker": "Brokered by Flippa",
        "owner": "Listed by Owner",
        "partner_broker": "Listed by Partner Broker",
    }
    if code not in labels:
        raise FilterError(f"filter[managed_by][]: unknown value {code!r}")
    return labels[code]


def _category_label(code: str) -> str:
    labels = {value: _phrase(name) for name, value in CATEGORIES.items()}
    if code not in labels:
        raise FilterError(f"filter[listing_category][]: unknown value {code!r}")
    return labels[code]


def filters_from_search_url(url: str) -> dict[str, str]:
    """Turn a Flippa search URL into filters.txt values. Missing filters are none."""
    parsed = urllib.parse.urlparse(url.strip())
    host = parsed.netloc.lower().removeprefix("www.")
    if host != "flippa.com" or parsed.path.rstrip("/") != "/search":
        raise FilterError("URL must be a https://flippa.com/search link")
    query = urllib.parse.parse_qs(parsed.query, keep_blank_values=False)
    values = {label: NONE for label in LABELS}

    def one(key: str) -> str | None:
        items = query.get(key, [])
        if not items:
            return None
        if len(items) > 1:
            raise FilterError(f"{key} appears more than once")
        return items[0]

    def many(key: str) -> list[str]:
        return query.get(key, [])

    keyword = one("query[keyword]")
    if keyword:
        values["Keyword"] = keyword
    managed = many("filter[managed_by][]")
    if managed:
        values["Managed by"] = ", ".join(_managed_label(code) for code in managed)
    price_min = one("filter[price][min]")
    if price_min is not None:
        values["Price minimum"] = _dollar_text(_whole_number(price_min, "filter[price][min]"))
    price_max = one("filter[price][max]")
    if price_max is not None:
        values["Price maximum"] = _dollar_text(_whole_number(price_max, "filter[price][max]"))
    categories = many("filter[listing_category][]")
    if categories:
        values["Category type"] = ", ".join(_category_label(code) for code in categories)
    country = many("filter[seller_location][]")
    if len(country) > 1:
        raise FilterError("filter[seller_location][] appears more than once")
    if country:
        code = country[0].strip().lower()
        if not re.fullmatch(r"[a-z]{2}", code):
            raise FilterError(f"filter[seller_location][]: {country[0]!r} is not a 2-letter code")
        values["Country"] = "United States" if code == "us" else code
    age_min = one("filter[age][min]")
    if age_min is not None:
        values["Business age minimum"] = _age_text(_whole_number(age_min, "filter[age][min]"))
    age_max = one("filter[age][max]")
    if age_max is not None:
        values["Business age maximum"] = _age_text(_whole_number(age_max, "filter[age][max]"))
    _money_param(values, "Monthly profit minimum", one("filter[profit_per_month][min]"), "filter[profit_per_month][min]")
    _money_param(values, "Monthly profit maximum", one("filter[profit_per_month][max]"), "filter[profit_per_month][max]")
    _money_param(values, "Monthly revenue minimum", one("filter[revenue_per_month][min]"), "filter[revenue_per_month][min]")
    _money_param(values, "Monthly revenue maximum", one("filter[revenue_per_month][max]"), "filter[revenue_per_month][max]")
    values["Profit multiple"] = _multiple_text(
        one("filter[multiple][min]"),
        one("filter[multiple][max]"),
    )
    revenue_low = one("filter[revenue_multiple][min]")
    revenue_high = one("filter[revenue_multiple][max]")
    if revenue_low is not None:
        values["Revenue multiple minimum"] = _one_multiple_text(revenue_low, "filter[revenue_multiple][min]")
    if revenue_high is not None:
        values["Revenue multiple maximum"] = _one_multiple_text(revenue_high, "filter[revenue_multiple][max]")
    industries = many("filter[vertical][]")
    if industries:
        values["Industry"] = ", ".join(_industry_label(code) for code in industries)
    _count_param(values, "Monthly users minimum", one("filter[uniques_per_month][min]"), "filter[uniques_per_month][min]")
    _count_param(values, "Monthly users maximum", one("filter[uniques_per_month][max]"), "filter[uniques_per_month][max]")
    _count_param(values, "Monthly pageviews minimum", one("filter[page_views_per_month][min]"), "filter[page_views_per_month][min]")
    _count_param(values, "Monthly pageviews maximum", one("filter[page_views_per_month][max]"), "filter[page_views_per_month][max]")
    _count_param(values, "Monthly app downloads minimum", one("filter[downloads_per_month][min]"), "filter[downloads_per_month][min]")
    _count_param(values, "Monthly app downloads maximum", one("filter[downloads_per_month][max]"), "filter[downloads_per_month][max]")
    sales = many("filter[sale_method][]")
    if sales:
        values["Sale type"] = ", ".join(_choice_label(code, SALE_TYPES, "filter[sale_method][]") for code in sales)
    statuses = many("filter[status][]")
    if statuses:
        labels = {"open": "Open", "won": "Recently Sold"}
        try:
            values["Status"] = ", ".join(labels[code] for code in statuses)
        except KeyError as error:
            raise FilterError(f"filter[status][]: unknown value {error.args[0]!r}") from error
    sort = one("sort_alias")
    if sort:
        label = {code: _phrase(name) for name, code in SORTS.items() if code}.get(sort)
        if label is None:
            raise FilterError(f"sort_alias: unknown value {sort!r}")
        values["Sort"] = label

    known = set(IGNORED_QUERY_KEYS)
    known.update(
        [
            "query[keyword]",
            "filter[managed_by][]",
            "filter[price][min]",
            "filter[price][max]",
            "filter[listing_category][]",
            "filter[seller_location][]",
            "filter[age][min]",
            "filter[age][max]",
            "filter[profit_per_month][min]",
            "filter[profit_per_month][max]",
            "filter[revenue_per_month][min]",
            "filter[revenue_per_month][max]",
            "filter[multiple][min]",
            "filter[multiple][max]",
            "filter[revenue_multiple][min]",
            "filter[revenue_multiple][max]",
            "filter[vertical][]",
            "filter[uniques_per_month][min]",
            "filter[uniques_per_month][max]",
            "filter[page_views_per_month][min]",
            "filter[page_views_per_month][max]",
            "filter[downloads_per_month][min]",
            "filter[downloads_per_month][max]",
            "filter[sale_method][]",
            "filter[status][]",
            "sort_alias",
        ]
    )
    unknown = sorted(set(query) - known)
    if unknown:
        raise FilterError("unsupported search parameter " + unknown[0])
    return values


def _whole_number(raw: str, key: str) -> int:
    if not re.fullmatch(r"[0-9]+", raw):
        raise FilterError(f"{key}: {raw!r} is not a whole number")
    return int(raw)


def _dollar_text(amount: int) -> str:
    return f"${amount:,}"


def _age_text(months: int) -> str:
    if months % 12 == 0 and months >= 12:
        years = months // 12
        unit = "year" if years == 1 else "years"
        return f"{years} {unit}"
    unit = "month" if months == 1 else "months"
    return f"{months} {unit}"


def _money_param(values: dict[str, str], label: str, raw: str | None, key: str) -> None:
    if raw is not None:
        values[label] = _dollar_text(_whole_number(raw, key))


def _count_param(values: dict[str, str], label: str, raw: str | None, key: str) -> None:
    if raw is not None:
        values[label] = f"{_whole_number(raw, key):,}"


def _multiple_display(raw: str, key: str) -> str:
    try:
        number = float(raw) / 10
    except ValueError as error:
        raise FilterError(f"{key}: {raw!r} is not a number") from error
    if number < 0:
        raise FilterError(f"{key}: {raw!r} is too small")
    if float(number).is_integer():
        return f"{int(number)}x"
    return f"{number}x"


def _multiple_text(low: str | None, high: str | None) -> str:
    if low is None and high is None:
        return NONE
    low_text = _multiple_display(low, "filter[multiple][min]") if low is not None else None
    high_text = _multiple_display(high, "filter[multiple][max]") if high is not None else None
    if low_text and high_text:
        return f"{low_text} to {high_text} annual"
    if low_text:
        return low_text
    return f"to {high_text}"


def _one_multiple_text(raw: str, key: str) -> str:
    return _multiple_display(raw, key)


def _industry_label(code: str) -> str:
    labels = {value: _phrase(name) for name, value in INDUSTRIES.items()}
    if code not in labels:
        raise FilterError(f"filter[vertical][]: unknown value {code!r}")
    return labels[code]


def _choice_label(code: str, choices: dict[str, str], key: str) -> str:
    labels = {value: _phrase(name) for name, value in choices.items()}
    if code not in labels:
        raise FilterError(f"{key}: unknown value {code!r}")
    return labels[code]


def apply_search_url(path: Path, url: str) -> Settings:
    """Replace filter values from a Flippa search URL."""
    values = filters_from_search_url(url)
    settings = Settings([(label, values[label]) for label in LABELS])
    write_filters_file(path, settings)
    return settings


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


DEFAULT_DELAY = 1.5
DEFAULT_TIMEOUT = 60


def write_filters_file(path: Path, settings: Settings) -> None:
    """Write filters.txt."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(format_filters(settings.lines) + "\n", encoding="utf-8")


def _empty(value) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _json_number(value: int | float | None) -> int | float | None:
    if value is None:
        return None
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def _months_to_form(months: int | None) -> dict | None:
    if months is None:
        return None
    if months % 12 == 0 and months >= 12:
        years = months // 12
        return {"amount": years, "unit": "years"}
    return {"amount": months, "unit": "months"}


def _sale_type_label(code: str) -> str:
    return _choice_label(code, SALE_TYPES, "Sale type")


def _status_label(code: str) -> str:
    return _choice_label(code, STATUSES, "Status")


def filter_options() -> dict:
    """Choices for the local filter page."""
    return {
        "managed_by": [{"code": code, "label": _managed_label(code)} for code in MANAGED_BY.values()],
        "categories": [{"code": code, "label": _category_label(code)} for code in CATEGORIES.values()],
        "industries": [{"code": code, "label": _industry_label(code)} for code in INDUSTRIES.values()],
        "sale_types": [{"code": code, "label": _sale_type_label(code)} for code in SALE_TYPES.values()],
        "statuses": [{"code": code, "label": _status_label(code)} for code in STATUSES.values()],
        "sorts": [{"value": NONE, "label": "None"}]
        + [{"value": _phrase(name), "label": _phrase(name)} for name in SORTS],
        "check_off": NONE,
        "check_on": REQUIRED,
    }


def filter_form(settings: Settings) -> dict:
    """Current filters as values the local page can show."""
    values = dict(settings.lines)
    return {
        "keyword": settings.keyword or "",
        "managed_by": list(settings.managed_by),
        "price_min": settings.price_min,
        "price_max": settings.price_max,
        "price_max_under": settings.price_max_under,
        "categories": list(settings.categories),
        "country": "" if settings.country is None else values["Country"],
        "age_min": _months_to_form(settings.age_min),
        "age_max": _months_to_form(settings.age_max),
        "profit_min": settings.profit_min,
        "profit_max": settings.profit_max,
        "revenue_min": settings.revenue_min,
        "revenue_max": settings.revenue_max,
        "multiple_min": _json_number(settings.multiple_min),
        "multiple_max": _json_number(settings.multiple_max),
        "revenue_multiple_min": _json_number(settings.revenue_multiple_min),
        "revenue_multiple_max": _json_number(settings.revenue_multiple_max),
        "industries": list(settings.industries),
        "users_min": settings.users_min,
        "users_max": settings.users_max,
        "pageviews_min": settings.pageviews_min,
        "pageviews_max": settings.pageviews_max,
        "downloads_min": settings.downloads_min,
        "downloads_max": settings.downloads_max,
        "sale_methods": list(settings.sale_methods),
        "statuses": list(settings.statuses),
        "sort": values["Sort"],
        "require_analytics": settings.require_analytics,
        "require_revenue": settings.require_revenue,
        "search_url": build_url(settings, 1),
    }


def _whole_amount(value, label: str) -> int:
    if isinstance(value, bool):
        raise FilterError(f"{label}: {value!r} should look like $300")
    if isinstance(value, str):
        text = value.strip().replace(",", "").replace("$", "").strip()
        if not re.fullmatch(r"[0-9]+", text):
            raise FilterError(f"{label}: {value!r} should look like $300")
        return int(text)
    if isinstance(value, float):
        if not value.is_integer():
            raise FilterError(f"{label}: {value!r} should look like $300")
        value = int(value)
    if isinstance(value, int):
        if value < 0:
            raise FilterError(f"{label}: {value!r} is too small")
        return value
    raise FilterError(f"{label}: {value!r} should look like $300")


def _amount_text(value, label: str, under: bool = False) -> str:
    if _empty(value):
        return NONE
    if under and label != "Price maximum":
        raise FilterError(f"{label}: under is only for Price maximum")
    amount = _whole_amount(value, label)
    text = f"{'under ' if under else ''}{_dollar_text(amount)}"
    _money(text, label, allow_under=(label == "Price maximum"))
    return text


def _count_text(value, label: str) -> str:
    if _empty(value):
        return NONE
    if isinstance(value, str):
        text = value.strip()
    elif isinstance(value, bool):
        raise FilterError(f"{label}: {value!r} should be a number")
    elif isinstance(value, float) and value.is_integer():
        text = f"{int(value):,}"
    elif isinstance(value, int):
        text = f"{value:,}"
    else:
        raise FilterError(f"{label}: {value!r} should be a number")
    number = _count(text, label)
    if number is None:
        return NONE
    return f"{number:,}"


def _optional_multiple(value, label: str) -> float | None:
    if _empty(value):
        return None
    if isinstance(value, bool):
        raise FilterError(f"{label}: {value!r} should look like 2x")
    if isinstance(value, str):
        text = value.strip().lower().rstrip("x").strip()
        try:
            number = float(text)
        except ValueError as error:
            raise FilterError(f"{label}: {value!r} should look like 2x") from error
    elif isinstance(value, (int, float)):
        number = float(value)
    else:
        raise FilterError(f"{label}: {value!r} should look like 2x")
    if number < 0:
        raise FilterError(f"{label}: {value!r} is too small")
    return number


def _scaled_multiple(number: float) -> str:
    scaled = number * 10
    if float(scaled).is_integer():
        return str(int(scaled))
    return str(scaled)


def _profit_multiple_text(low, high) -> str:
    low_number = _optional_multiple(low, "Profit multiple")
    high_number = _optional_multiple(high, "Profit multiple")
    low_raw = None if low_number is None else _scaled_multiple(low_number)
    high_raw = None if high_number is None else _scaled_multiple(high_number)
    return _multiple_text(low_raw, high_raw)


def _single_multiple_text(value, label: str) -> str:
    number = _optional_multiple(value, label)
    if number is None:
        return NONE
    return _one_multiple_text(_scaled_multiple(number), label)


def _age_form_text(value, label: str) -> str:
    if _empty(value):
        return NONE
    if not isinstance(value, dict):
        raise FilterError(f"{label}: {value!r} should look like 12 months or 2 years")
    amount = value.get("amount")
    unit = str(value.get("unit", "")).strip().lower()
    if _empty(amount):
        return NONE
    if unit in {"year", "years"}:
        unit_word = "years"
    elif unit in {"month", "months"}:
        unit_word = "months"
    else:
        raise FilterError(f"{label}: unit should be years or months")
    months = _age(f"{amount} {unit_word}", label)
    if months is None:
        return NONE
    return _age_text(months)


def _keyword_text(value) -> str:
    if _empty(value):
        return NONE
    if not isinstance(value, str):
        raise FilterError("Keyword: expected text")
    text = value.strip()
    if _is_none(text):
        return NONE
    return text


def _country_text(value) -> str:
    if _empty(value):
        return NONE
    if not isinstance(value, str):
        raise FilterError("Country: expected text")
    text = value.strip()
    if _is_none(text):
        return NONE
    _country(text)
    if text.lower() in {"united states", "us"}:
        return "United States"
    return text.lower()


def _sort_text(value) -> str:
    if _empty(value):
        return NONE
    if not isinstance(value, str):
        raise FilterError("Sort: expected text")
    text = value.strip()
    if _is_none(text):
        return NONE
    _sort(text)
    for name in SORTS:
        if name == text.lower():
            return _phrase(name)
    return text


def _flag_text(value, label: str) -> str:
    if value is True:
        return REQUIRED
    if value is False or _empty(value):
        return NONE
    if isinstance(value, str):
        text = value.strip().lower()
        if text == NONE:
            return NONE
        if text == REQUIRED:
            return REQUIRED
    raise FilterError(f"{label}: {value!r} should be {REQUIRED!r} or none")


def _choice_text(value, labeler, label: str) -> str:
    if value is None or value == [] or (isinstance(value, str) and (_empty(value) or _is_none(value))):
        return NONE
    if isinstance(value, str):
        codes = _split_choices(value)
    elif isinstance(value, list):
        codes = value
    else:
        raise FilterError(f"{label}: expected a list")
    labels: list[str] = []
    for item in codes:
        if not isinstance(item, str) or not item.strip():
            raise FilterError(f"{label}: {item!r} is not a choice")
        labels.append(labeler(item.strip()))
    if not labels:
        raise FilterError(f"{label}: {value!r} is empty")
    return ", ".join(labels)


def settings_from_form(form: dict) -> Settings:
    """Build settings from the local page."""
    if not isinstance(form, dict):
        raise FilterError("filters should be an object")
    lines = [
        ("Keyword", _keyword_text(form.get("keyword"))),
        ("Managed by", _choice_text(form.get("managed_by"), _managed_label, "Managed by")),
        ("Price minimum", _amount_text(form.get("price_min"), "Price minimum")),
        (
            "Price maximum",
            _amount_text(form.get("price_max"), "Price maximum", under=form.get("price_max_under") is True),
        ),
        ("Category type", _choice_text(form.get("categories"), _category_label, "Category type")),
        ("Country", _country_text(form.get("country"))),
        ("Business age minimum", _age_form_text(form.get("age_min"), "Business age minimum")),
        ("Business age maximum", _age_form_text(form.get("age_max"), "Business age maximum")),
        ("Monthly profit minimum", _amount_text(form.get("profit_min"), "Monthly profit minimum")),
        ("Monthly profit maximum", _amount_text(form.get("profit_max"), "Monthly profit maximum")),
        ("Monthly revenue minimum", _amount_text(form.get("revenue_min"), "Monthly revenue minimum")),
        ("Monthly revenue maximum", _amount_text(form.get("revenue_max"), "Monthly revenue maximum")),
        ("Profit multiple", _profit_multiple_text(form.get("multiple_min"), form.get("multiple_max"))),
        (
            "Revenue multiple minimum",
            _single_multiple_text(form.get("revenue_multiple_min"), "Revenue multiple minimum"),
        ),
        (
            "Revenue multiple maximum",
            _single_multiple_text(form.get("revenue_multiple_max"), "Revenue multiple maximum"),
        ),
        ("Industry", _choice_text(form.get("industries"), _industry_label, "Industry")),
        ("Monthly users minimum", _count_text(form.get("users_min"), "Monthly users minimum")),
        ("Monthly users maximum", _count_text(form.get("users_max"), "Monthly users maximum")),
        ("Monthly pageviews minimum", _count_text(form.get("pageviews_min"), "Monthly pageviews minimum")),
        ("Monthly pageviews maximum", _count_text(form.get("pageviews_max"), "Monthly pageviews maximum")),
        (
            "Monthly app downloads minimum",
            _count_text(form.get("downloads_min"), "Monthly app downloads minimum"),
        ),
        (
            "Monthly app downloads maximum",
            _count_text(form.get("downloads_max"), "Monthly app downloads maximum"),
        ),
        ("Sale type", _choice_text(form.get("sale_methods"), _sale_type_label, "Sale type")),
        ("Status", _choice_text(form.get("statuses"), _status_label, "Status")),
        ("Sort", _sort_text(form.get("sort"))),
        ("Google Analytics", _flag_text(form.get("require_analytics"), "Google Analytics")),
        ("Verified revenue", _flag_text(form.get("require_revenue"), "Verified revenue")),
    ]
    return Settings(lines)


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
    """Listing numbers in deleted, saved, first access, signed NDA, or waiting inquiry."""
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
    nda_path = output_dir / "nda.json"
    if nda_path.is_file():
        raw = nda_path.read_text(encoding="utf-8").strip()
        data = json.loads(raw) if raw else []
        for item in data:
            if isinstance(item, dict):
                number = str(item.get("listing_id", "")).strip()
                if number:
                    found.add(number)
    waiting_path = output_dir / "waiting_inquiry.json"
    if waiting_path.is_file():
        raw = waiting_path.read_text(encoding="utf-8").strip()
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
            f"Skipping {len(skipped)} listing numbers already in Deleted, Top Choices, First access, Signed NDA, or Waiting inquiry.",
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
    write_filters_file(output_dir / "filters.txt", settings)

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
        default=DEFAULT_DELAY,
        help=f"Seconds to wait between pages (default: {DEFAULT_DELAY}).",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT,
        help=f"HTTP timeout in seconds (default: {DEFAULT_TIMEOUT}).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("output"),
        help="Directory for filters.txt, businesses.csv, businesses.json, and names.txt.",
    )
    parser.add_argument(
        "--url",
        help="Flippa search URL. Replaces the values in filters.txt, then runs the scrape.",
    )
    args = parser.parse_args()
    if args.delay < 0:
        parser.error("--delay must be 0 or more")
    if args.timeout <= 0:
        parser.error("--timeout must be greater than 0")

    filters_path = args.output / "filters.txt"
    try:
        if args.url:
            settings = apply_search_url(filters_path, args.url)
        else:
            settings = read_filters(filters_path)
    except FilterError as error:
        print(f"filters.txt: {error}", file=sys.stderr)
        sys.exit(1)

    listings = scrape(settings, args.delay, args.timeout, excluded_listing_ids(args.output))
    write_outputs(listings, args.output, settings)


if __name__ == "__main__":
    main()
