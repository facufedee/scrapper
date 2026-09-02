from abc import ABC, abstractmethod
from typing import Iterator, Optional

from pydantic import BaseModel, Field


class PropertyItem(BaseModel):
    """Normalized shape every scraper must produce, regardless of the source
    site's own data structure. This is what gets written to the DB."""

    source: str
    source_id: str
    url: Optional[str] = None  # None when the ingest path had no real listing link (e.g. link-less manual pastes)

    title: Optional[str] = None
    description: Optional[str] = None
    property_type: Optional[str] = None
    operation: str  # sale, rent, temporal
    status: Optional[str] = None

    price: Optional[float] = None
    currency: Optional[str] = None
    expenses_price: Optional[float] = None
    expenses_currency: Optional[str] = None

    address: Optional[str] = None
    neighborhood: Optional[str] = None
    city: Optional[str] = None
    province: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None

    total_rooms: Optional[int] = None
    bedrooms: Optional[int] = None
    bathrooms: Optional[int] = None
    land_m2: Optional[float] = None
    covered_m2: Optional[float] = None
    total_m2: Optional[float] = None

    agent_name: Optional[str] = None
    agent_phone: Optional[str] = None
    agent_email: Optional[str] = None
    office_name: Optional[str] = None

    photos: list[str] = Field(default_factory=list)
    raw: dict = Field(default_factory=dict)


class BaseScraper(ABC):
    source_name: str
    # If True, fetch_listings(operation="all") does a single pass covering every
    # operation itself. If False (default), the caller must call fetch_listings
    # once per operation ("sale", "rent", "temporal") because the source's own
    # API/pagination is scoped to a single operation per request.
    all_in_one = False

    def close(self) -> None:
        """Optional cleanup hook (e.g. closing a browser). No-op by default."""

    @abstractmethod
    def fetch_listings(
        self,
        operation: str = "sale",
        max_pages: Optional[int] = None,
    ) -> Iterator[PropertyItem]:
        """Yield PropertyItem objects for the given operation ('sale', 'rent', 'temporal')."""
        raise NotImplementedError
