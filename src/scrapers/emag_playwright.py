"""eMAG.ro scraper using Playwright headless browser.

eMAG blocks simple HTTP requests (403/captcha). Playwright renders the page
in a real Chromium browser, bypassing bot detection.

NOTE: This scraper is SLOW (~5-10s per page) and should only be used in
GitHub Actions (check_prices.py), NOT in Vercel serverless functions.
"""

import json
from typing import Optional

from src.scrapers.base import BaseScraper, ScrapeResult, SearchResult


def _get_page_html(url: str, wait_selector: str = None, timeout: int = 30000) -> str:
    """Launch headless Chromium, navigate to URL, return rendered HTML."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        )
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            locale="ro-RO",
        )

        # Disable webdriver detection
        context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        """)

        page = context.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=timeout)

            # Wait for Cloudflare challenge to resolve (if present)
            page.wait_for_timeout(3000)

            # Wait for specific selector if provided
            if wait_selector:
                try:
                    page.wait_for_selector(wait_selector, timeout=10000)
                except Exception:
                    pass  # Selector didn't appear — page might still have useful data

            html = page.content()
        finally:
            browser.close()

    return html


class EmagPlaywrightScraper(BaseScraper):
    """
    eMAG.ro scraper using Playwright headless Chromium.
    Search: renders search results page, extracts product cards.
    Scrape: renders product page, extracts JSON-LD or HTML data.
    """

    RETAILER_NAME = "eMAG"
    SEARCH_URL = "https://www.emag.ro/search/{query}"

    def search(self, query: str, max_results: int = 10) -> list[SearchResult]:
        """Search eMAG by rendering the search results page."""
        url = self.SEARCH_URL.format(query=query.replace(" ", "+"))
        try:
            html = _get_page_html(url, wait_selector=".card-item")
        except Exception:
            return []

        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "lxml")
        results = []

        for card in soup.select(".card-item")[:max_results]:
            # Product name + URL (eMAG uses card-v2-title or product-title)
            title_el = card.select_one("a.card-v2-title, .product-title a, a.product-title")
            if not title_el:
                continue
            name = title_el.get_text(strip=True)
            product_url = title_el.get("href", "")
            if not name or not product_url:
                continue
            if not product_url.startswith("http"):
                product_url = "https://www.emag.ro" + product_url

            # Price
            price = None
            price_el = card.select_one(".product-new-price")
            if price_el:
                price_text = price_el.get_text(strip=True)
                price = self.parse_romanian_price(price_text)

            # Image
            image_url = None
            img_el = card.select_one("img.lozad, img[data-src], img.product-image")
            if img_el:
                image_url = img_el.get("data-src") or img_el.get("src")

            # Stock
            in_stock = True
            oos = card.select_one(".out-of-stock, .product-stock-status-oos")
            if oos:
                in_stock = False

            if price:
                results.append(SearchResult(
                    name=name,
                    url=product_url,
                    retailer=self.RETAILER_NAME,
                    price=price,
                    in_stock=in_stock,
                    image_url=image_url,
                ))

        return results

    def scrape(self, url: str) -> ScrapeResult:
        """Scrape an eMAG product page using Playwright."""
        try:
            html = _get_page_html(url, wait_selector=".product-new-price")
        except Exception as e:
            return ScrapeResult(error=f"Playwright fetch failed: {e}")

        result = ScrapeResult()
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "lxml")

        # Try JSON-LD first
        jsonld = self._extract_jsonld(soup)
        if jsonld:
            result.product_name = jsonld.get("name")
            result.image_url = jsonld.get("image")
            if isinstance(result.image_url, list):
                result.image_url = result.image_url[0] if result.image_url else None

            offers = jsonld.get("offers", {})
            if isinstance(offers, list):
                offers = offers[0] if offers else {}

            try:
                result.price = float(offers.get("price", 0)) or None
            except (ValueError, TypeError):
                result.price = None

            result.currency = offers.get("priceCurrency", "RON")
            avail = offers.get("availability", "")
            if avail:
                result.in_stock = "InStock" in avail

        # Fallback: HTML
        if not result.price:
            price_el = soup.select_one(".product-new-price")
            if price_el:
                result.price = self.parse_romanian_price(price_el.get_text())

        if not result.product_name:
            h1 = soup.select_one("h1.page-title, h1")
            if h1:
                result.product_name = h1.get_text(strip=True)

        if not result.image_url:
            og = soup.find("meta", property="og:image")
            if og:
                result.image_url = og.get("content")

        # Original price
        old_el = soup.select_one(".product-old-price")
        if old_el:
            result.original_price = self.parse_romanian_price(old_el.get_text())

        if result.original_price and result.price and abs(result.original_price - result.price) < 1:
            result.original_price = None

        # Stock
        if not result.in_stock:
            add_cart = soup.select_one(".yeahIWantIt, .add-to-cart-button")
            if add_cart:
                result.in_stock = True
            oos = soup.select_one(".out-of-stock-box, .product-stock-status-oos")
            if oos:
                result.in_stock = False

        if not result.price:
            result.error = "Could not extract price"

        return result

    def _extract_jsonld(self, soup) -> Optional[dict]:
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string or "")
                if isinstance(data, list):
                    for item in data:
                        if item.get("@type") == "Product":
                            return item
                elif data.get("@type") == "Product":
                    return data
            except json.JSONDecodeError:
                continue
        return None
