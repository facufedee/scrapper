from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from api.dependencies import get_session, require_client
from api.schemas import ComparableOut, PriceRange, ValuationRequest, ValuationResponse
from valuation.domain import InsufficientComparablesError, Subject
from valuation.service import value_property

router = APIRouter()


@router.get("/health", tags=["meta"])
def health() -> dict:
    return {"status": "ok"}


@router.post(
    "/v1/valuations",
    response_model=ValuationResponse,
    tags=["valuations"],
    responses={
        401: {"description": "Missing or invalid X-API-Key header"},
        422: {"description": "Invalid input or not enough comparable listings nearby"},
    },
)
def create_valuation(
    body: ValuationRequest,
    session: Session = Depends(get_session),
    client: str = Depends(require_client),
) -> ValuationResponse:
    subject = Subject(lat=body.lat, lon=body.lon, property_type=body.property_type.value, area_m2=body.area_m2)
    try:
        valuation = value_property(session, subject)
    except InsufficientComparablesError as error:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "insufficient_comparables",
                "message": str(error),
                "found": error.found,
                "required": error.required,
            },
        )

    return ValuationResponse(
        estimated_value_usd=valuation.estimated_value_usd,
        range=PriceRange(low_usd=valuation.low_usd, high_usd=valuation.high_usd),
        median_price_per_m2_usd=valuation.median_price_per_m2_usd,
        comparables_count=valuation.comparables_count,
        search_radius_km=valuation.radius_km,
        confidence=valuation.confidence,
        comparables=[
            ComparableOut(
                source=c.source,
                url=c.url,
                distance_km=c.distance_km,
                price_usd=c.price_usd,
                area_m2=c.area_m2,
                price_per_m2_usd=round(c.price_per_m2),
                bedrooms=c.bedrooms,
                total_rooms=c.total_rooms,
            )
            for c in valuation.comparables
        ],
    )
