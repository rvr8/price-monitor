import re
from dataclasses import dataclass, field
from typing import Optional

import httpx

# Color/variant words to strip when normalizing product names
_COLOR_WORDS = {
    "black", "white", "grey", "gray", "blue", "red", "green", "beige", "pink",
    "brown", "orange", "yellow", "purple", "silver", "gold", "cream", "navy",
    "moon", "lava", "deep", "dark", "light", "classic", "comfort", "stone",
    "stormy", "almond", "moos", "moss", "sand", "sky", "ocean", "seashell",
    "autumn", "spring", "winter", "summer", "midnight", "candy", "taupe",
    "negru", "alb", "gri", "albastru", "rosu", "verde", "bej", "roz", "intens",
    "alomond",  # typo on toysforkids
}
# Romanian product-type prefixes to strip
_PREFIX_WORDS = {"carucior", "landou", "scoica", "scaun", "auto"}
# Frame/chassis codes to strip
_FRAME_CODES = {"tpe", "blk", "slv", "chr", "rse", "blk b", "slv b", "tpe b", "chr b", "b"}


def normalize_product_name(name: str) -> str:
    """Normalize a product name for grouping: strip colors, prefixes, frame codes.

    'Carucior Balios S Lux Cybex TPE, Moos Green' → 'Balios S Lux Cybex'
    'Carucior Cybex, Balios S Lux 3 in 1 BLK, Moon Black' → 'Cybex Balios S Lux 3 in 1'
    """
    # Remove everything after last comma (usually color)
    if "," in name:
        parts = name.rsplit(",", 1)
        # Only strip if the part after comma looks like a color/variant
        after_comma = parts[1].strip().lower()
        after_words = set(after_comma.split())
        if after_words & _COLOR_WORDS or len(after_comma.split()) <= 3:
            name = parts[0].strip()

    # If there's still a comma (e.g., "Cybex, Balios"), remove it
    name = name.replace(",", " ")

    # Split into words and filter
    words = name.split()
    filtered = []
    for w in words:
        wl = w.lower().strip(".,;:-")
        if wl in _PREFIX_WORDS:
            continue
        if wl in _COLOR_WORDS:
            continue
        if wl in _FRAME_CODES:
            continue
        filtered.append(w.strip(".,;:-"))

    result = " ".join(filtered).strip()
    # Collapse multiple spaces
    result = re.sub(r'\s+', ' ', result)
    return result


@dataclass
class SearchResult:
    """A single product found in search results."""
    name: str
    url: str
    retailer: str
    price: Optional[float] = None
    original_price: Optional[float] = None
    currency: str = "RON"
    in_stock: bool = False
    image_url: Optional[str] = None

    @property
    def discount_pct(self) -> Optional[float]:
        if self.price and self.original_price and self.original_price > self.price:
            return round((1 - self.price / self.original_price) * 100, 1)
        return None

    @property
    def normalized_name(self) -> str:
        return normalize_product_name(self.name)


@dataclass
class SearchResultGroup:
    """A group of search results for the same product model (color-agnostic)."""
    normalized_name: str
    items: list[SearchResult] = field(default_factory=list)

    @property
    def best_price(self) -> Optional[float]:
        prices = [r.price for r in self.items if r.price]
        return min(prices) if prices else None

    @property
    def max_price(self) -> Optional[float]:
        prices = [r.price for r in self.items if r.price]
        return max(prices) if prices else None

    @property
    def best_retailer(self) -> Optional[str]:
        best = min((r for r in self.items if r.price), key=lambda r: r.price, default=None)
        return best.retailer if best else None

    @property
    def count(self) -> int:
        return len(self.items)

    @property
    def in_stock_count(self) -> int:
        return sum(1 for r in self.items if r.in_stock)

    @property
    def retailers(self) -> list[str]:
        return list(set(r.retailer for r in self.items))

    @property
    def best_image(self) -> Optional[str]:
        for r in self.items:
            if r.image_url:
                return r.image_url
        return None


@dataclass
class ScrapeResult:
    price: Optional[float] = None
    original_price: Optional[float] = None
    currency: str = "RON"
    in_stock: bool = False
    product_name: Optional[str] = None
    image_url: Optional[str] = None
    error: Optional[str] = None

    @property
    def success(self) -> bool:
        return self.price is not None and self.error is None

    @property
    def discount_pct(self) -> Optional[float]:
        if self.price and self.original_price and self.original_price > self.price:
            return round((1 - self.price / self.original_price) * 100, 1)
        return None


class BaseScraper:
    """Base class for all retailer scrapers."""

    RETAILER_NAME = "Unknown"

    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ro-RO,ro;q=0.9,en-US;q=0.8,en;q=0.7",
    }

    def fetch(self, url: str) -> str:
        """Fetch page HTML."""
        with httpx.Client(headers=self.HEADERS, follow_redirects=True, timeout=30) as client:
            resp = client.get(url)
            resp.raise_for_status()
            return resp.text

    def scrape(self, url: str) -> ScrapeResult:
        """Scrape price data from URL. Override in subclasses."""
        raise NotImplementedError

    def search(self, query: str, max_results: int = 10) -> list[SearchResult]:
        """Search for products by name. Override in subclasses."""
        raise NotImplementedError

    def parse_romanian_price(self, text: str) -> Optional[float]:
        """Parse Romanian price formats: 2.032,50 or 2032.50 or 2032"""
        if not text:
            return None
        import re
        text = text.strip().replace("\xa0", "").replace(" ", "")
        # Remove currency suffixes
        text = re.sub(r'(lei|ron|lei/buc|mdl)$', '', text, flags=re.IGNORECASE).strip()
        # Format: 2.032,50 (dot thousands, comma decimal)
        if re.match(r'^\d{1,3}(\.\d{3})+(,\d{1,2})?$', text):
            text = text.replace('.', '').replace(',', '.')
        # Format: 2032,50 (comma decimal, no thousands sep)
        elif ',' in text:
            text = text.replace('.', '').replace(',', '.')
        try:
            return float(text)
        except ValueError:
            return None
