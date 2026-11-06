"""Local Flippa-style filter page.

    python serve.py

The page is served at http://127.0.0.1:8765.

Search writes output/filters.txt and imports listings from Flippa's public
search HTML. Named presets live in output/saved-filters/ and do not replace
filters.txt until Search. python scrape.py still scrapes that file without
this page.
"""

from __future__ import annotations

import csv
import json
import re
import socket
import sys
import threading
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from scrape import (
    DEFAULT_DELAY,
    DEFAULT_TIMEOUT,
    PUBLIC_FIELDS,
    FilterError,
    excluded_listing_ids,
    filter_form,
    filter_options,
    read_filters,
    scrape,
    settings_from_form,
    write_filters_file,
    write_outputs,
)

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "output"
WEB = ROOT / "web"
BUSINESSES_PATH = OUTPUT / "businesses.json"
SAVED_PATH = OUTPUT / "saved.json"
DELETED_PATH = OUTPUT / "deleted.json"
FIRST_ACCESS_PATH = OUTPUT / "first_access.json"
NDA_PATH = OUTPUT / "nda.json"
WAITING_PATH = OUTPUT / "waiting_inquiry.json"
RATINGS_PATH = OUTPUT / "ratings.json"
FILTERS_PATH = OUTPUT / "filters.txt"
SAVED_FILTERS = OUTPUT / "saved-filters"
MAX_BODY = 200_000
_run_lock = threading.Lock()
LISTEN_HOST = "127.0.0.1"
LISTEN_PORT = 8765
LISTEN_URL = f"http://{LISTEN_HOST}:{LISTEN_PORT}"


def print_listen_target() -> None:
    """Print url|host|port for the launcher."""
    print(f"{LISTEN_URL}|{LISTEN_HOST}|{LISTEN_PORT}")


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


_FLIPPA_LISTING_URL = re.compile(r"https://flippa\.com/\d+")


def flippa_listing_url(number: str, url: str = "") -> str:
    text = str(url or "").strip()
    if _FLIPPA_LISTING_URL.fullmatch(text):
        return text
    if str(number).isdigit():
        return f"https://flippa.com/{number}"
    return ""


def known_listings() -> dict[str, dict]:
    """Listings still stored on a review or holding tab, including Waiting inquiry."""
    found: dict[str, dict] = {}
    for rows in (load_businesses(), load_saved(), load_first_access(), load_nda(), load_waiting()):
        for row in rows:
            number = listing_number(row)
            if number and number not in found:
                found[number] = row
    return found


def deleted_note(item) -> str:
    if not isinstance(item, dict):
        return ""
    return str(item.get("note") or "").strip()


def deleted_disk(record: dict) -> dict:
    """Stored shape. An empty note is left off so older rows stay valid."""
    stored = {
        "listing_id": record["listing_id"],
        "name": record.get("name") or "",
        "url": record.get("url") or "",
    }
    note = str(record.get("note") or "").strip()
    if note:
        stored["note"] = note
    return stored


def deleted_record(item, known: dict[str, dict] | None = None) -> dict | None:
    if isinstance(item, dict):
        number = str(item.get("listing_id", "")).strip()
        name = str(item.get("name") or "").strip()
        url = str(item.get("url") or "").strip()
        note = deleted_note(item)
    else:
        number = str(item).strip()
        name = ""
        url = ""
        note = ""
    if not number:
        return None
    row = (known or {}).get(number)
    if row is not None:
        if not name:
            name = str(row.get("name") or "").strip()
        if not _FLIPPA_LISTING_URL.fullmatch(url):
            url = str(row.get("url") or "").strip()
    return {
        "listing_id": number,
        "name": name,
        "url": flippa_listing_url(number, url),
        "note": note,
    }


def _same_deleted_record(item, record: dict) -> bool:
    if not isinstance(item, dict):
        return False
    if set(item) - {"listing_id", "name", "url", "note"}:
        return False
    if not {"listing_id", "name", "url"} <= set(item):
        return False
    current = deleted_disk({
        "listing_id": str(item.get("listing_id", "")).strip(),
        "name": str(item.get("name") or "").strip(),
        "url": str(item.get("url") or "").strip(),
        "note": deleted_note(item),
    })
    return current == deleted_disk(record)


def clean_note(raw: object) -> str:
    if raw is None:
        return ""
    if not isinstance(raw, str):
        raise ValueError("note must be text")
    note = raw.strip()
    if len(note) > 2000:
        raise ValueError("Use a shorter note.")
    return note


