"""Score a listing with the E-commerce Scorecard workbook.

The workbook is the metric source. Bands and input labels are read from it.
The calculations follow the Scorecard and Financing sheets, so the same inputs
always get the same points.
"""

from __future__ import annotations

import re
import zipfile
import xml.etree.ElementTree as ET
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

SCORECARD_PATH = Path(r"c:\Users\kevin\OneDrive\Desktop\Important\Life\Job\E-commerce Scorecard.xlsx")
MARKER = "SCORECARD INPUTS"
NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
MAIN = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"

DOWN_DEFAULT = Decimal("30000")
RATE_DEFAULT = Decimal("0.11")
TERM1_DEFAULT = Decimal("10")
TERM2_DEFAULT = Decimal("7")

PERCENT_KEYS = {"ConvRate", "RepeatRate", "Rate"}
YESNO_KEYS = {"HasInventory", "CustCoverage", "Owner_1", "Owner_2", "Owner_3", "Owner_4", "Owner_5"}
CHANNEL_KEYS = {"LargestChannel"}
TEXT_KEYS = {"BizName"}
BLANK_WORDS = {"", "blank", "missing", "unknown", "n/a", "na", "none", "-", "—"}


def excel_round(value: Decimal, places: int) -> Decimal:
    quant = Decimal("1").scaleb(-places)
    return value.quantize(quant, rounding=ROUND_HALF_UP)


def _column_index(letters: str) -> int:
    index = 0
    for char in letters:
        index = index * 26 + (ord(char.upper()) - 64)
    return index


def _split_ref(ref: str) -> tuple[str, str, str]:
    sheet, cells = ref.split("!", 1)
    sheet = sheet.strip().strip("'")
    start, _, end = cells.replace("$", "").partition(":")
    return sheet, start, end or start


def _cell_parts(ref: str) -> tuple[str, int]:
    match = re.match(r"([A-Z]+)(\d+)", ref.upper())
    if not match:
        raise ValueError(f"Bad cell {ref}")
    return match.group(1), int(match.group(2))


def _load_sheets(path: Path) -> tuple[dict[str, dict[str, Decimal | str]], dict[str, str]]:
    with zipfile.ZipFile(path) as book:
        workbook = ET.fromstring(book.read("xl/workbook.xml"))
        rels = ET.fromstring(book.read("xl/_rels/workbook.xml.rels"))
        relmap = {rel.attrib["Id"]: rel.attrib["Target"] for rel in rels}
        strings: list[str] = []
        if "xl/sharedStrings.xml" in book.namelist():
            shared = ET.fromstring(book.read("xl/sharedStrings.xml"))
            for item in shared.findall("m:si", NS):
                strings.append("".join(node.text or "" for node in item.iter(MAIN + "t")))
        sheets: dict[str, dict[str, Decimal | str]] = {}
        for sheet in workbook.find("m:sheets", NS):
            name = sheet.attrib["name"]
            target = relmap[sheet.attrib["{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"]]
            if not target.startswith("xl/"):
                target = "xl/" + target.lstrip("/")
            root = ET.fromstring(book.read(target))
            cells: dict[str, Decimal | str] = {}
            for cell in root.iter(MAIN + "c"):
                ref = cell.attrib.get("r", "")
                kind = cell.attrib.get("t")
                value = cell.find("m:v", NS)
                inline = cell.find("m:is", NS)
                if kind == "s" and value is not None and value.text:
                    cells[ref] = strings[int(value.text)]
                elif kind == "inlineStr" and inline is not None:
                    cells[ref] = "".join(node.text or "" for node in inline.iter(MAIN + "t"))
                elif kind == "str" and value is not None and value.text is not None:
                    cells[ref] = value.text
                elif value is not None and value.text:
                    cells[ref] = Decimal(value.text)
                elif ref:
                    cells[ref] = ""
            sheets[name] = cells
        names: dict[str, str] = {}
        defined = workbook.find("m:definedNames", NS)
        if defined is not None:
            for item in defined:
                if item.text and item.attrib.get("name"):
                    names[item.attrib["name"]] = item.text
    return sheets, names


def _range_values(sheets: dict[str, dict[str, Decimal | str]], ref: str) -> list[Decimal | str]:
    sheet, start, end = _split_ref(ref)
    start_col, start_row = _cell_parts(start)
    end_col, end_row = _cell_parts(end)
    cells = sheets[sheet]
    values: list[Decimal | str] = []
    for row in range(start_row, end_row + 1):
        for index in range(_column_index(start_col), _column_index(end_col) + 1):
            letters = ""
            number = index
            while number:
                number, remainder = divmod(number - 1, 26)
                letters = chr(65 + remainder) + letters
            values.append(cells.get(f"{letters}{row}", ""))
    return values


