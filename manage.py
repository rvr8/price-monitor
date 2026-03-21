"""CLI to manage tracked products. Run locally to add/remove products."""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

DB_PATH = Path(__file__).parent / "docs" / "db.json"


def load_db():
    if not DB_PATH.exists():
        return {"products": [], "price_history": [], "last_checked": ""}
    with open(DB_PATH) as f:
        return json.load(f)


def save_db(db):
    DB_PATH.parent.mkdir(exist_ok=True)
    with open(DB_PATH, "w") as f:
        json.dump(db, f, indent=2, ensure_ascii=False)


def cmd_search(query):
    from src.scrapers import search_all
    print(f"Searching for '{query}'...")
    groups = search_all(query)
    if not groups:
        print("No results found.")
        return
    for i, g in enumerate(groups):
        print(f"\n[{i+1}] {g.normalized_name}")
        print(f"    {g.count} variants, {g.best_price:.0f}-{g.max_price:.0f} Lei, {g.in_stock_count} in stock")
        for item in g.items:
            stock = "In stock" if item.in_stock else "Out of stock"
            print(f"      {item.retailer}: {item.price:.0f} Lei ({stock}) — {item.url}")


def cmd_track(args):
    if len(args) < 2:
        print("Usage: python manage.py track <product_name> <url1> [url2] ...")
        return
    name = args[0]
    urls = args[1:]
    db = load_db()

    product_id = re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')

    # Check if product already exists
    existing = next((p for p in db["products"] if p["id"] == product_id), None)
    if existing:
        print(f"Product '{name}' already exists. Adding new URLs...")
        existing_urls = {u["url"] for u in existing["tracked_urls"]}
        for url in urls:
            if url in existing_urls:
                print(f"  Skipped (already tracked): {url}")
                continue
            from src.scrapers import detect_retailer
            retailer = detect_retailer(url)
            slug = url.rstrip("/").split("/")[-1].replace(".html", "").replace("-", " ")
            existing["tracked_urls"].append({
                "url": url,
                "retailer": retailer,
                "variant_name": slug[:50],
            })
            print(f"  Added: {retailer} — {url}")
    else:
        from src.scrapers import detect_retailer
        tracked = []
        for url in urls:
            retailer = detect_retailer(url)
            slug = url.rstrip("/").split("/")[-1].replace(".html", "").replace("-", " ")
            tracked.append({
                "url": url,
                "retailer": retailer,
                "variant_name": slug[:50],
            })
            print(f"  Added: {retailer} — {url}")

        db["products"].append({
            "id": product_id,
            "name": name,
            "image_url": None,
            "tracked_urls": tracked,
            "alerts": [],
        })
        print(f"Created product '{name}' with {len(tracked)} URLs")

    save_db(db)
    print("Saved.")


def cmd_track_group(args):
    """Track all URLs from a search group by group number."""
    if len(args) < 2:
        print("Usage: python manage.py track-group <search_query> <group_number>")
        return
    query = args[0]
    group_num = int(args[1])

    from src.scrapers import search_all
    groups = search_all(query)
    if group_num < 1 or group_num > len(groups):
        print(f"Invalid group number. Found {len(groups)} groups.")
        return

    group = groups[group_num - 1]
    urls = [item.url for item in group.items]
    print(f"Tracking '{group.normalized_name}' with {len(urls)} variants...")
    cmd_track([group.normalized_name] + urls)


def cmd_alert(args):
    if len(args) < 2:
        print("Usage: python manage.py alert <product_id> <target_price>")
        return
    product_id = args[0]
    target_price = float(args[1])
    db = load_db()

    product = next((p for p in db["products"] if p["id"] == product_id), None)
    if not product:
        print(f"Product '{product_id}' not found. Available:")
        for p in db["products"]:
            print(f"  {p['id']}: {p['name']}")
        return

    product["alerts"].append({
        "target_price": target_price,
        "triggered": False,
    })
    save_db(db)
    print(f"Alert set: notify when {product['name']} drops below {target_price:.0f} Lei")


def cmd_list():
    db = load_db()
    if not db["products"]:
        print("No products tracked.")
        return
    print(f"Last checked: {db.get('last_checked', 'never')}\n")
    for p in db["products"]:
        # Find latest prices
        prices = [h for h in db["price_history"] if h["product_id"] == p["id"]]
        latest_by_url = {}
        for h in prices:
            latest_by_url[h["url"]] = h
        best = min((h["price"] for h in latest_by_url.values()), default=None)
        print(f"[{p['id']}] {p['name']}")
        print(f"  URLs: {len(p['tracked_urls'])}, Best price: {best:.0f} Lei" if best else f"  URLs: {len(p['tracked_urls'])}, No price data")
        print(f"  Alerts: {len(p.get('alerts', []))}")


def main():
    if len(sys.argv) < 2:
        print("Usage: python manage.py <command>")
        print("Commands:")
        print("  search <query>          — Search retailers for products")
        print("  track <name> <urls...>  — Track a product with given URLs")
        print("  track-group <query> <#> — Search and track group by number")
        print("  alert <product_id> <$>  — Set price alert")
        print("  list                    — List tracked products")
        return

    cmd = sys.argv[1]
    args = sys.argv[2:]

    if cmd == "search":
        cmd_search(" ".join(args))
    elif cmd == "track":
        cmd_track(args)
    elif cmd == "track-group":
        cmd_track_group(args)
    elif cmd == "alert":
        cmd_alert(args)
    elif cmd == "list":
        cmd_list()
    else:
        print(f"Unknown command: {cmd}")


if __name__ == "__main__":
    main()
