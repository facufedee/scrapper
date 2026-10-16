"""Public HTTP contract. Changing a field here is a breaking change for clients: add a new
API version instead."""

from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field

DISCLAIMER = (
    "Estimate based on asking prices of comparable listings currently published on the market, "
    "not on closing prices. It is not a formal appraisal."
)


class PropertyType(str, Enum):
    apartment = "apartment"
    house = "house"
    ph = "ph"
    land = "land"
    retail = "retail"
    office = "office"
    garage = "garage"
    warehouse = "warehouse"
    weekend_house = "weekend_house"
    farm = "farm"


class ValuationRequest(BaseModel):
    lat: float = Field(ge=-90, le=90, examples=[-34.588])
    lon: float = Field(ge=-180, le=180, examples=[-58.43])
    property_type: PropertyType
    area_m2: float = Field(
        gt=0, le=1_000_000, description="Built area in m2 (lot area for land).", examples=[60]
    )


class PriceRange(BaseModel):
    low_usd: float
    high_usd: float


class ComparableOut(BaseModel):
    source: str
    url: Optional[str]
    distance_km: float
    price_usd: float
    area_m2: float
    price_per_m2_usd: float
    bedrooms: Optional[int]
    total_rooms: Optional[int]


class ValuationResponse(BaseModel):
    estimated_value_usd: float
    range: PriceRange = Field(description="Interquartile range of comparable USD/m2 times the area.")
    median_price_per_m2_usd: float
    comparables_count: int
    search_radius_km: float
    confidence: Literal["high", "medium", "low"]
    comparables: list[ComparableOut] = Field(description="Nearest comparables used (up to 10).")
    disclaimer: str = DISCLAIMER


class ErrorDetail(BaseModel):
    code: str
    message: str