def load_businesses() -> list[dict]:
    data = read_json(BUSINESSES_PATH, [])
    return data if isinstance(data, list) else []


def load_saved() -> list[dict]:
    data = read_json(SAVED_PATH, [])
    return data if isinstance(data, list) else []


def load_first_access() -> list[dict]:
    data = read_json(FIRST_ACCESS_PATH, [])
    return data if isinstance(data, list) else []


def load_nda() -> list[dict]:
    data = read_json(NDA_PATH, [])
    return data if isinstance(data, list) else []


def load_waiting() -> list[dict]:
    data = read_json(WAITING_PATH, [])
    return data if isinstance(data, list) else []


def load_ratings() -> dict[str, int]:
    """Saved 1–5 scores keyed by listing id. Missing file means nothing is rated."""
    data = read_json(RATINGS_PATH, {})
    if not isinstance(data, dict):
        return {}
    ratings: dict[str, int] = {}
    for key, value in data.items():
        number = str(key).strip()
        if not number.isdigit() or isinstance(value, bool) or not isinstance(value, int):
            continue
        if 1 <= value <= 5:
            ratings[number] = value
    return ratings


def write_ratings(ratings: dict[str, int]) -> None:
    ordered = dict(sorted(ratings.items(), key=lambda item: int(item[0])))
    write_json(RATINGS_PATH, ordered)


def set_rating(number: str, rating: int | None) -> None:
    """Store or clear a score. Unknown ids are ignored so no listing is created."""
    if number not in known_listings():
        return
    ratings = load_ratings()
    if rating is None:
        if number not in ratings:
            return
        del ratings[number]
    elif ratings.get(number) == rating:
        return
    else:
        ratings[number] = rating
    write_ratings(ratings)


def drop_waiting(number: str) -> None:
    if not WAITING_PATH.is_file():
        return
    rows = load_waiting()
    kept = [row for row in rows if listing_number(row) != number]
    if len(kept) != len(rows):
        write_json(WAITING_PATH, kept)


def find_listing(number: str, pools: tuple[list[dict], ...]) -> dict | None:
    for rows in pools:
        chosen = next((row for row in rows if listing_number(row) == number), None)
        if chosen is not None:
            return chosen
    return None


def write_deleted(records: list[dict]) -> None:
    write_json(DELETED_PATH, [deleted_disk(record) for record in records])


def load_deleted() -> list[dict]:
    """Deleted listings as id, name, url, and an optional note."""
    data = read_json(DELETED_PATH, [])
    if not isinstance(data, list):
        data = []
    needs_lookup = any(
        not isinstance(item, dict) or not str(item.get("name") or "").strip()
        for item in data
    )
    known = known_listings() if needs_lookup else {}
    records: list[dict] = []
    seen: set[str] = set()
    changed = False
    for item in data:
        record = deleted_record(item, known)
        if record is None or record["listing_id"] in seen:
            changed = True
            continue
        seen.add(record["listing_id"])
        records.append(record)
        if not _same_deleted_record(item, record):
            changed = True
    if changed:
        write_deleted(records)
    return records


def remember_deleted(deleted: list[dict], number: str, row: dict | None, note: str | None = None) -> None:
    name = str((row or {}).get("name") or "").strip()
    url = flippa_listing_url(number, str((row or {}).get("url") or ""))
    text = None if note is None else note.strip()
    for record in deleted:
        if record["listing_id"] != number:
            continue
        if name and not record["name"]:
            record["name"] = name
        if url and not record["url"]:
            record["url"] = url
        if text is not None:
            record["note"] = text
        return
    deleted.append({
        "listing_id": number,
        "name": name,
        "url": url,
        "note": text or "",
    })


def write_businesses(rows: list[dict]) -> None:
    write_json(BUSINESSES_PATH, rows)
    csv_path = OUTPUT / "businesses.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=PUBLIC_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in PUBLIC_FIELDS})
    names = OUTPUT / "names.txt"
    names.write_text(
        "\n".join(str(row.get("name", "")) for row in rows) + ("\n" if rows else ""),
        encoding="utf-8",
    )


def public_row(row: dict) -> dict:
    return {key: row.get(key, "") for key in PUBLIC_FIELDS}


_PRESET_NAME = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9 ._-]*[A-Za-z0-9])?")
_RESERVED_NAMES = {"CON", "PRN", "AUX", "NUL"}