def _bands(sheets, names: dict[str, str], levels: str, points: str, labels: str) -> list[tuple[Decimal, Decimal | str, str]]:
    rows = []
    for level, point, label in zip(_range_values(sheets, names[levels]), _range_values(sheets, names[points]), _range_values(sheets, names[labels])):
        if not isinstance(level, Decimal) or not isinstance(point, (Decimal, str)):
            continue
        rows.append((level, point, str(label)))
    rows.sort(key=lambda item: item[0])
    return rows


def _lookup(value: Decimal, rows: list[tuple[Decimal, Decimal | str, str]]) -> tuple[Decimal | str, str]:
    found: tuple[Decimal | str, str] | None = None
    for level, point, label in rows:
        if value >= level:
            found = (point, label)
        else:
            break
    if found is None:
        raise ValueError("A scorecard band did not cover that value.")
    return found


def _point(value: Decimal | str) -> int:
    if isinstance(value, Decimal):
        return int(value)
    return int(Decimal(value))


class Scorecard:
    def __init__(self, path: Path = SCORECARD_PATH):
        self.path = path
        sheets, names = _load_sheets(path)
        self.sheets = sheets
        self.names = names
        self.band = {
            "sde": _bands(sheets, names, "SDE_L", "SDE_P", "SDE_B"),
            "gm": _bands(sheets, names, "GM_L", "GM_P", "GM_B"),
            "net": _bands(sheets, names, "NET_L", "NET_P", "NET_B"),
            "yoy": _bands(sheets, names, "YOY_L", "YOY_P", "YOY_B"),
            "cv": _bands(sheets, names, "CV_L", "CV_P", "CV_B"),
            "org": _bands(sheets, names, "ORG_L", "ORG_P", "ORG_B"),
            "tacos": _bands(sheets, names, "TACOS_L", "TACOS_P", "TACOS_B"),
            "refund": _bands(sheets, names, "REFUND_L", "REFUND_P", "REFUND_B"),
            "fees": _bands(sheets, names, "FEES_L", "FEES_P", "FEES_B"),
            "invlo": _bands(sheets, names, "INVLO_L", "INVLO_P", "INVLO_B"),
            "invhi": _bands(sheets, names, "INVHI_L", "INVHI_P", "INVHI_B"),
            "aov": _bands(sheets, names, "AOV_L", "AOV_P", "AOV_B"),
            "web": _bands(sheets, names, "CONVWEB_L", "CONVWEB_P", "CONVWEB_B"),
            "amazon": _bands(sheets, names, "CONVAMZ_L", "CONVAMZ_P", "CONVAMZ_B"),
            "rating": _bands(sheets, names, "RATE_L", "RATE_P", "RATE_P"),
        }
        self.fields = self._input_fields()

    def _input_fields(self) -> list[dict[str, str]]:
        cells = self.sheets["Inputs"]
        fields = []
        for row in range(1, 80):
            key = cells.get(f"A{row}", "")
            label = cells.get(f"B{row}", "")
            rule = cells.get(f"D{row}", "")
            if not isinstance(key, str) or not isinstance(label, str) or not key.strip() or not label.strip():
                continue
            fields.append({"key": key.strip(), "label": label.strip(), "rule": str(rule).strip()})
        return fields

    def instructions(self) -> str:
        lines = [
            "OUTPUT RULE: Your entire reply is one ```html code block and nothing else.",
            "Do not write a report. Do not write Python. Do not show code, code output, or commentary before or after the block.",
            "Read the listing and the attached files, then fill only the values in the pre block.",
            "Do not assign points, ratings, or bands. The page calculates the score when this HTML is pasted into results.",
            "Leave a value blank when the data does not provide it. Never write 0 for unknown. 0 is a real value.",
            "Money is a plain number. Percentages include a % sign, such as 12.5%. Yes/No fields are Yes or No.",
            "Largest sales channel is Website or Amazon/Marketplace.",
            "Use a $30,000 down payment, 11% interest, a 10-year term, and a 7-year term unless the listing states a different deal.",
            "Put each month on its own line, oldest first, with no gaps: 1 | Jun 2025 | 91789.90",
            "",
            "Definitions, for you only. Do not copy these lines into the reply:",
        ]
        for field in self.fields:
            if field["rule"]:
                lines.append(f"- {field['label']}: {field['rule']}")
        lines.extend([
            "",
            "Reply with this HTML and nothing else:",
            "",
            "```html",
            "<pre>",
            MARKER,
        ])
        for field in self.fields:
            lines.append(f"{field['label']}:")
        lines.extend([
            "1 | month | ",
            "2 | month | ",
            "</pre>",
            "```",
        ])
        return "\n".join(lines)


