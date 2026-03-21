import re
import json
from typing import Optional

from bs4 import BeautifulSoup

from src.scrapers.base import BaseScraper, ScrapeResult, SearchResult


class BabyNeedsScraper(BaseScraper):
    """
    BabyNeeds.ro scraper.
    Primary: JSON-LD structured data (schema.org Product).
    Fallback: regex on JS var avanticart.product fields, HTML selectors.
    Search: Custom search endpoint with .product-box cards.
    """

    RETAILER_NAME = "BabyNeeds"
    SEARCH_URL = "https://www.babyneeds.ro/index.php5?module=Frontend&action=search&search_value={query}"

    def search(self, query: str, max_results: int = 10) -> list[SearchResult]:
        """Search BabyNeeds.ro for products matching query."""
        url = self.SEARCH_URL.format(query=query.replace(" ", "+"))
        try:
            html = self.fetch(url)
        except Exception:
            return []

        soup = BeautifulSoup(html, "lxml")
        results = []

        items = soup.select(".product-box")
        for item in items[:max_results]:
            # Name + URL from the product link
            link = item.select_one("a.productImage[href]")
            if not link:
                continue
            name = link.get("title", "")
            product_url = link.get("href", "")
            if not name or not product_url:
                continue

            # Price from div.productPrice[price] attribute
            price = None
            price_el = item.select_one("div.productPrice[price]")
            if price_el:
                try:
                    price = float(price_el.get("price", "0"))
                except ValueError:
                    pass

            # Image (lazy-loaded)
            img_el = item.select_one("img.first-show")
            image_url = None
            if img_el:
                image_url = img_el.get("data-src") or img_el.get("src")

            # Stock
            in_stock = True
            stock_el = item.select_one(".stockAvability, .stock-status")
            if stock_el:
                text = stock_el.get_text(strip=True).lower()
                if "indisponibil" in text or "epuizat" in text:
                    in_stock = False

            results.append(SearchResult(
                name=name,
                url=product_url,
                retailer=self.RETAILER_NAME,
                price=price if price > 0 else None,
                in_stock=in_stock,
                image_url=image_url,
            ))

        return results

    def scrape(self, url: str) -> ScrapeResult:
        try:
            html = self.fetch(url)
        except Exception as e:
            return ScrapeResult(error=f"Fetch failed: {e}")

        result = ScrapeResult()
        soup = BeautifulSoup(html, "lxml")

        # Try JSON-LD first (most reliable)
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
            result.in_stock = "InStock" in avail

        # Fallback: regex on JS fields (handles large avanticart object)
        if not result.price:
            match = re.search(r'"product_price"\s*:\s*"?([\d.]+)', html)
            if match:
                try:
                    result.price = float(match.group(1))
                except ValueError:
                    pass

        if not result.product_name:
            result.product_name = self._extract_name(soup)

        if not result.image_url:
            result.image_url = self._extract_image(soup)

        # Original price
        if not result.original_price:
            result.original_price = self._extract_old_price(html)

        # If original equals current, clear it
        if result.original_price and result.price and abs(result.original_price - result.price) < 0.01:
            result.original_price = None

        # Stock fallback
        if not result.in_stock and not jsonld:
            result.in_stock = self._check_stock(soup, html)

        if not result.price:
            result.error = "Could not extract price"

        return result

    def _extract_jsonld(self, soup: BeautifulSoup) -> Optional[dict]:
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

    def _extract_name(self, soup: BeautifulSoup) -> Optional[str]:
        h1 = soup.find("h1", class_="page-title")
        if h1:
            return h1.get_text(strip=True)
        title = soup.find("title")
        if title:
            return title.get_text(strip=True).split(" - ")[0].strip()
        return None

    def _extract_image(self, soup: BeautifulSoup) -> Optional[str]:
        meta = soup.find("meta", property="og:image")
        if meta:
            return meta.get("content")
        return None

    def _extract_old_price(self, html: str) -> Optional[float]:
        match = re.search(r'"product_price_old"\s*:\s*"?([\d.]+)', html)
        if match:
            try:
                return float(match.group(1))
            except ValueError:
                pass
        return None

    def _check_stock(self, soup: BeautifulSoup, html: str) -> bool:
        # JS variable
        match = re.search(r'"product_stock"\s*:\s*"?(\d+)', html)
        if match:
            return int(match.group(1)) > 0
        # HTML text
        stock_div = soup.select_one("div.stockAvability, div.stock-availability, .availability")
        if stock_div:
            text = stock_div.get_text(strip=True).lower()
            if any(kw in text for kw in ("in stoc", "în stoc", "disponibil")):
                return True
        return False
