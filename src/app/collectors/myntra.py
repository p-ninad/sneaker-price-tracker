"""Myntra sneaker collector implementation.

Strategy:
1. Try GraphQL API endpoints first
2. Fallback to Playwright if needed
3. Parse HTML with BeautifulSoup

This collector demonstrates the hybrid approach.
"""

import httpx
import json
import re
from typing import Optional, List
from urllib.parse import quote_plus, urljoin, urlparse
from app.collectors.base import (
    BaseCollector,
    ProductData,
    CollectorResponse,
)
from app.utils.logger import get_logger
from app.config import settings
from app.utils.url_parser import extract_product_id_from_url

logger = get_logger(__name__)


class MyntraCollector(BaseCollector):
    """Myntra platform collector using APIs and web scraping."""

    def __init__(self):
        super().__init__(
            platform_name="myntra",
            base_url="https://www.myntra.com",
        )
        self.api_base = "https://www.myntra.com/gateway/v2"
        self.graphql_endpoint = "https://www.myntra.com/graphql"

    async def discover_products(self, query: str = "sneaker", limit: int = 100) -> CollectorResponse:
        """Discover sneaker products using Myntra API.

        Attempts to use Myntra's GraphQL or JSON API first.
        Falls back to HTML scraping if APIs fail.
        """
        try:
            # Try GraphQL API first
            products = await self._discover_via_graphql(query, limit)

            if products:
                logger.info(
                    "Discovered products via GraphQL",
                    platform="myntra",
                    products_count=len(products),
                    query=query,
                )
                return CollectorResponse(
                    success=True,
                    products=products,
                    duration_seconds=0,  # TODO: measure
                )

            # Fallback to REST API
            products = await self._discover_via_rest_api(query, limit)

            if products:
                logger.info(
                    "Discovered products via REST API",
                    platform="myntra",
                    products_count=len(products),
                    query=query,
                )
                return CollectorResponse(
                    success=True,
                    products=products,
                    duration_seconds=0,
                )

            # Fallback to HTML scraping
            products = await self._discover_via_scraping(query, limit)

            if products:
                logger.info(
                    "Discovered products via HTML scraping",
                    platform="myntra",
                    products_count=len(products),
                    query=query,
                )
                return CollectorResponse(
                    success=True,
                    products=products,
                    duration_seconds=0,
                )

            return CollectorResponse(
                success=False,
                error_message="All discovery methods failed",
            )

        except Exception as e:
            logger.error(
                "Discovery failed",
                platform="myntra",
                error=str(e),
                query=query,
            )
            return CollectorResponse(
                success=False,
                error_message=str(e),
            )

    async def fetch_product_details(self, product_id: str) -> Optional[ProductData]:
        """Fetch detailed product information."""
        try:
            target = (product_id or "").strip()
            source_url = target if target.startswith("http") else None
            resolved_product_id = (
                extract_product_id_from_url(source_url) if source_url else target
            )

            logger.info(
                "Starting product fetch",
                product_id=resolved_product_id,
                source_url=source_url,
                platform="myntra",
            )
            
            # Try REST API first
            logger.debug(
                "Attempting API fetch",
                product_id=resolved_product_id,
            )
            product = await self._fetch_details_via_api(resolved_product_id)
            if product:
                logger.info(
                    "Successfully fetched product via API",
                    product_id=resolved_product_id,
                )
                return product
            
            logger.debug(
                "API fetch failed, falling back to Playwright scraping",
                product_id=resolved_product_id,
            )

            # Try lightweight HTTP fetch before browser automation.
            # This often works when Playwright navigation is blocked/timing out.
            product = await self._fetch_details_via_http(
                resolved_product_id,
                source_url=source_url,
            )
            if product:
                logger.info(
                    "Successfully fetched product via HTTP HTML fallback",
                    product_id=resolved_product_id,
                )
                return product

            # Fallback to scraping
            product = await self._fetch_details_via_scraping(
                resolved_product_id,
                source_url=source_url,
            )
            if product:
                logger.info(
                    "Successfully fetched product via scraping",
                    product_id=resolved_product_id,
                )
            else:
                logger.error(
                    "Failed to fetch product via both API and scraping",
                    product_id=resolved_product_id,
                    source_url=source_url,
                    platform="myntra",
                )
            return product

        except Exception as e:
            logger.error(
                "Unexpected error during product fetch",
                platform="myntra",
                product_id=product_id,
                error=str(e),
                error_type=type(e).__name__,
            )
            return None

    # === Private Methods ===

    async def _discover_via_graphql(self, query: str, limit: int) -> Optional[List[ProductData]]:
        """Try to discover products using GraphQL API."""
        try:
            # This is a placeholder for actual GraphQL query
            # Real implementation would inspect network requests
            await self.random_delay()

            # TODO: Implement actual GraphQL discovery
            # For now, return None to signal fallback
            return None

        except Exception as e:
            logger.debug(f"GraphQL discovery failed: {e}", platform="myntra")
            return None

    async def _discover_via_rest_api(self, query: str, limit: int) -> Optional[List[ProductData]]:
        """Try to discover products using REST API."""
        try:
            await self.random_delay()

            url = f"{self.api_base}/products"
            params = {
                "query": query,
                "limit": min(limit, 100),
                "offset": 0,
            }

            async with httpx.AsyncClient(
                timeout=settings.request_timeout_seconds,
                headers=self.get_browser_headers(),
            ) as client:
                response = await client.get(url, params=params)
                response.raise_for_status()

                data = response.json()
                products = []

                # Parse API response
                # TODO: Adjust based on actual API response format
                if "data" in data and "products" in data["data"]:
                    for item in data["data"]["products"][:limit]:
                        try:
                            product = self._parse_api_product(item)
                            if product:
                                products.append(product)
                        except Exception as e:
                            logger.debug(f"Failed to parse product: {e}")
                            continue

                return products if products else None

        except Exception as e:
            logger.debug(f"REST API discovery failed: {e}", platform="myntra")
            return None

    async def _discover_via_scraping(self, query: str, limit: int) -> Optional[List[ProductData]]:
        """Fallback: Discover products using Playwright + BeautifulSoup."""
        try:
            candidate_urls = await self._discover_product_urls_via_http(query, limit)
            if not candidate_urls:
                candidate_urls = await self._discover_product_urls_via_playwright(query, limit)

            if not candidate_urls:
                logger.info(
                    "Myntra discovery found no product URLs",
                    platform="myntra",
                    query=query,
                )
                return None

            products: list[ProductData] = []
            seen_urls: set[str] = set()
            for url in candidate_urls:
                normalized_url = url.strip()
                if not normalized_url or normalized_url in seen_urls:
                    continue
                seen_urls.add(normalized_url)

                product_id = extract_product_id_from_url(normalized_url) or normalized_url
                product = await self._fetch_details_via_http(
                    product_id,
                    source_url=normalized_url,
                )
                if product is None:
                    product = await self._fetch_details_via_scraping(
                        product_id,
                        source_url=normalized_url,
                    )
                if product is None:
                    continue

                products.append(product)
                if len(products) >= limit:
                    break

            return products or None

        except Exception as e:
            logger.debug(f"HTML scraping failed: {e}", platform="myntra")
            return None

    async def _discover_product_urls_via_http(self, query: str, limit: int) -> list[str]:
        """Discover candidate product URLs from Myntra search HTML."""
        try:
            for search_url in self._build_search_urls(query):
                try:
                    async with httpx.AsyncClient(
                        timeout=settings.request_timeout_seconds,
                        headers=self.get_browser_headers(),
                        follow_redirects=True,
                    ) as client:
                        response = await client.get(search_url)
                        if response.status_code >= 400:
                            continue

                        html = response.text
                        if self._html_looks_blocked(html):
                            continue

                        urls = self._extract_product_urls_from_html(html, str(response.url))
                        if urls:
                            return urls[:limit]
                except Exception as exc:
                    logger.debug(
                        "HTTP search discovery failed",
                        platform="myntra",
                        search_url=search_url,
                        error=str(exc),
                    )
                    continue
        except Exception as exc:
            logger.debug(
                "HTTP search discovery aborted",
                platform="myntra",
                error=str(exc),
            )
        return []

    async def _discover_product_urls_via_playwright(self, query: str, limit: int) -> list[str]:
        """Discover candidate product URLs from Myntra search pages with Playwright."""
        try:
            from playwright.async_api import async_playwright

            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=settings.playwright_headless,
                    args=[
                        "--disable-blink-features=AutomationControlled",
                        "--disable-http2",
                        "--disable-quic",
                    ],
                )
                context = await browser.new_context(
                    user_agent=self.get_browser_headers()["User-Agent"],
                    locale="en-US",
                    viewport={"width": 1366, "height": 768},
                    ignore_https_errors=True,
                )
                page = await context.new_page()

                try:
                    for search_url in self._build_search_urls(query):
                        try:
                            await page.goto(
                                search_url,
                                timeout=settings.browser_timeout_ms,
                                wait_until="domcontentloaded",
                            )
                            html = await page.content()
                            if self._html_looks_blocked(html):
                                continue

                            urls = self._extract_product_urls_from_html(html, page.url)
                            if urls:
                                return urls[:limit]
                        except Exception as exc:
                            logger.debug(
                                "Playwright search discovery failed for URL",
                                platform="myntra",
                                search_url=search_url,
                                error=str(exc),
                            )
                            continue
                finally:
                    await context.close()
                    await browser.close()
        except Exception as exc:
            logger.debug(
                "Playwright search discovery failed",
                platform="myntra",
                error=str(exc),
            )
        return []

    @staticmethod
    def _build_search_urls(query: str) -> list[str]:
        """Build candidate Myntra search URLs for a discovery query."""
        cleaned_query = str(query or "").strip()
        encoded_query = quote_plus(cleaned_query or "sneaker")
        slug = re.sub(r"[^a-z0-9]+", "-", cleaned_query.lower()).strip("-") or "sneaker"

        return list(
            dict.fromkeys(
                [
                    f"https://www.myntra.com/search?rawQuery={encoded_query}",
                    f"https://www.myntra.com/{slug}?rawQuery={encoded_query}",
                    f"https://www.myntra.com/{slug}",
                    f"https://www.myntra.com/catalog?rawQuery={encoded_query}",
                ]
            )
        )

    @staticmethod
    def _html_looks_blocked(html: str) -> bool:
        """Detect Myntra anti-bot pages."""
        blocked_markers = (
            "access denied",
            "request unsuccessful",
            "bot verification",
            "please verify you are a human",
            "captcha-delivery",
        )
        lower_html = html.lower()
        return any(marker in lower_html for marker in blocked_markers)

    def _extract_product_urls_from_html(self, html: str, base_url: str) -> list[str]:
        """Extract candidate Myntra product URLs from search result HTML."""
        try:
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(html, "html.parser")
            candidate_urls: list[str] = []

            for anchor in soup.select("a[href]"):
                href = anchor.get("href")
                if not href:
                    continue

                absolute_url = urljoin(base_url, href)
                if self._is_product_url(absolute_url):
                    candidate_urls.append(absolute_url)

            if not candidate_urls:
                for match in re.findall(r'(?:(?:https?:)?//www\.myntra\.com[^"\']+|/[^"\']+)', html):
                    absolute_url = urljoin(base_url, match)
                    if self._is_product_url(absolute_url):
                        candidate_urls.append(absolute_url)

            return list(dict.fromkeys(candidate_urls))
        except Exception as exc:
            logger.debug(
                "Failed to extract product URLs from HTML",
                platform="myntra",
                error=str(exc),
            )
            return []

    @staticmethod
    def _is_product_url(url: str) -> bool:
        """Return True when a URL looks like a Myntra product page."""
        parsed = urlparse(url)
        hostname = parsed.netloc.lower()
        if "myntra.com" not in hostname:
            return False

        path_parts = [part for part in parsed.path.strip("/").split("/") if part]
        if not path_parts:
            return False

        if path_parts[-1].lower() != "buy" and not path_parts[-1].isdigit():
            return False

        return any(part.isdigit() for part in path_parts)

    async def _fetch_details_via_api(self, product_id: str) -> Optional[ProductData]:
        """Fetch product details from API."""
        try:
            await self.random_delay()

            url = f"{self.api_base}/products/{product_id}"

            async with httpx.AsyncClient(
                timeout=settings.request_timeout_seconds,
                headers=self.get_browser_headers(),
            ) as client:
                response = await client.get(url)
                response.raise_for_status()

                data = response.json()
                return self._parse_api_product(data)

        except httpx.HTTPStatusError as e:
            logger.debug(
                "API fetch returned error status",
                product_id=product_id,
                status_code=e.response.status_code,
            )
            return None
        except Exception as e:
            logger.debug(
                "API fetch failed, will try scraping",
                product_id=product_id,
                error=str(e),
            )
            return None

    async def _fetch_details_via_http(
        self,
        product_id: str,
        source_url: str | None = None,
    ) -> Optional[ProductData]:
        """Fetch product details using plain HTTP + HTML parsing."""
        try:
            candidate_urls = []
            if source_url:
                candidate_urls.append(source_url)
            candidate_urls.extend(
                [
                    f"https://www.myntra.com/{product_id}",
                    f"https://www.myntra.com/p/{product_id}",
                    f"https://www.myntra.com/products/{product_id}",
                    f"https://www.myntra.com/shoes/{product_id}",
                ]
            )
            candidate_urls = list(dict.fromkeys(candidate_urls))

            async with httpx.AsyncClient(
                timeout=settings.request_timeout_seconds,
                headers=self.get_browser_headers(),
                follow_redirects=True,
            ) as client:
                for url in candidate_urls:
                    try:
                        response = await client.get(url)
                        if response.status_code >= 400:
                            logger.debug(
                                "HTTP HTML fallback URL returned non-success status",
                                product_id=product_id,
                                url=url,
                                status_code=response.status_code,
                            )
                            continue

                        html = response.text
                        parsed = self._parse_html_product(html, str(response.url))
                        if parsed:
                            return parsed

                        blocked_markers = (
                            "access denied",
                            "request unsuccessful",
                            "bot verification",
                            "please verify you are a human",
                            "captcha-delivery",
                        )
                        lower_html = html.lower()
                        if any(marker in lower_html for marker in blocked_markers):
                            logger.debug(
                                "HTTP HTML fallback got blocked content",
                                product_id=product_id,
                                url=url,
                            )
                    except Exception as e:
                        logger.debug(
                            "HTTP HTML fallback URL failed",
                            product_id=product_id,
                            url=url,
                            error=str(e),
                        )
                        continue

        except Exception as e:
            logger.debug(
                "HTTP HTML fallback failed",
                product_id=product_id,
                error=str(e),
            )

        return None

    async def _fetch_details_via_scraping(
        self,
        product_id: str,
        source_url: str | None = None,
    ) -> Optional[ProductData]:
        """Fallback: Fetch product details using Playwright."""
        try:
            from playwright.async_api import async_playwright
            from bs4 import BeautifulSoup

            await self.random_delay()

            # Build URL - try common Myntra URL patterns
            # Note: Product IDs are sometimes plain numbers that can be accessed via multiple patterns
            possible_urls = []
            if source_url:
                possible_urls.append(source_url)
            possible_urls.extend([
                f"https://www.myntra.com/{product_id}",  # Direct ID (e.g., /36427615)
                f"https://www.myntra.com/p/{product_id}",  # /p/ prefix pattern
                f"https://www.myntra.com/products/{product_id}",  # /products/ pattern
                f"https://www.myntra.com/shoes/{product_id}",  # /shoes/ category pattern
            ])
            # Preserve order while removing duplicates
            possible_urls = list(dict.fromkeys(possible_urls))

            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=settings.playwright_headless,
                    args=[
                        "--disable-blink-features=AutomationControlled",
                        "--disable-http2",
                        "--disable-quic",
                    ],
                )
                context = await browser.new_context(
                    user_agent=self.get_browser_headers()["User-Agent"],
                    locale="en-US",
                    viewport={"width": 1366, "height": 768},
                    ignore_https_errors=True,
                )
                page = await context.new_page()

                product_data = None
                last_error = None
                attempts = []

                for url in possible_urls:
                    try:
                        logger.debug(
                            "Scraping Myntra product - attempting URL",
                            product_id=product_id,
                            url=url,
                        )

                        response = await page.goto(
                            url,
                            timeout=settings.browser_timeout_ms,
                            wait_until="domcontentloaded",
                        )
                        
                        status = response.status if response else "no_response"
                        logger.debug(
                            "Page load response",
                            product_id=product_id,
                            url=url,
                            status=status,
                        )

                        # Wait for product info to load
                        try:
                            await page.wait_for_selector(
                                "h1, .productTitle, [class*='title']",
                                timeout=5000,
                            )
                        except Exception as wait_error:
                            logger.debug(
                                "Product selector timeout - page might lack title element",
                                product_id=product_id,
                                url=url,
                                error=str(wait_error),
                            )
                            # Continue anyway, we'll try to parse what's there

                        final_url = page.url
                        html = await page.content()
                        product_data = self._parse_html_product(html, final_url)
                        if not product_data:
                            blocked_markers = (
                                "access denied",
                                "request unsuccessful",
                                "bot verification",
                                "please verify you are a human",
                                "captcha-delivery",
                            )
                            lower_html = html.lower()
                            if any(marker in lower_html for marker in blocked_markers):
                                attempts.append(
                                    f"URL {url}: blocked page detected at {final_url}"
                                )
                                continue

                        if product_data:
                            logger.info(
                                "Successfully scraped product from Myntra",
                                product_id=product_id,
                                url=url,
                                title=product_data.title,
                            )
                            break  # Found it, exit loop
                        else:
                            # Parsing failed, log the attempt
                            attempts.append(f"URL {url}: parsing failed")

                    except Exception as e:
                        last_error = e
                        attempts.append(f"URL {url}: {type(e).__name__}: {str(e)}")
                        logger.debug(
                            "URL attempt failed during navigation",
                            product_id=product_id,
                            url=url,
                            error_type=type(e).__name__,
                            error=str(e),
                        )
                        continue

                await context.close()
                await browser.close()

                if not product_data:
                    attempts_str = "; ".join(attempts) if attempts else "No attempts recorded"
                    logger.warning(
                        "Playwright scraping exhausted all URL patterns",
                        product_id=product_id,
                        attempted_urls=possible_urls,
                        attempts=attempts_str,
                        last_error=str(last_error) if last_error else "None",
                    )

                return product_data

        except Exception as e:
            logger.debug(
                "Playwright scraping failed",
                product_id=product_id,
                error=str(e),
            )
            return None

    def _parse_html_product(self, html: str, url: str) -> Optional[ProductData]:
        """Parse product data from HTML using BeautifulSoup."""
        try:
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(html, "html.parser")

            # Try various selectors for product title
            title = None
            title_selectors = [
                "h1",
                ".productTitle",
                "[class*='title']",
                "meta[property='og:title']",
            ]
            
            for selector in title_selectors:
                element = soup.select_one(selector)
                if element:
                    if element.name == "meta":
                        title = element.get("content", "").strip()
                    else:
                        title = element.get_text(strip=True)
                    if title:
                        logger.debug(
                            "Found product title",
                            url=url,
                            selector=selector,
                            title=title,
                        )
                        break

            if not title:
                logger.warning(
                    "Could not extract title from HTML - all selectors failed",
                    url=url,
                    attempted_selectors=title_selectors,
                    html_sample=html[:500],
                )
                return None

            # Extract price information
            listed_price = None
            discounted_price = None

            # Try to find price elements
            price_selectors = {
                "discounted_price": [
                    ".productPrice",
                    "[class*='price']",
                    ".discountedPrice",
                ],
                "listed_price": [".mrp", ".originalPrice", ".listPrice"],
            }

            for price_type, selectors in price_selectors.items():
                for selector in selectors:
                    elements = soup.select(selector)
                    for elem in elements:
                        text = elem.get_text(strip=True)
                        # Extract numbers
                        numbers = re.findall(r"\d+\.?\d*", text)
                        if numbers:
                            price_val = float(numbers[0])
                            if price_type == "discounted_price":
                                discounted_price = price_val
                                logger.debug(
                                    "Found discounted price",
                                    url=url,
                                    selector=selector,
                                    price=price_val,
                                )
                            else:
                                listed_price = price_val
                                logger.debug(
                                    "Found listed price",
                                    url=url,
                                    selector=selector,
                                    price=price_val,
                                )
                            break
                    if price_type == "discounted_price" and discounted_price:
                        break
                    elif price_type == "listed_price" and listed_price:
                        break

            # Extract brand and model from title
            brand, model = self.normalize_product_name(title)
            model = self._clean_myntra_model_name(title, brand, fallback=model)

            # Try to extract stock status
            in_stock = "out of stock" not in html.lower()
            sizes_available = self._extract_sizes_from_html(html)

            # Try to extract image
            image_url = None
            img_element = soup.select_one("img[class*='image'], img[class*='product']")
            if img_element:
                image_url = img_element.get("src") or img_element.get("data-src")

            product = ProductData(
                platform_product_id=extract_product_id_from_url(url) or url.split("/")[-1],
                product_url=url,
                title=title,
                brand=brand,
                model_name=model,
                listed_price=listed_price,
                discounted_price=discounted_price,
                currency="INR",
                in_stock=in_stock,
                sizes_available=sizes_available,
                image_url=image_url,
                description=None,
                sku=None,
            )

            logger.debug("Parsed product from HTML", product_id=product.platform_product_id)
            return product

        except Exception as e:
            logger.debug(f"Failed to parse HTML product: {e}")
            return None

    @staticmethod
    def _clean_myntra_model_name(title: str, brand: str, fallback: str) -> str:
        """Clean noisy e-commerce title copy into a model-friendly value."""
        cleaned = re.sub(r"\s+", " ", str(title or "").strip())
        cleaned = re.sub(r"^buy\s+", "", cleaned, flags=re.IGNORECASE)

        brand_name = str(brand or "").strip()
        if brand_name:
            cleaned = re.sub(
                rf"^{re.escape(brand_name)}\s+",
                "",
                cleaned,
                flags=re.IGNORECASE,
            )

        cleaned = re.sub(
            r"\b(unisex|men|mens|women|womens)\b",
            " ",
            cleaned,
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(
            r"\b(footwear|sneaker|sneakers|shoe|shoes)\b.*$",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
        cleaned = cleaned.replace("-", " ")
        cleaned = re.sub(r"\s+", " ", cleaned).strip()

        return cleaned or fallback

    @staticmethod
    def _extract_sizes_from_html(html: str) -> Optional[List[str]]:
        """Extract available UK sizes from embedded Myntra page data."""
        candidates = set()

        patterns = [
            r'"sizeDisplayName"\s*:\s*"([^"]+)"',
            r'"displaySize"\s*:\s*"([^"]+)"',
            r'"size"\s*:\s*"((?:UK\s*)?\d+(?:\.\d+)?)"',
            r'"label"\s*:\s*"((?:UK\s*)?\d+(?:\.\d+)?)"',
        ]
        for pattern in patterns:
            for match in re.findall(pattern, html, flags=re.IGNORECASE):
                value = str(match).strip().upper()
                if not value:
                    continue
                number_match = re.search(r"(\d+(?:\.\d+)?)", value)
                if number_match:
                    candidates.add(f"UK{number_match.group(1)}")

        if not candidates:
            return None

        def _size_key(size_token: str):
            number = re.search(r"(\d+(?:\.\d+)?)", size_token)
            return float(number.group(1)) if number else 0.0

        return sorted(candidates, key=_size_key)

    def _parse_api_product(self, data: dict) -> Optional[ProductData]:
        """Parse product data from API response."""
        try:
            # TODO: Adjust based on actual API response format
            product_id = data.get("id") or data.get("productId")
            if not product_id:
                return None

            title = data.get("title") or data.get("name", "")
            if not title:
                return None

            brand, model = self.normalize_product_name(title)

            product = ProductData(
                platform_product_id=str(product_id),
                product_url=data.get("url") or f"{self.base_url}/products/{product_id}",
                title=title,
                brand=brand,
                model_name=model,
                listed_price=data.get("originalPrice") or data.get("mrp"),
                discounted_price=data.get("discountedPrice") or data.get("price"),
                currency="INR",
                discount_percentage=data.get("discountPercentage"),
                in_stock=data.get("inStock", True),
                sizes_available=data.get("availableSizes"),
                image_url=data.get("imageUrl") or data.get("image"),
                description=data.get("description"),
                sku=data.get("sku"),
            )

            return product

        except Exception as e:
            logger.debug(f"Failed to parse product: {e}")
            return None
