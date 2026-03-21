"""Price checker — run by GitHub Actions on schedule.
Reads data/db.json, scrapes all tracked URLs, appends price records, sends alerts."""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

# Add project root to path so scrapers can be imported
import sys
sys.path.insert(0, str(Path(__file__).parent))

from src.scrapers import get_scraper, detect_retailer

DB_PATH = Path(__file__).parent / "docs" / "db.json"


def load_db():
    with open(DB_PATH) as f:
        return json.load(f)


def save_db(db):
    with open(DB_PATH, "w") as f:
        json.dump(db, f, indent=2, ensure_ascii=False)


def check_all(db):
    """Scrape all tracked URLs and append price records."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    checked = 0
    errors = 0

    for product in db["products"]:
        for tracked in product["tracked_urls"]:
            url = tracked["url"]
            try:
                scraper = get_scraper(url)
                result = scraper.scrape(url)
                if result.success:
                    db["price_history"].append({
                        "product_id": product["id"],
                        "url": url,
                        "price": result.price,
                        "original_price": result.original_price,
                        "in_stock": result.in_stock,
                        "checked_at": now,
                    })
                    checked += 1
                    print(f"  OK: {tracked['retailer']} — {result.price} Lei ({'in stock' if result.in_stock else 'out of stock'})")
                else:
                    errors += 1
                    print(f"  ERR: {tracked['retailer']} — {result.error}")
            except Exception as e:
                errors += 1
                print(f"  ERR: {url} — {e}")

    db["last_checked"] = now
    return checked, errors


def check_alerts(db):
    """Check if any alerts should fire."""
    telegram_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    telegram_chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")

    if not telegram_token or not telegram_chat_id:
        return

    for product in db["products"]:
        if not product.get("alerts"):
            continue

        # Find latest price for this product
        product_prices = [
            p for p in db["price_history"]
            if p["product_id"] == product["id"]
        ]
        if not product_prices:
            continue

        latest_prices = {}
        for p in product_prices:
            latest_prices[p["url"]] = p  # last one wins (sorted by time)

        best_price = min(p["price"] for p in latest_prices.values())

        for alert in product["alerts"]:
            if alert.get("triggered"):
                continue
            if best_price <= alert["target_price"]:
                _send_telegram(
                    telegram_token,
                    alert.get("telegram_chat_id", telegram_chat_id),
                    product["name"],
                    best_price,
                    alert["target_price"],
                )
                alert["triggered"] = True
                alert["triggered_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _send_telegram(token, chat_id, product_name, price, target):
    """Send Telegram alert."""
    import httpx
    text = (
        f"*Price Alert\\!*\n\n"
        f"*{_esc(product_name)}*\n"
        f"Price: *{price:.0f} Lei*\n"
        f"Your target: {target:.0f} Lei\n"
    )
    try:
        httpx.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "MarkdownV2"},
            timeout=10,
        )
        print(f"  ALERT: Sent Telegram — {product_name} at {price} Lei")
    except Exception as e:
        print(f"  ALERT ERR: {e}")


def _esc(text):
    for ch in r"_*[]()~`>#+-=|{}.!":
        text = text.replace(ch, f"\\{ch}")
    return text


if __name__ == "__main__":
    print(f"[Price Monitor] Loading database...")
    db = load_db()
    print(f"[Price Monitor] {len(db['products'])} products to check")

    checked, errors = check_all(db)
    print(f"[Price Monitor] Checked: {checked} OK, {errors} errors")

    check_alerts(db)

    save_db(db)
    print(f"[Price Monitor] Database saved")
