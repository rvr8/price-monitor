"""Vercel serverless function: track a product group (add to db.json via GitHub API)."""

import json
import os
import re
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
    """Fetch db.json from GitHub, returns (db_dict, sha)."""
    import httpx

    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{DB_FILE_PATH}"
    resp = httpx.get(url, headers=_github_headers(), timeout=15)
    resp.raise_for_status()
    data = resp.json()
    content = b64decode(data["content"]).decode("utf-8")
    return json.loads(content), data["sha"]


def _put_db_to_github(db, sha, message):
    """Commit updated db.json to GitHub."""
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


def _check_prices_for_urls(tracked_urls, product_id):
    """Scrape initial prices for newly tracked URLs."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    records = []
    for tracked in tracked_urls:
        try:
            scraper = get_scraper(tracked["url"])
            result = scraper.scrape(tracked["url"])
            if result.success:
                records.append({
                    "product_id": product_id,
                    "url": tracked["url"],
                    "price": result.price,
                    "original_price": result.original_price,
                    "in_stock": result.in_stock,
                    "checked_at": now,
                })
        except Exception:
            continue
    return records


def _auto_discover_urls(product_name, existing_tracked):
    """Search all retailers for the same product and return new URLs to track."""
    from src.scrapers import SEARCHABLE_SCRAPERS, normalize_product_name

    # Retailers we already have URLs for
    existing_retailers = {t["retailer"] for t in existing_tracked}
    normalized = normalize_product_name(product_name).lower()
    query_words = [w for w in normalized.split() if len(w) > 2]

    discovered = []
    for scraper_class in SEARCHABLE_SCRAPERS:
        scraper = scraper_class()
        if scraper.RETAILER_NAME in existing_retailers:
            continue  # Already have this retailer
        try:
            results = scraper.search(product_name, max_results=5)
            for r in results:
                # Check if the result matches our product (at least 2 query words in name)
                name_lower = r.name.lower()
                matches = sum(1 for w in query_words if w in name_lower)
                if matches >= min(2, len(query_words)) and r.price:
                    discovered.append({
                        "url": r.url,
                        "retailer": r.retailer,
                        "variant_name": r.name[:50],
                    })
                    break  # One URL per retailer is enough
        except Exception:
            continue

    return discovered


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        if not GITHUB_TOKEN:
            self._json_response(500, {"error": "Server not configured: missing GITHUB_TOKEN"})
            return

        try:
            content_length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(content_length)) if content_length else {}

            name = body.get("name", "").strip()
            items = body.get("items", [])
            image_url = body.get("image_url")

            if not name:
                self._json_response(400, {"error": "Product name is required"})
                return
            if not items:
                self._json_response(400, {"error": "At least one URL is required"})
                return

            # Generate product ID from name
            product_id = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")

            # Build tracked_urls list
            tracked_urls = []
            for item in items:
                tracked_urls.append({
                    "url": item["url"],
                    "retailer": item["retailer"],
                    "variant_name": item.get("variant_name", item.get("name", ""))[:50],
                })

            # Fetch current db.json from GitHub
            db, sha = _get_db_from_github()

            # Check if product already exists
            existing = next((p for p in db["products"] if p["id"] == product_id), None)
            if existing:
                # Add new URLs that aren't already tracked
                existing_urls = {u["url"] for u in existing["tracked_urls"]}
                new_urls = [u for u in tracked_urls if u["url"] not in existing_urls]
                if not new_urls:
                    self._json_response(200, {
                        "status": "already_tracked",
                        "product_id": product_id,
                        "message": f"'{name}' is already fully tracked",
                    })
                    return
                existing["tracked_urls"].extend(new_urls)
                if image_url and not existing.get("image_url"):
                    existing["image_url"] = image_url
                tracked_urls = new_urls  # Only check new URLs
            else:
                db["products"].append({
                    "id": product_id,
                    "name": name,
                    "image_url": image_url,
                    "tracked_urls": tracked_urls,
                    "alerts": [],
                })

            # Auto-discover: search OTHER retailers for the same product
            auto_urls = _auto_discover_urls(name, tracked_urls)
            if auto_urls:
                # Add to product (existing or new)
                product_obj = existing or db["products"][-1]
                existing_url_set = {u["url"] for u in product_obj["tracked_urls"]}
                for au in auto_urls:
                    if au["url"] not in existing_url_set:
                        product_obj["tracked_urls"].append(au)
                        tracked_urls.append(au)
                        existing_url_set.add(au["url"])

            # Scrape initial prices for ALL new URLs (including auto-discovered)
            price_records = _check_prices_for_urls(tracked_urls, product_id)
            db["price_history"].extend(price_records)
            db["last_checked"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

            # Commit to GitHub
            _put_db_to_github(db, sha, f"track: {name} ({len(tracked_urls)} URLs)")

            self._json_response(200, {
                "status": "tracked",
                "product_id": product_id,
                "urls_added": len(tracked_urls),
                "prices_found": len(price_records),
                "auto_discovered": len(auto_urls) if auto_urls else 0,
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
