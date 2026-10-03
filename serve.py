"""Local page for the scraped Flippa listings.

    py serve.py

Then open http://127.0.0.1:8765
"""

from __future__ import annotations

import csv
import json
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from scrape import PUBLIC_FIELDS

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "output"
WEB = ROOT / "web"
BUSINESSES_PATH = OUTPUT / "businesses.json"
SAVED_PATH = OUTPUT / "saved.json"
DELETED_PATH = OUTPUT / "deleted.json"
FIRST_ACCESS_PATH = OUTPUT / "first_access.json"
HOST = "127.0.0.1"
PORT = 8765


def read_json(path: Path, fallback):
    if not path.is_file():
        return fallback
    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        return fallback
    return json.loads(raw)


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def listing_number(row: dict) -> str:
    return str(row.get("listing_id", "")).strip()


def load_businesses() -> list[dict]:
    data = read_json(BUSINESSES_PATH, [])
    return data if isinstance(data, list) else []


def load_saved() -> list[dict]:
    data = read_json(SAVED_PATH, [])
    return data if isinstance(data, list) else []


def load_first_access() -> list[dict]:
    data = read_json(FIRST_ACCESS_PATH, [])
    return data if isinstance(data, list) else []


def load_deleted() -> list[str]:
    data = read_json(DELETED_PATH, [])
    numbers = []
    for item in data:
        if isinstance(item, dict):
            item = item.get("listing_id", "")
        number = str(item).strip()
        if number and number not in numbers:
            numbers.append(number)
    return numbers


def write_businesses(rows: list[dict]) -> None:
    write_json(BUSINESSES_PATH, rows)
    csv_path = OUTPUT / "businesses.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=PUBLIC_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in PUBLIC_FIELDS})
    names = OUTPUT / "names.txt"
    names.write_text("\n".join(str(row.get("name", "")) for row in rows) + ("\n" if rows else ""), encoding="utf-8")


def public_row(row: dict) -> dict:
    return {key: row.get(key, "") for key in PUBLIC_FIELDS}


def state() -> dict:
    return {
        "businesses": load_businesses(),
        "saved": load_saved(),
        "deleted": load_deleted(),
        "first_access": load_first_access(),
    }


def delete_all_review() -> None:
    deleted = load_deleted()
    for row in load_businesses():
        number = listing_number(row)
        if number and number not in deleted:
            deleted.append(number)
    write_businesses([])
    write_json(DELETED_PATH, deleted)


def delete_listing(number: str) -> None:
    businesses = [row for row in load_businesses() if listing_number(row) != number]
    saved = [row for row in load_saved() if listing_number(row) != number]
    first_access = [row for row in load_first_access() if listing_number(row) != number]
    deleted = load_deleted()
    if number not in deleted:
        deleted.append(number)
    write_businesses(businesses)
    write_json(SAVED_PATH, saved)
    write_json(FIRST_ACCESS_PATH, first_access)
    write_json(DELETED_PATH, deleted)


def save_listing(number: str) -> None:
    businesses = load_businesses()
    chosen = next((row for row in businesses if listing_number(row) == number), None)
    if chosen is None:
        raise KeyError(number)
    saved = load_saved()
    if not any(listing_number(row) == number for row in saved):
        saved.append(public_row(chosen))
    write_businesses([row for row in businesses if listing_number(row) != number])
    write_json(SAVED_PATH, saved)


def first_access_listing(number: str, days: int) -> None:
    if days < 1:
        raise ValueError("days must be 1 or more")
    businesses = load_businesses()
    chosen = next((row for row in businesses if listing_number(row) == number), None)
    if chosen is None:
        raise KeyError(number)
    record = public_row(chosen)
    record["view_on"] = (date.today() + timedelta(days=days)).isoformat()
    record["access_days"] = days
    queued = [row for row in load_first_access() if listing_number(row) != number]
    queued.append(record)
    write_businesses([row for row in businesses if listing_number(row) != number])
    write_json(FIRST_ACCESS_PATH, queued)


def restore_listing(number: str) -> None:
    saved = load_saved()
    chosen = next((row for row in saved if listing_number(row) == number), None)
    if chosen is None:
        raise KeyError(number)
    deleted = [item for item in load_deleted() if item != number]
    businesses = load_businesses()
    if not any(listing_number(row) == number for row in businesses):
        businesses.append(public_row(chosen))
    write_json(SAVED_PATH, [row for row in saved if listing_number(row) != number])
    write_json(DELETED_PATH, deleted)
    write_businesses(businesses)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/state":
            self._send_json(state())
            return
        if path in {"/", "/index.html"}:
            page = WEB / "index.html"
            body = page.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_error(404)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        actions = {
            "/api/delete": delete_listing,
            "/api/delete-all": delete_all_review,
            "/api/save": save_listing,
            "/api/restore": restore_listing,
            "/api/first-access": first_access_listing,
        }
        action = actions.get(path)
        if action is None:
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", "0"))
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            if path == "/api/delete-all":
                delete_all_review()
                self._send_json(state())
                return
            number = str(payload.get("listing_id", "")).strip()
            if not number.isdigit():
                raise ValueError("listing_id must be the Flippa listing number")
            if path == "/api/first-access":
                days = payload.get("days")
                if isinstance(days, bool) or not isinstance(days, int):
                    raise ValueError("days must be a whole number")
                first_access_listing(number, days)
            else:
                action(number)
        except KeyError:
            self._send_json({"error": "listing not found"}, status=404)
            return
        except (ValueError, json.JSONDecodeError) as error:
            self._send_json({"error": str(error)}, status=400)
            return
        self._send_json(state())

    def log_message(self, format: str, *args) -> None:
        print(f"{self.address_string()} {format % args}")

    def _send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Open http://{HOST}:{PORT}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
