"""Vercel serverless function: product actions (delete, archive, restore)."""

import json
import os
from base64 import b64decode, b64encode
from http.server import BaseHTTPRequestHandler

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

            action = body.get("action", "").strip()
            product_id = body.get("product_id", "").strip()

            if not product_id:
                self._json_response(400, {"error": "product_id is required"})
                return
            if action not in ("delete", "archive", "restore"):
                self._json_response(400, {"error": "action must be 'delete', 'archive', or 'restore'"})
                return

            db, sha = _get_db_from_github()

            # Ensure archived_products list exists
            if "archived_products" not in db:
                db["archived_products"] = []

            if action == "archive":
                product = next((p for p in db["products"] if p["id"] == product_id), None)
                if not product:
                    self._json_response(404, {"error": f"Product '{product_id}' not found"})
                    return
                # Move to archived
                db["products"] = [p for p in db["products"] if p["id"] != product_id]
                product["archived_at"] = __import__("datetime").datetime.now(
                    __import__("datetime").timezone.utc
                ).strftime("%Y-%m-%dT%H:%M:%SZ")
                db["archived_products"].append(product)
                _put_db_to_github(db, sha, f"archive: {product['name']}")
                self._json_response(200, {"status": "archived", "product_id": product_id})

            elif action == "restore":
                product = next((p for p in db["archived_products"] if p["id"] == product_id), None)
                if not product:
                    self._json_response(404, {"error": f"Archived product '{product_id}' not found"})
                    return
                # Move back to active
                db["archived_products"] = [p for p in db["archived_products"] if p["id"] != product_id]
                product.pop("archived_at", None)
                db["products"].append(product)
                _put_db_to_github(db, sha, f"restore: {product['name']}")
                self._json_response(200, {"status": "restored", "product_id": product_id})

            elif action == "delete":
                # Check both active and archived
                found_in = None
                for lst_name in ("products", "archived_products"):
                    if any(p["id"] == product_id for p in db.get(lst_name, [])):
                        found_in = lst_name
                        break
                if not found_in:
                    self._json_response(404, {"error": f"Product '{product_id}' not found"})
                    return

                product_name = next(p["name"] for p in db[found_in] if p["id"] == product_id)
                db[found_in] = [p for p in db[found_in] if p["id"] != product_id]
                # Also remove price history
                db["price_history"] = [p for p in db["price_history"] if p["product_id"] != product_id]
                _put_db_to_github(db, sha, f"delete: {product_name}")
                self._json_response(200, {"status": "deleted", "product_id": product_id})

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
