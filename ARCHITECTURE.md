# Price Monitor — Architecture

## Goal
Monitor prices and availability of baby/stroller products across Romanian e-commerce sites.
Alert the user when prices drop below a threshold or items come back in stock.

**Reference product:** Cybex Balios S Lux stroller
**Target market:** Romania (Brasov/Bucharest)

---

## Tech Stack
- **Language:** Python 3.12
- **Hosting:** Vercel (static frontend + Python serverless functions)
- **Frontend:** Tailwind CSS (CDN) + vanilla JS + Chart.js
- **Database:** JSON file (`docs/db.json`) — version-controlled in Git
- **Scraping:** httpx + BeautifulSoup4 + lxml
- **Scheduling:** GitHub Actions (daily cron at 08:17 UTC)
- **Notifications:** Telegram API
- **CLI:** `manage.py` for local product management

## Supported Retailers

| Retailer | Domain | Scraping Method | Search | Status |
|---|---|---|---|---|
| eMAG | emag.ro | JS regex (EM.* vars) + meta tags | Blocked | Built |
| BabyNeeds | babyneeds.ro | JSON-LD + JS var fallback | Yes | Built |
| ToysForKids | toysforkids.ro | JSON-LD + HTML fallback | Yes | Built |

## Data Model (db.json)

```
Product (1) ──→ (N) TrackedURL
   │
   └──→ (N) Alert

PriceHistory entries reference product_id + url
```

- **Product**: id, name, image_url, tracked_urls[], alerts[]
- **TrackedURL**: url, retailer, variant_name (embedded in Product)
- **PriceHistory**: product_id, url, price, original_price, in_stock, checked_at
- **Alert**: target_price, triggered, triggered_at (embedded in Product)

## Project Structure

```
price-monitor/
├── ARCHITECTURE.md              # This file
├── CLAUDE.md                    # Project-specific Claude rules
├── vercel.json                  # Vercel config: Python runtime, rewrites
├── requirements.txt             # httpx, beautifulsoup4, lxml
├── .env.example                 # Environment template
├── .gitignore
├── check_prices.py              # GitHub Actions entry point (daily price check)
├── manage.py                    # CLI: search, track, track-group, alert, list
├── api/                         # Vercel Python serverless functions
│   ├── search.py                #   POST /api/search — search retailers live
│   └── track.py                 #   POST /api/track — add product via GitHub API
├── public/                      # Vercel static files (served at /)
│   ├── index.html               #   Dashboard: product grid, add product flow
│   ├── product.html             #   Product detail: chart, where to buy, alerts
│   └── db.json                  #   Copy of docs/db.json (built at deploy time)
├── docs/                        # Canonical data directory
│   ├── db.json                  #   The database (GitHub Actions writes here)
│   ├── index.html               #   Legacy GitHub Pages dashboard (kept for compat)
│   └── product.html             #   Legacy product page
├── src/
│   ├── __init__.py
│   └── scrapers/
│       ├── __init__.py          #   Registry: get_scraper(), search_all()
│       ├── base.py              #   BaseScraper, ScrapeResult, SearchResult, normalize_product_name()
│       ├── emag.py              #   eMAG.ro scraper
│       ├── babyneeds.py         #   BabyNeeds.ro scraper
│       └── toysforkids.py       #   ToysForKids.ro scraper
└── .github/workflows/
    ├── check-prices.yml         #   Daily cron: scrape all URLs, commit db.json
    ├── add-product.yml          #   Manual workflow: search/track via GitHub Actions
    └── on-issue.yml             #   Auto-process [ADD]/[RETAILER] issues
```

## Key Design Decisions

1. **Vercel for hosting** — free tier (100GB bandwidth, 60s serverless functions), auto-deploy on push to main
2. **Two-step search → track** — user searches, sees grouped results, picks which group to track. Better UX than blind auto-track.
3. **Server-side GitHub token** — stored as Vercel env var, never exposed to browser. User needs no tokens.
4. **db.json stays in docs/** — GitHub Actions writes here. Vercel copies to `public/` at build time. Single source of truth.
5. **Python serverless** — Vercel supports Python natively. Reuses existing scrapers with zero code changes.
6. **Color-agnostic grouping** — `normalize_product_name()` strips color/variant words, groups same product across retailers.
7. **Auto-detect retailer from URL** — user pastes a URL, system detects retailer by domain.
8. **JSON file database** — simple, version-controlled, good enough for 1-10 products. No server needed.

## Data Flow

### Adding a Product (via dashboard)
```
User types "Cybex Eezy S Twist" → clicks Search
  → POST /api/search {query}
  → api/search.py calls search_all() → scrapes ToysForKids + BabyNeeds live
  → Returns grouped results (5-15 seconds)
User clicks "Track" on desired group
  → POST /api/track {name, items, image_url}
  → api/track.py: GET docs/db.json from GitHub → add product → PUT docs/db.json
  → Also scrapes initial prices for all URLs
  → Commit triggers Vercel auto-redeploy
```

### Daily Price Check
```
GitHub Actions (08:17 UTC daily)
  → check_prices.py: load db.json, scrape all URLs, append price records
  → Commit updated db.json to docs/
  → Vercel auto-redeploys with new data
  → Check alerts: if price ≤ target → send Telegram notification
```

## Environment Variables

### Vercel (server-side)
- `GITHUB_TOKEN` — GitHub PAT with `repo` scope (for committing db.json)
- `GITHUB_REPO` — `rvr8/price-monitor`

### GitHub Actions Secrets
- `TELEGRAM_BOT_TOKEN` — Telegram bot token for alerts
- `TELEGRAM_CHAT_ID` — Telegram chat ID for alert messages

## Notification Rules

An alert triggers when:
- Price drops below target_price AND alert is active AND not already triggered
- After triggering, alert.triggered_at is set (won't re-trigger until reset)
