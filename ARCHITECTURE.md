# Price Monitor — Architecture

## Goal
Monitor prices and availability of baby/stroller products across Romanian e-commerce sites.
Alert the user when prices drop below a threshold or items come back in stock.

**Reference product:** Cybex Balios S Lux stroller
**Target market:** Romania (Brasov/Bucharest)

---

## Tech Stack
- **Language:** Python 3.11+
- **Web framework:** FastAPI + Jinja2 templates
- **Frontend:** Tailwind CSS (CDN) + htmx + Chart.js
- **Database:** SQLite via SQLAlchemy (sync)
- **Scraping:** httpx + BeautifulSoup4 + lxml
- **Scheduling:** APScheduler (BackgroundScheduler)
- **Config:** pydantic-settings + .env file
- **Notifications:** Email (SMTP)

## Supported Retailers

| Retailer | Domain | Scraping Method | Status |
|---|---|---|---|
| eMAG | emag.ro | JS regex (EM.* vars) + meta tags | Built |
| BabyNeeds | babyneeds.ro | HTML (data-price attr) + JS var | Built |
| ToysForKids | toysforkids.ro | JSON-LD structured data | Built |

## Data Model

```
Product (1) ──→ (N) TrackedURL (1) ──→ (N) PriceRecord
   │
   └──→ (N) Alert
```

- **Product**: name, category, image_url
- **TrackedURL**: retailer, url, last_checked_at, last_error (belongs to Product)
- **PriceRecord**: price, original_price, currency, in_stock, checked_at (belongs to TrackedURL)
- **Alert**: target_price, notify_email, active, triggered_at (belongs to Product)

## Project Structure

```
price-monitor/
├── ARCHITECTURE.md          # This file
├── requirements.txt         # Python dependencies
├── .env.example             # Environment template
├── .gitignore
├── run.py                   # Entry point (serve, init, check)
└── src/
    ├── __init__.py
    ├── config.py            # Settings (pydantic-settings)
    ├── models.py            # SQLAlchemy models + DB setup
    ├── checker.py           # Orchestrates scraping all tracked URLs
    ├── notifier.py          # Email notification sender
    ├── scrapers/
    │   ├── __init__.py      # Registry: URL → scraper auto-detection
    │   ├── base.py          # BaseScraper + ScrapeResult dataclass
    │   ├── emag.py          # eMAG.ro scraper
    │   ├── babyneeds.py     # BabyNeeds.ro scraper
    │   └── toysforkids.py   # ToysForKids.ro scraper
    ├── web/
    │   ├── __init__.py
    │   ├── app.py           # FastAPI app setup + lifespan (scheduler)
    │   ├── routes.py        # API + page routes
    │   ├── static/
    │   │   ├── app.js       # htmx interactions + chart init
    │   │   └── style.css    # Custom styles (Tailwind via CDN)
    │   └── templates/
    │       ├── base.html    # Layout: Tailwind CDN, nav, footer
    │       ├── index.html   # Dashboard: all products, best prices
    │       ├── product.html # Product detail: price comparison, chart
    │       └── add.html     # Add product: paste URL form
```

## Key Design Decisions

1. **Auto-detect retailer from URL** — user pastes a URL, system detects retailer by domain. No "scraper" dropdown exposed.
2. **Tailwind CSS via CDN** — modern look without build tooling. Pico CSS was too plain (user rejected v1).
3. **SQLite** — simple, no server needed, file-based. Good enough for personal use.
4. **Sync SQLAlchemy** — async is overkill for this scale. Background scheduler runs sync anyway.
5. **APScheduler** — runs inside FastAPI lifespan, checks all URLs on interval (default 4h).
6. **htmx** — dynamic UI without writing a SPA. Forms submit via htmx, partial page updates.

## User Workflow

1. User opens dashboard → sees all tracked products with current best price
2. Clicks "Add Product" → pastes a URL → system auto-detects retailer, scrapes product info, creates product
3. Can add multiple URLs for same product (different retailers)
4. Dashboard shows price comparison across retailers
5. Product detail page shows price history chart + all retailer prices
6. User sets price alert → gets email when price drops below target

## Notification Rules

An alert triggers when:
- Price drops below target_price AND alert is active AND not already triggered
- After triggering, alert.triggered_at is set (won't re-trigger until reset)
- Back-in-stock notifications: when in_stock changes from False to True

## Browser Testing

- Use **Microsoft Edge** for visible browser tests (not Chrome, to avoid disrupting user sessions)
- Chrome as fallback only when Edge unavailable