def _norm_label(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _blank(text: str) -> bool:
    return text.strip().lower() in BLANK_WORDS


def _number(text: str) -> Decimal | None:
    cleaned = text.strip()
    if _blank(cleaned):
        return None
    negative = cleaned.startswith("(") and cleaned.endswith(")")
    cleaned = cleaned.strip("()").replace("$", "").replace(",", "").replace(" ", "")
    cleaned = cleaned.replace("×", "").replace("x", "")
    if _blank(cleaned):
        return None
    try:
        value = Decimal(cleaned)
    except Exception:
        found = re.findall(r"-?\d[\d,]*\.?\d*", text.replace("$", "").replace(",", ""))
        if not found:
            return None
        value = Decimal(found[-1].replace(",", ""))
    return -value if negative else value


def _percent(text: str) -> Decimal | None:
    raw = text.strip()
    if _blank(raw):
        return None
    has_percent = "%" in raw
    value = _number(raw.replace("%", ""))
    if value is None:
        return None
    if has_percent or abs(value) > 1:
        return value / Decimal(100)
    return value


def _yesno(text: str) -> str | None:
    low = text.strip().lower()
    if _blank(low):
        return None
    if re.search(r"\bno\b", low) or "dropship" in low or "print-on-demand" in low or "print on demand" in low:
        return "No"
    if re.search(r"\byes\b", low) or low in {"y", "true"}:
        return "Yes"
    return None


def _channel(text: str) -> str:
    low = text.strip().lower()
    if _blank(low):
        return ""
    if "amazon" in low or "marketplace" in low:
        return "Amazon/Marketplace"
    if "website" in low or "shopify" in low or "woocommerce" in low:
        return "Website"
    return text.strip()


def _parse_value(key: str, raw: str) -> Decimal | str | None:
    if key in TEXT_KEYS:
        text = raw.strip()
        return None if _blank(text) else text
    if key in YESNO_KEYS:
        return _yesno(raw)
    if key in CHANNEL_KEYS:
        return _channel(raw) or None
    if key in PERCENT_KEYS:
        return _percent(raw)
    return _number(raw)


def parse_inputs(text: str, fields: list[dict[str, str]]) -> tuple[dict[str, Decimal | str | None], dict[str, str], list[Decimal | None]]:
    values: dict[str, Decimal | str | None] = {field["key"]: None for field in fields}
    sources: dict[str, str] = {}
    prefixes = [(f"{field['label']}:", field["key"]) for field in fields]
    prefixes.extend((f"{field['key']}:", field["key"]) for field in fields)
    prefixes.sort(key=lambda item: len(item[0]), reverse=True)
    monthly: dict[int, Decimal | None] = {}
    in_months = False
    for line in text.splitlines():
        stripped = re.sub(r"<[^>\n]+>", "", line).strip().strip("`")
        if not stripped or stripped.lower().startswith(MARKER.lower()):
            in_months = False
            continue
        if _norm_label(stripped).startswith("monthly revenue"):
            in_months = True
            embedded = re.search(r"\|\s*(\d+)\s*\|\s*(?:month\s*\|)?\s*(.*)$", stripped, re.IGNORECASE)
            if embedded and 1 <= int(embedded.group(1)) <= 36:
                amount = embedded.group(2).strip()
                monthly[int(embedded.group(1))] = None if _blank(amount) else _number(amount)
            continue
        if in_months and re.match(r"\d+\s*[|:]", stripped):
            parts = [part.strip() for part in re.split(r"\s*[|:]\s*", stripped)]
            if not parts or not parts[0].isdigit():
                continue
            number = int(parts[0])
            amount = parts[-1] if len(parts) > 1 else ""
            if len(parts) == 2 and not re.search(r"\d", parts[1]):
                amount = ""
            if 1 <= number <= 36:
                monthly[number] = None if _blank(amount) else _number(amount)
            continue
        lower = stripped.lower()
        matched = next((item for item in prefixes if item[0].lower() in lower), None)
        if not matched:
            continue
        in_months = False
        raw = stripped[lower.find(matched[0].lower()) + len(matched[0]):]
        value_text, _, source = raw.partition("|")
        values[matched[1]] = _parse_value(matched[1], value_text)
        source = source.strip()
        if source:
            sources[matched[1]] = source
    months: list[Decimal | None] = []
    if monthly:
        for index in range(1, max(monthly) + 1):
            months.append(monthly.get(index))
    return values, sources, months


def _num(value: Decimal | str | None) -> Decimal | None:
    return value if isinstance(value, Decimal) else None


def _count(value: Decimal | str | None) -> bool:
    return isinstance(value, Decimal)


def _population_stdev(values: list[Decimal]) -> Decimal:
    count = Decimal(len(values))
    mean = sum(values, Decimal(0)) / count
    variance = sum((item - mean) ** 2 for item in values) / count
    return variance.sqrt()


def _month_view(months: list[Decimal | None]) -> tuple[list[Decimal | None], int, bool]:
    trimmed = list(months)
    while trimmed and trimmed[-1] is None:
        trimmed.pop()
    count = sum(1 for item in trimmed if item is not None)
    last = 0
    for index, item in enumerate(trimmed, start=1):
        if item is not None:
            last = index
    gap = count != last
    return trimmed, count, gap


def _sum_span(months: list[Decimal | None], start: int, end: int) -> Decimal:
    return sum((item or Decimal(0) for item in months[start - 1:end]), Decimal(0))


def _pct(value: Decimal) -> str:
    return f"{excel_round(value * Decimal(100), 2):.2f}%"


def _money(value: Decimal) -> str:
    rounded = excel_round(value, 2)
    if rounded == rounded.to_integral():
        return f"${int(rounded):,}"
    return f"${rounded:,.2f}"


def _whole(value: Decimal) -> str:
    return f"${int(excel_round(value, 0)):,}"


class MetricRow:
    def __init__(self, section: str, name: str, maximum: int, status: str, points: int, result: str):
        self.section = section
        self.name = name
        self.maximum = maximum
        self.status = status
        self.points = points
        self.result = result


def _inventory_months_row(card: Scorecard, months_on_hand: Decimal | None, no_inventory: bool) -> MetricRow:
    name = "C2 Months of inventory on hand"
    note = "Inventory at cost / monthly COGS"
    if no_inventory:
        return MetricRow("C", name, 10, "N/A", 0, f"N/A · {note}")
    if months_on_hand is None:
        return MetricRow("C", name, 10, "MISSING", 0, f"MISSING · {note}")
    low_points, low_band = _lookup(months_on_hand, card.band["invlo"])
    high_points, high_band = _lookup(months_on_hand, card.band["invhi"])
    if _point(low_points) <= _point(high_points):
        points, band = _point(low_points), low_band
    else:
        points, band = _point(high_points), high_band
    return MetricRow("C", name, 10, "OK", points, f"{months_on_hand:.2f} · {band} · {note}")


def _row(card: Scorecard, section: str, name: str, maximum: int, value: Decimal | None, shown: str, status: str, band_name: str, note: str) -> MetricRow:
    if status != "OK" or value is None:
        points = 0
        result = status
    else:
        point, band = _lookup(value, card.band[band_name])
        points = _point(point)
        result = f"{shown} · {band}"
    if note:
        result = f"{result} · {note}" if result else note
    return MetricRow(section, name, maximum, status, points, result)


def score_values(card: Scorecard, values: dict[str, Decimal | str | None], sources: dict[str, str], months: list[Decimal | None], price_fallback: Decimal | None) -> dict:
    revenue = _num(values.get("Revenue"))
    revenue_ok = revenue is not None and revenue > 0
    net_profit = _num(values.get("NetProfit"))
    addbacks = [_num(values.get(key)) or Decimal(0) for key in ("AB_Owner", "AB_Interest", "AB_DA", "AB_OneTime", "AB_Personal")]
    sde = None if net_profit is None else net_profit + sum(addbacks, Decimal(0))
    cogs = _num(values.get("COGS"))
    gross_margin = excel_round((revenue - cogs) / revenue, 4) if revenue_ok and _count(values.get("COGS")) else None
    ad_spend = _num(values.get("AdSpend"))
    tacos = excel_round(ad_spend / revenue, 4) if revenue_ok and _count(values.get("AdSpend")) else None
    total_orders = _num(values.get("TotalOrders"))
    channel_revenue = _num(values.get("LC_Revenue"))
    channel_orders = _num(values.get("LC_Orders"))
    if revenue_ok and total_orders is not None and total_orders > 0:
        aov = excel_round(revenue / total_orders, 2)
        aov_method = "All channels"
    elif channel_revenue is not None and channel_orders is not None and channel_revenue > 0 and channel_orders > 0:
        aov = excel_round(channel_revenue / channel_orders, 2)
        aov_method = "Largest channel (fallback)"
    else:
        aov = None
        aov_method = "MISSING"
    trimmed, month_count, gap = _month_view(months)
    comparison = min(12, month_count - 12) if month_count >= 15 and not gap else None
    last_twelve = _sum_span(trimmed, month_count - 11, month_count) if month_count >= 12 and not gap else None
    revenue_check = ""
    if last_twelve is not None and revenue_ok and revenue is not None:
        revenue_check = "Differs by more than 2% - check inputs" if abs(last_twelve / revenue - 1) > Decimal("0.02") else "OK"
    ad_revenue = _num(values.get("AdRevenue"))
    if revenue_ok and _count(values.get("AdRevenue")) and revenue is not None and ad_revenue is not None:
        organic = excel_round(1 - ad_revenue / revenue, 4)
        organic_note = "1 - ad-attributed revenue / Revenue"
    elif tacos is not None:
        organic = excel_round(max(Decimal(0), 1 - 3 * tacos), 4)
        organic_note = "Fallback: 1 - 3 x TACoS"
    else:
        organic = None
        organic_note = ""
    trend = None
    trend_note = "Needs 12+ months of monthly revenue"
    if comparison is not None:
        recent = _sum_span(trimmed, month_count - comparison + 1, month_count)
        prior = _sum_span(trimmed, month_count - comparison - 11, month_count - 12)
        trend = excel_round(recent / prior - 1, 4) if prior != 0 else None
        trend_note = f"Year over year, latest {comparison} months" if comparison < 12 else "Full TTM vs prior 12 months"
    elif month_count >= 12 and not gap:
        recent = _sum_span(trimmed, month_count - 5, month_count)
        prior = _sum_span(trimmed, month_count - 11, month_count - 6)
        trend = excel_round(recent / prior - 1, 4) if prior != 0 else None
        trend_note = "Last 6 months vs prior 6 (less than 15 months of data)"
    volatility = None
    if month_count >= 12 and not gap:
        window = [item for item in trimmed[month_count - 12:month_count] if item is not None]
        average = sum(window, Decimal(0)) / Decimal(len(window))
        if average != 0:
            volatility = excel_round(_population_stdev(window) / average, 4)
    sde_margin = excel_round(sde / revenue, 4) if revenue_ok and sde is not None and revenue is not None else None
    net_margin = excel_round(net_profit / revenue, 4) if revenue_ok and _count(values.get("NetProfit")) and net_profit is not None and revenue is not None else None
    refunds = _num(values.get("Refunds"))
    refund_rate = excel_round(refunds / revenue, 4) if revenue_ok and _count(values.get("Refunds")) and refunds is not None and revenue is not None else None
    fees = _num(values.get("PlatformFees"))
    fee_rate = excel_round(fees / revenue, 4) if revenue_ok and _count(values.get("PlatformFees")) and fees is not None and revenue is not None else None
    inventory = _num(values.get("AvgInventory"))
    months_on_hand = excel_round(inventory / (cogs / 12), 2) if cogs is not None and cogs > 0 and _count(values.get("AvgInventory")) and inventory is not None else None
    no_inventory = values.get("HasInventory") == "No"
    owner_yes = sum(1 for key in ("Owner_1", "Owner_2", "Owner_3", "Owner_4", "Owner_5") if values.get(key) == "Yes")
    conversion = excel_round(_num(values.get("ConvRate")), 4) if _count(values.get("ConvRate")) and values.get("LargestChannel") else None
    channel = values.get("LargestChannel") if isinstance(values.get("LargestChannel"), str) else ""
    conversion_band = "web" if channel == "Website" else "amazon"
    conversion_note = f"{channel} table" if channel else "Pick the largest channel on Inputs"
    gross_note = "FLAG: COGS may be under-reported (margin > 80%)" if gross_margin is not None and gross_margin > Decimal("0.8") else "(Revenue - COGS) / Revenue"

    rows = [
        _row(card, "A", "A1 SDE / EBITDA (SDE margin)", 15, sde_margin, _pct(sde_margin) if sde_margin is not None else "", "OK" if sde_margin is not None else "MISSING", "sde", "SDE / Revenue"),
        _row(card, "A", "A2 Gross profit margin", 10, gross_margin, _pct(gross_margin) if gross_margin is not None else "", "OK" if gross_margin is not None else "MISSING", "gm", gross_note),
        _row(card, "A", "A3 Net profit margin", 5, net_margin, _pct(net_margin) if net_margin is not None else "", "OK" if net_margin is not None else "MISSING", "net", "Net profit (pre-tax) / Revenue"),
        _row(card, "A", "A4a Revenue trend", 10, trend, _pct(trend) if trend is not None else "", "OK" if trend is not None else "MISSING", "yoy", trend_note),
        _row(card, "A", "A4b Monthly stability (CV)", 5, volatility, _pct(volatility) if volatility is not None else "", "OK" if volatility is not None else "MISSING", "cv", "Population std dev / average, last 12 months"),
        _row(card, "B", "B1 Organic vs paid (organic share)", 10, organic, _pct(organic) if organic is not None else "", "OK" if organic is not None else "MISSING", "org", organic_note),
        _row(card, "B", "B2 Ad spend share (TACoS)", 5, tacos, _pct(tacos) if tacos is not None else "", "OK" if tacos is not None else "MISSING", "tacos", "Ad spend / Revenue"),
        _row(card, "B", "B3 Returns and refunds", 5, refund_rate, _pct(refund_rate) if refund_rate is not None else "", "OK" if refund_rate is not None else "MISSING", "refund", "Refunds + return costs / Revenue"),
        MetricRow("B", "B4 Owner dependency", 5, "OK", owner_yes, f"{owner_yes} of 5 statements"),
        _row(card, "C", "C1 Platform & fulfillment fees", 10, fee_rate, _pct(fee_rate) if fee_rate is not None else "", "OK" if fee_rate is not None else "MISSING", "fees", "Fees / Revenue"),
        _inventory_months_row(card, months_on_hand, no_inventory),
        _row(card, "D", "D1 Average order value", 5, aov, _money(aov) if aov is not None else "", "OK" if aov is not None else "MISSING", "aov", aov_method),
        _row(card, "D", "D2 Conversion rate (largest channel)", 5, conversion, _pct(conversion) if conversion is not None else "", "OK" if conversion is not None else "MISSING", conversion_band, conversion_note),
    ]
    for row in rows:
        source = sources.get({
            "A1 SDE / EBITDA (SDE margin)": "NetProfit",
            "A2 Gross profit margin": "COGS",
            "A3 Net profit margin": "NetProfit",
            "B3 Returns and refunds": "Refunds",
            "C1 Platform & fulfillment fees": "PlatformFees",
            "D2 Conversion rate (largest channel)": "ConvRate",
        }.get(row.name, ""))
        if source:
            row.result = f"{row.result} · {source}"
    earned = sum(row.points for row in rows)
    removed = sum(row.maximum for row in rows if row.status == "N/A")
    missing = sum(row.maximum for row in rows if row.status == "MISSING")
    possible = 100 - removed
    final = int(excel_round(Decimal(earned) / Decimal(possible) * Decimal(100), 0)) if possible else 0
    rating, _band = _lookup(Decimal(final), card.band["rating"])
    completeness = (Decimal(possible) - Decimal(missing)) / Decimal(possible) if possible else Decimal(0)
    warning = "Score is unreliable - significant data missing" if completeness < Decimal("0.7") else ""
    financing = _financing(values, sde, trimmed, month_count, gap, price_fallback)
    flags = []
    if gap:
        flags.append("Monthly revenue has gaps.")
    if revenue_check and revenue_check != "OK":
        flags.append(revenue_check)
    if gross_margin is not None and gross_margin > Decimal("0.8"):
        flags.append("COGS may be under-reported.")
    return {
        "rows": rows,
        "earned": earned,
        "removed": removed,
        "missing": missing,
        "possible": possible,
        "final": final,
        "rating": str(rating),
        "completeness": completeness,
        "warning": warning,
        "financing": financing,
        "flags": flags,
        "sde": sde,
    }


def _payment(principal: Decimal, annual_rate: Decimal, years: Decimal) -> Decimal | None:
    if years <= 0:
        return None
    payments = years * 12
    monthly_rate = annual_rate / 12
    if monthly_rate == 0:
        return principal / payments
    return principal * monthly_rate / (1 - (1 + monthly_rate) ** (-payments))


def _financing(values, sde: Decimal | None, months: list[Decimal | None], month_count: int, gap: bool, price_fallback: Decimal | None) -> dict:
    notes = []
    price = _num(values.get("Price"))
    if price is None and price_fallback is not None and price_fallback > 0:
        price = price_fallback
        notes.append("Purchase price used the listing price.")
    down = _num(values.get("Down"))
    rate = _num(values.get("Rate"))
    term1 = _num(values.get("Term1"))
    term2 = _num(values.get("Term2"))
    if down is None or rate is None or term1 is None or term2 is None:
        down = DOWN_DEFAULT if down is None else down
        rate = RATE_DEFAULT if rate is None else rate
        term1 = TERM1_DEFAULT if term1 is None else term1
        term2 = TERM2_DEFAULT if term2 is None else term2
        notes.append("Blank financing inputs used $30,000 down, 11%, 10 years, and 7 years.")
    terms = []
    if price is not None and price > 0:
        principal = price - (down or Decimal(0))
        for years in (term1, term2):
            if years is None:
                continue
            payment = _payment(principal, rate, years)
            if payment is None:
                continue
            annual = payment * 12
            cash_flow = None if sde is None else sde / 12 - payment
            dscr = excel_round(sde / annual, 2) if sde is not None and annual > 0 else None
            cash_on_cash = (sde - annual) / down if sde is not None and down is not None and down > 0 else None
            terms.append({
                "years": int(years) if years == years.to_integral() else years,
                "payment": payment,
                "cash_flow": cash_flow,
                "dscr": dscr,
                "cash_on_cash": cash_on_cash,
            })
    last6 = _num(values.get("SDE_Last6"))
    run_rate = last6 * 2 if last6 is not None else None
    if run_rate is None and month_count >= 6 and not gap and sde is not None:
        run_rate = None
    return {"terms": terms, "notes": notes, "run_rate": run_rate, "sde": sde, "down": down}


def _esc(text: object) -> str:
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def render_html(result: dict) -> str:
    rows = ['<table>', "<thead><tr><th>Metric</th><th>Max</th><th>Points</th><th>Result</th></tr></thead>", "<tbody>"]
    sections = (("A", "A. Financial Health", 45), ("B", "B. Business Sustainability", 25), ("C", "C. Operational Health", 20), ("D", "D. Growth Potential", 10))
    grouped: dict[str, list[MetricRow]] = {key: [] for key, _name, _maximum in sections}
    for row in result["rows"]:
        grouped[row.section].append(row)
    for key, title, maximum in sections:
        for row in grouped[key]:
            rows.append(f"<tr><td>{_esc(row.name)}</td><td>{row.maximum}</td><td>{row.points}</td><td>{_esc(row.result)}</td></tr>")
        earned = sum(row.points for row in grouped[key])
        rows.append(f"<tr><td><strong>{title}</strong></td><td><strong>{maximum}</strong></td><td><strong>{earned}</strong></td><td></td></tr>")
    final_bits = [f"{result['earned']} of {result['possible']} points", str(result["rating"]), f"Data completeness {_pct(result['completeness'])}"]
    if result["warning"]:
        final_bits.append(result["warning"])
    final_bits.extend(result["flags"])
    rows.append(
        f"<tr><td><strong>Final score</strong></td><td><strong>100</strong></td><td><strong>{result['final']}</strong></td><td><strong>{_esc('. '.join(final_bits))}</strong></td></tr>"
    )
    rows.append("</tbody></table>")
    financing = result["financing"]
    takeaways = ['<div class="financial-takeaways">', "<h3>Key Financial Takeaways</h3>"]
    takeaways.append('<div class="takeaway-section"><h4>1. Monthly Loan Payments & Cash Flow</h4><ul>')
    if financing["terms"]:
        for term in financing["terms"]:
            cash = "SDE is missing, so cash flow after the loan is not calculated." if term["cash_flow"] is None else f"After paying the loan, SDE leaves {_whole(term['cash_flow'])}/month."
            takeaways.append(f"<li><strong>{_esc(term['years'])}-year term:</strong> Monthly payment {_whole(term['payment'])}. {_esc(cash)}</li>")
    else:
        takeaways.append("<li>Purchase price is missing, so the loan payment is not calculated.</li>")
    for note in financing["notes"]:
        takeaways.append(f"<li>{_esc(note)}</li>")
    takeaways.append("</ul></div>")
    takeaways.append('<div class="takeaway-section"><h4>2. Debt Service Coverage Ratio (DSCR)</h4><ul>')
    takeaways.append("<li><strong>Formula:</strong> DSCR = SDE / Annual Debt Service</li>")
    if any(term["dscr"] is not None for term in financing["terms"]):
        for term in financing["terms"]:
            if term["dscr"] is None:
                continue
            compared = "above" if term["dscr"] >= Decimal("1.25") else "below"
            takeaways.append(f"<li><strong>{_esc(term['years'])}-year term:</strong> DSCR is {term['dscr']}×, {compared} a 1.25× lender minimum.</li>")
    else:
        takeaways.append("<li>DSCR needs SDE and a loan payment.</li>")
    takeaways.append("</ul></div>")
    takeaways.append('<div class="takeaway-section"><h4>3. Return on Investment (ROI) on Cash-on-Cash Basis</h4><ul>')
    down = financing.get("down")
    if isinstance(down, Decimal):
        takeaways.append(f"<li>Down payment: <strong>{_whole(down)}</strong>.</li>")
    shown_return = False
    for term in financing["terms"]:
        if term["cash_on_cash"] is None:
            continue
        shown_return = True
        annual_cash = None if term["cash_flow"] is None else term["cash_flow"] * 12
        cash_text = _whole(annual_cash) if annual_cash is not None else "the remaining SDE"
        takeaways.append(
            f"<li><strong>{_esc(term['years'])}-year term:</strong> {cash_text} of annual cash flow after debt service is {_pct(term['cash_on_cash'])} cash-on-cash return.</li>"
        )
    if not shown_return:
        takeaways.append("<li>Cash-on-cash return needs SDE, the loan payment, and a down payment.</li>")
    takeaways.append("</ul></div></div>")
    return "\n".join(rows + takeaways)


def scorecard_instructions(path: Path = SCORECARD_PATH) -> str:
    try:
        return Scorecard(path).instructions()
    except (OSError, zipfile.BadZipFile, KeyError, ET.ParseError):
        return "The E-commerce Scorecard could not be read, so this prompt has no scoring inputs."


def score_inputs_html(text: str, price_fallback: int | None = None, path: Path = SCORECARD_PATH) -> str | None:
    if MARKER.lower() not in text.lower():
        return None
    try:
        card = Scorecard(path)
    except (OSError, zipfile.BadZipFile, KeyError, ET.ParseError) as error:
        raise ValueError("The E-commerce Scorecard could not be read.") from error
    values, sources, months = parse_inputs(text, card.fields)
    fallback = Decimal(price_fallback) if isinstance(price_fallback, int) and price_fallback > 0 else None
    result = score_values(card, values, sources, months, fallback)
    html = render_html(result)
    if len(html) > 100_000:
        raise ValueError("That results HTML is too long.")
    return html


if __name__ == "__main__":
    sample = """
SCORECARD INPUTS
Business name: Example Co
Holds physical inventory?: Yes
Largest sales channel by revenue: Amazon/Marketplace
Revenue: 250000
COGS (landed product cost only): 75000
Net profit before income tax: 40000
Add-back: owner salary & benefits (one owner): 20000
Add-back: interest: 2000
Add-back: depreciation & amortization: 1000
Add-back: personal expenses paid by business: 1500
Ad spend (all channels): 30000
Ad-attributed revenue (all channels): 90000
Refunds + return processing costs (all channels): 8000
Platform & fulfillment fees (all channels): 70000
Total orders, all channels: 6500
Largest channel: revenue: 200000
Largest channel: orders: 5400
Largest channel: conversion rate: 12%
Inventory value at cost: 35000
Owner works <= 10 hrs/week: No
Written SOPs exist for core operations: Yes
Daily ops handled by staff/VAs/agencies: No
Brand not tied to owner's personal identity: Yes
Supplier relationships documented & transferable: Yes
Purchase price: 125000
Down payment: 30000
Annual interest rate: 11%
Loan term 1 (years): 10
Loan term 2 (years): 7
Monthly revenue (oldest month first, no gaps, up to 36):
1 | m | 16000
2 | m | 15500
3 | m | 17000
4 | m | 18500
5 | m | 18000
6 | m | 19000
7 | m | 20500
8 | m | 20000
9 | m | 18500
10 | m | 21500
11 | m | 26000
12 | m | 33000
13 | m | 17500
14 | m | 17000
15 | m | 18500
16 | m | 19500
17 | m | 19000
"""
    card = Scorecard()
    values, sources, months = parse_inputs(sample, card.fields)
    result = score_values(card, values, sources, months, None)
    by_name = {row.name: row.points for row in result["rows"]}
    expected = {
        "A1 SDE / EBITDA (SDE margin)": 15,
        "A2 Gross profit margin": 10,
        "A3 Net profit margin": 4,
        "A4a Revenue trend": 6,
        "B1 Organic vs paid (organic share)": 6,
        "B2 Ad spend share (TACoS)": 3,
        "B3 Returns and refunds": 4,
        "B4 Owner dependency": 3,
        "C1 Platform & fulfillment fees": 6,
        "C2 Months of inventory on hand": 7,
        "D1 Average order value": 2,
        "D2 Conversion rate (largest channel)": 3,
    }
    for name, points in expected.items():
        if by_name[name] != points:
            raise SystemExit(f"{name}: {by_name[name]} != {points}")
    if result["final"] != 73:
        raise SystemExit(f"final {result['final']}")
    short = score_values(card, values, sources, months[:12], None)
    trend = next(row for row in short["rows"] if row.name.startswith("A4a"))
    if trend.points != 10:
        raise SystemExit(f"6v6 {trend.points} {trend.result}")
    payments = [int(excel_round(term["payment"], 0)) for term in result["financing"]["terms"]]
    if payments != [1309, 1627]:
        raise SystemExit(f"payments {payments}")
    print({row.name: row.points for row in result["rows"]})
    print("final", result["final"], result["rating"], "earned", result["earned"])