def clean_preset_name(raw: object) -> str:
    """Return a file name that stays inside output/saved-filters/."""
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("Enter a name for this filter.")
    if any(ord(char) < 32 for char in raw) or "/" in raw or "\\" in raw or ".." in raw:
        raise ValueError("That name cannot be used.")
    name = " ".join(raw.split())
    if name.lower().endswith(".txt"):
        name = name[:-4].strip()
    if not name:
        raise ValueError("Enter a name for this filter.")
    if len(name) > 80:
        raise ValueError("Use a shorter name.")
    if not _PRESET_NAME.fullmatch(name):
        raise ValueError("Use letters, numbers, spaces, hyphens, or periods in the name.")
    stem = name.split(".", 1)[0].upper()
    reserved = stem in _RESERVED_NAMES or (
        len(stem) == 4 and stem[:3] in {"COM", "LPT"} and stem[3] in "123456789"
    )
    if reserved:
        raise ValueError("That name cannot be used.")
    return name


def preset_path(name: object) -> tuple[str, Path]:
    safe = clean_preset_name(name)
    root = SAVED_FILTERS.resolve()
    path = root / f"{safe}.txt"
    if path.parent != root or path.is_symlink():
        raise ValueError("That name cannot be used.")
    return safe, path


def list_saved_filters() -> list[str]:
    if not SAVED_FILTERS.is_dir():
        return []
    root = SAVED_FILTERS.resolve()
    names: list[str] = []
    for path in SAVED_FILTERS.iterdir():
        if path.is_symlink() or not path.is_file() or path.suffix.lower() != ".txt":
            continue
        if path.resolve().parent != root:
            continue
        names.append(path.stem)
    names.sort(key=str.casefold)
    return names


def _existing_preset(safe: str) -> Path | None:
    root = SAVED_FILTERS.resolve()
    if not root.is_dir():
        return None
    for path in root.iterdir():
        if path.is_symlink() or not path.is_file() or path.suffix.lower() != ".txt":
            continue
        if path.resolve().parent != root:
            continue
        if path.stem.casefold() == safe.casefold():
            return path
    return None


def save_filter_preset(payload: dict) -> str:
    """Write the current form as a preset. filters.txt is left unchanged."""
    if not isinstance(payload, dict):
        raise ValueError("expected an object")
    safe, path = preset_path(payload.get("name", ""))
    if _existing_preset(safe) is not None:
        raise ValueError("That name is already taken.")
    settings = settings_from_form(payload)
    write_filters_file(path, settings)
    return safe


def load_filter_preset(name: object) -> dict:
    """Read a preset for the form. Does not write filters.txt or import listings."""
    safe, _path = preset_path(name)
    path = _existing_preset(safe)
    if path is None:
        raise KeyError(safe)
    return filter_form(read_filters(path))


def delete_filter_preset(name: object) -> None:
    safe, _path = preset_path(name)
    path = _existing_preset(safe)
    if path is None:
        raise KeyError(safe)
    path.unlink()


def filters_payload() -> dict:
    options = filter_options()
    try:
        settings = read_filters(FILTERS_PATH)
    except FilterError as error:
        return {"error": str(error), "options": options, "form": None}
    return {"error": None, "options": options, "form": filter_form(settings)}


def state() -> dict:
    return {
        "businesses": load_businesses(),
        "saved": load_saved(),
        "deleted": load_deleted(),
        "first_access": load_first_access(),
        "nda": load_nda(),
        "waiting_inquiry": load_waiting(),
        "ratings": load_ratings(),
        "filters": filters_payload(),
        "saved_filters": list_saved_filters(),
    }


def delete_all_review() -> None:
    businesses = load_businesses()
    deleted = load_deleted()
    for row in businesses:
        number = listing_number(row)
        if number:
            remember_deleted(deleted, number, row)
    write_businesses([])
    write_deleted(deleted)


def delete_listing(number: str, note: str = "") -> None:
    source = known_listings().get(number)
    businesses = [row for row in load_businesses() if listing_number(row) != number]
    saved = [row for row in load_saved() if listing_number(row) != number]
    first_access = [row for row in load_first_access() if listing_number(row) != number]
    nda = [row for row in load_nda() if listing_number(row) != number]
    deleted = load_deleted()
    remember_deleted(deleted, number, source, note)
    write_businesses(businesses)
    write_json(SAVED_PATH, saved)
    write_json(FIRST_ACCESS_PATH, first_access)
    write_json(NDA_PATH, nda)
    drop_waiting(number)
    write_deleted(deleted)


def save_listing(number: str) -> None:
    chosen = find_listing(number, (load_businesses(), load_waiting()))
    if chosen is None:
        raise KeyError(number)
    saved = load_saved()
    if not any(listing_number(row) == number for row in saved):
        saved.append(public_row(chosen))
    write_businesses([row for row in load_businesses() if listing_number(row) != number])
    drop_waiting(number)
    write_json(SAVED_PATH, saved)


