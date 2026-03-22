"""Vercel serverless function: check prices for a single product on demand."""

import json
import os
import sys
from base64 import b64decode, b64encode
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.scrapers import get_scraper

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "").strip()
GITHUB_REPO = os.environ.get("GITHUB_REPO", "rvr8/price-monitor").strip()
DB_FILE_PATH = "docs/db.json"


def _github_headers():
    return {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _get_db_from_github():
    import httpx
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{DB_FILE_PATH}"
    resp = httpx.get(url, headers=_github_headers(), timeout=15)
    resp.raise_for_status()
    data = resp.json()
    content = b64decode(data["content"]).decode("utf-8")
    return json.loads(content), data["sha"]


def _put_db_to_github(db, sha, message):
    import httpx
    content = json.dumps(db, indent=2, ensure_ascii=False)
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{DB_FILE_PATH}"
    resp = httpx.put(
        url,
        headers=_github_headers(),
        json={
            "message": message,
            "content": b64encode(content.encode("utf-8")).decode("ascii"),
            "sha": sha,
        },
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        if not GITHUB_TOKEN:
            self._json_response(500, {"error": "Server not configured: missing GITHUB_TOKEN"})
            return

        try:
            content_length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(content_length)) if content_length else {}
            product_id = body.get("product_id", "").strip()

            if not product_id:
                self._json_response(400, {"error": "product_id is required"})
                return

            db, sha = _get_db_from_github()
            product = next((p for p in db["products"] if p["id"] == product_id), None)
            if not product:
                self._json_response(404, {"error": f"Product '{product_id}' not found"})
                return

            now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            checked = 0
            errors = 0

            for tracked in product["tracked_urls"]:
                url = tracked["url"]
                try:
                    scraper = get_scraper(url)
                    result = scraper.scrape(url)
                    if result.success:
                        db["price_history"].append({
                            "product_id": product_id,
                            "url": url,
                            "price": result.price,
                            "original_price": result.original_price,
                            "in_stock": result.in_stock,
                            "checked_at": now,
                        })
                        checked += 1
                except Exception:
                    errors += 1

            product["last_checked"] = now
            db["last_checked"] = now

            # Commit with retry on SHA conflict
            price_records = [h for h in db["price_history"] if h.get("checked_at") == now and h.get("product_id") == product_id]
            committed = False
            for attempt in range(3):
                try:
                    _put_db_to_github(db, sha, f"check: {product['name']} (manual)")
                    committed = True
                    break
                except Exception as e:
                    if attempt < 2:
                        import time
                        time.sleep(2)
                        try:
                            db, sha = _get_db_from_github()
                            product = next((p for p in db["products"] if p["id"] == product_id), None)
                            if product:
                                product["last_checked"] = now
                                db["price_history"].extend(price_records)
                                db["last_checked"] = now
                        except Exception:
                            pass
                    else:
                        self._json_response(500, {
                            "error": f"Failed to save after 3 attempts: {str(e)[:100]}",
                            "prices_checked": checked,
                        })
                        return

            self._json_response(200, {
                "status": "checked",
                "product_id": product_id,
                "prices_checked": checked,
                "errors": errors,
                "saved": committed,
            })

        except Exception as e:
            self._json_response(500, {"error": str(e)})

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors_headers()
        self.end_headers()

    def _json_response(self, status, data):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self._cors_headers()
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def _cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
