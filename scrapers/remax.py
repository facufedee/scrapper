"""Remax Argentina scraper.

Remax's site (remax.com.ar) is an Angular app with server-side rendering; the
listing data is served by a public JSON REST API at api-ar.redremax.com that
responds to plain HTTP requests (found by inspecting the Angular TransferState
blob embedded in the SSR'd HTML). No headless browser is needed for listings.
"""

import logging
import time
from typing import Iterator, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

import config
from scrapers.base import BaseScraper, PropertyItem

logger = logging.getLogger(__name__)

API_BASE = "https://api-ar.redremax.com/remaxweb-ar/api"
LISTINGS_ENDPOINT = f"{API_BASE}/listings/findAllWithEntrepreneurships"
PHOTO_BASE = "https://d1acdg20u0pmxj.cloudfront.net"

# maps our normalized operation names to Remax's internal operationId
OPERATION_IDS = {"sale": 1, "rent": 2, "temporal": 3}


def _make_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=config.MAX_RETRIES,
        backoff_factor=1.5,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.headers.update({"User-Agent": config.USER_AGENT, "Accept": "application/json"})
    return session


class RemaxScraper(BaseScraper):
    source_name = "remax"

    def __init__(self, page_size: int = 100, delay: Optional[float] = None):
        self.page_size = page_size
        self.delay = delay if delay is not None else config.REQUEST_DELAY
        self.session = _make_session()

    def fetch_listings(
        self,
        operation: str = "sale",
        max_pages: Optional[int] = None,
    ) -> Iterator[PropertyItem]:
        operation_id = OPERATION_IDS.get(operation)
        if operation_id is None:
            raise ValueError(f"Unknown operation '{operation}', expected one of {list(OPERATION_IDS)}")

        page = 1
        total_pages = None

        while True:
            params = {
                "page": page,
                "pageSize": self.page_size,
                "sort": "-createdAt",
                "in": f"operationId:{operation_id}",
                "landingPath": "",
            }
            resp = self.session.get(LISTINGS_ENDPOINT, params=params, timeout=config.REQUEST_TIMEOUT)
            resp.raise_for_status()
            payload = resp.json()["data"]

            total_pages = payload["totalPages"]
            items = payload["data"]
            logger.info(
                "remax operation=%s page=%s/%s items=%s totalItems=%s",
                operation, page, total_pages, len(items), payload["totalItems"],
            )

            for raw in items:
                item = self._normalize(raw, operation)
                if item is not None:
                    yield item

            if not items:
                break
            if max_pages is not None and page >= max_pages:
                break
            if page >= total_pages:
                break

            page += 1
            time.sleep(self.delay)

    @staticmethod
    def _photo_url(raw_value: str) -> str:
        # Best-effort direct URL; Remax serves these through a CloudFront +
        # Lambda image resizer that requires a signed/whitelisted size query
        # param we haven't reverse-engineered yet. This returns the base
        # path — good enough to store and to fetch manually if needed.
        return f"{PHOTO_BASE}/{raw_value}"

    def _normalize(self, raw: dict, operation: str) -> Optional[PropertyItem]:
        try:
            listing_id = raw["id"]
            slug = raw.get("slug") or str(listing_id)
            url = f"https://www.remax.com.ar/listings/{slug}"

            location = raw.get("location") or {}
            coords = location.get("coordinates") or [None, None]
            lon, lat = (coords + [None, None])[:2]

            currency = (raw.get("currency") or {}).get("value")
            expenses_currency = (raw.get("expensesCurrency") or {}).get("value")
            property_type = (raw.get("type") or {}).get("value")
            status = (raw.get("listingStatus") or {}).get("value")

            associate = raw.get("associate") or {}
            emails = associate.get("emails") or []
            phones = associate.get("phones") or []
            agent_email = next((e["value"] for e in emails if e.get("isPrimary")), None) or (
                emails[0]["value"] if emails else None
            )
            agent_phone = next((p["value"] for p in phones if p.get("isPrimary")), None) or (
                phones[0]["value"] if phones else None
            )

            photos = [self._photo_url(p["rawValue"]) for p in (raw.get("photos") or []) if p.get("rawValue")]

            geo_label = raw.get("geoLabel") or ""
            geo_parts = [p.strip() for p in geo_label.split(",")]
            neighborhood = geo_parts[0] if len(geo_parts) > 0 and geo_parts[0] else None
            city = geo_parts[1] if len(geo_parts) > 1 else None
            province = geo_parts[2] if len(geo_parts) > 2 else None

            return PropertyItem(
                source=self.source_name,
                source_id=str(listing_id),
                url=url,
                title=raw.get("title"),
                property_type=property_type,
                operation=operation,
                status=status,
                price=raw.get("price"),
                currency=currency,
                expenses_price=raw.get("expensesPrice"),
                expenses_currency=expenses_currency,
                address=raw.get("displayAddress"),
                neighborhood=neighborhood,
                city=city,
                province=province,
                lat=lat,
                lon=lon,
                total_rooms=raw.get("totalRooms"),
                bedrooms=raw.get("bedrooms"),
                bathrooms=raw.get("bathrooms"),
                land_m2=raw.get("dimensionLand"),
                covered_m2=raw.get("dimensionCovered"),
                total_m2=raw.get("dimensionTotalBuilt"),
                agent_name=associate.get("name"),
                agent_phone=agent_phone,
                agent_email=agent_email,
                office_name=associate.get("officeName"),
                photos=photos,
                raw=raw,
            )
        except Exception:
            logger.exception("Failed to normalize Remax listing id=%s", raw.get("id"))
            return None