def first_access_listing(number: str, days: int) -> None:
    if days < 1:
        raise ValueError("days must be 1 or more")
    chosen = find_listing(number, (load_businesses(), load_waiting()))
    if chosen is None:
        raise KeyError(number)
    record = public_row(chosen)
    record["view_on"] = (date.today() + timedelta(days=days)).isoformat()
    record["access_days"] = days
    queued = [row for row in load_first_access() if listing_number(row) != number]
    queued.append(record)
    write_businesses([row for row in load_businesses() if listing_number(row) != number])
    drop_waiting(number)
    write_json(FIRST_ACCESS_PATH, queued)


def sign_nda(number: str) -> None:
    chosen = find_listing(
        number,
        (load_businesses(), load_saved(), load_first_access(), load_nda(), load_waiting()),
    )
    if chosen is None:
        raise KeyError(number)
    nda = [row for row in load_nda() if listing_number(row) != number]
    nda.append(public_row(chosen))
    write_businesses([row for row in load_businesses() if listing_number(row) != number])
    write_json(SAVED_PATH, [row for row in load_saved() if listing_number(row) != number])
    write_json(FIRST_ACCESS_PATH, [row for row in load_first_access() if listing_number(row) != number])
    drop_waiting(number)
    write_json(NDA_PATH, nda)


def waiting_inquiry(number: str) -> None:
    chosen = find_listing(
        number,
        (load_businesses(), load_saved(), load_first_access(), load_nda(), load_waiting()),
    )
    if chosen is None:
        raise KeyError(number)
    waiting = [row for row in load_waiting() if listing_number(row) != number]
    waiting.append(public_row(chosen))
    write_businesses([row for row in load_businesses() if listing_number(row) != number])
    write_json(SAVED_PATH, [row for row in load_saved() if listing_number(row) != number])
    write_json(FIRST_ACCESS_PATH, [row for row in load_first_access() if listing_number(row) != number])
    write_json(NDA_PATH, [row for row in load_nda() if listing_number(row) != number])
    write_json(WAITING_PATH, waiting)


def restore_listing(number: str) -> None:
    saved = load_saved()
    chosen = next((row for row in saved if listing_number(row) == number), None)
    if chosen is None:
        raise KeyError(number)
    deleted = [item for item in load_deleted() if item["listing_id"] != number]
    businesses = load_businesses()
    if not any(listing_number(row) == number for row in businesses):
        businesses.append(public_row(chosen))
    write_json(SAVED_PATH, [row for row in saved if listing_number(row) != number])
    write_deleted(deleted)
    write_businesses(businesses)


class Server(ThreadingHTTPServer):
    allow_reuse_address = False

    def server_bind(self) -> None:
        # Windows otherwise lets a second process listen on the same port.
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


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
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_error(404)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/run":
            self._run()
            return
        if path == "/api/save-filter":
            self._save_filter()
            return
        if path == "/api/load-filter":
            self._load_filter()
            return
        if path == "/api/delete-filter":
            self._delete_filter()
            return
        if path == "/api/rate":
            self._rate()
            return
        actions = {
            "/api/delete": delete_listing,
            "/api/delete-all": delete_all_review,
            "/api/save": save_listing,
            "/api/restore": restore_listing,
            "/api/first-access": first_access_listing,
            "/api/nda": sign_nda,
            "/api/waiting-inquiry": waiting_inquiry,
        }
        action = actions.get(path)
        if action is None:
            self.send_error(404)
            return
        try:
            payload = self._read_json()
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
            elif path == "/api/delete":
                delete_listing(number, clean_note(payload.get("note", "")))
            else:
                action(number)
        except KeyError:
            self._send_json({"error": "listing not found"}, status=404)
            return
        except (ValueError, json.JSONDecodeError) as error:
            self._send_json({"error": str(error)}, status=400)
            return
        self._send_json(state())

    def _rate(self) -> None:
        try:
            payload = self._read_json()
            number = str(payload.get("listing_id", "")).strip()
            if not number.isdigit():
                raise ValueError("listing_id must be the Flippa listing number")
            if "rating" not in payload:
                raise ValueError("rating must be a whole number from 1 to 5, or null to clear")
            rating = payload.get("rating")
            if rating is None:
                set_rating(number, None)
            elif isinstance(rating, bool) or not isinstance(rating, int) or not 1 <= rating <= 5:
                raise ValueError("rating must be a whole number from 1 to 5, or null to clear")
            else:
                set_rating(number, rating)
        except (ValueError, json.JSONDecodeError) as error:
            self._send_json({"error": str(error)}, status=400)
            return
        self._send_json(state())

    def _save_filter(self) -> None:
        try:
            name = save_filter_preset(self._read_json())
        except FilterError as error:
            self._send_json({"error": str(error)}, status=400)
            return
        except (ValueError, json.JSONDecodeError) as error:
            self._send_json({"error": str(error)}, status=400)
            return
        except OSError as error:
            self._send_json({"error": f"Could not save that filter: {error}"}, status=500)
            return
        self._send_json({"name": name, "saved_filters": list_saved_filters()})

    def _load_filter(self) -> None:
        try:
            payload = self._read_json()
            form = load_filter_preset(payload.get("name", ""))
        except KeyError:
            self._send_json({"error": "That saved filter was not found."}, status=404)
            return
        except FilterError as error:
            self._send_json({"error": str(error)}, status=400)
            return
        except (ValueError, json.JSONDecodeError) as error:
            self._send_json({"error": str(error)}, status=400)
            return
        except OSError as error:
            self._send_json({"error": f"Could not read that filter: {error}"}, status=500)
            return
        self._send_json({"form": form})

    def _delete_filter(self) -> None:
        try:
            payload = self._read_json()
            delete_filter_preset(payload.get("name", ""))
        except KeyError:
            self._send_json({"error": "That saved filter was not found."}, status=404)
            return
        except (ValueError, json.JSONDecodeError) as error:
            self._send_json({"error": str(error)}, status=400)
            return
        except OSError as error:
            self._send_json({"error": f"Could not delete that filter: {error}"}, status=500)
            return
        self._send_json({"saved_filters": list_saved_filters()})

    def _run(self) -> None:
        try:
            form = self._read_json()
            if FILTERS_PATH.is_file():
                read_filters(FILTERS_PATH)
            settings = settings_from_form(form)
        except FilterError as error:
            self._send_json({"error": str(error)}, status=400)
            return
        except (ValueError, json.JSONDecodeError) as error:
            self._send_json({"error": str(error)}, status=400)
            return
        if not _run_lock.acquire(blocking=False):
            self._send_json({"error": "A search is already running."}, status=409)
            return
        try:
            try:
                write_filters_file(FILTERS_PATH, settings)
            except OSError as error:
                self._send_json({"error": f"Could not write filters.txt: {error}"}, status=500)
                return
            try:
                skipped = excluded_listing_ids(OUTPUT)
                listings = scrape(settings, DEFAULT_DELAY, DEFAULT_TIMEOUT, skipped)
                write_outputs(listings, OUTPUT, settings)
            except RuntimeError as error:
                self._send_json(
                    {"error": f"Filters were saved. Import failed: {error}"},
                    status=502,
                )
                return
            except json.JSONDecodeError:
                self._send_json(
                    {"error": "Filters were saved. A file in output could not be read."},
                    status=500,
                )
                return
            except OSError as error:
                self._send_json(
                    {"error": f"Filters were saved. Import failed: {error}"},
                    status=500,
                )
                return
            payload = state()
            payload["imported"] = len(listings)
            payload["skipped"] = len(skipped)
            self._send_json(payload)
        finally:
            _run_lock.release()

    def log_message(self, format: str, *args) -> None:
        print(f"{self.address_string()} {format % args}")

    def handle_error(self) -> None:
        error = sys.exc_info()[1]
        if isinstance(error, (ConnectionError, TimeoutError)):
            return
        super().handle_error()

    def _read_json(self) -> dict:
        length_header = self.headers.get("Content-Length", "0")
        if not length_header.isdigit():
            raise ValueError("Content-Length must be a number")
        length = int(length_header)
        if length > MAX_BODY:
            raise ValueError("request is too large")
        raw = self.rfile.read(length).decode("utf-8") if length else "{}"
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("expected an object")
        return payload

    def _send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    SAVED_FILTERS.mkdir(parents=True, exist_ok=True)
    url, host, port = LISTEN_URL, LISTEN_HOST, LISTEN_PORT
    try:
        server = Server((host, port), Handler)
    except OSError as error:
        winerror = getattr(error, "winerror", None)
        if error.errno in {48, 98, 10048} or winerror == 10048:
            print(f"Port {port} is already in use.", flush=True)
            print(f"Another program is listening on {url}.", flush=True)
            print("This server will not close that program.", flush=True)
            print("Free the port, then start flippa-scraper again.", flush=True)
            sys.exit(1)
        raise
    print(f"Open {url}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
