from sqlalchemy.orm import Session

from db.models import PriceHistory, Property, PropertyPhoto, utcnow
from scrapers.base import PropertyItem


def upsert_property(session: Session, item: PropertyItem) -> bool:
    """Insert or update a Property row from a normalized PropertyItem.

    Returns True if a new property was created, False if an existing one was updated.
    Does not commit — caller controls transaction/batch boundaries.
    """
    existing = (
        session.query(Property)
        .filter_by(source=item.source, source_id=item.source_id)
        .one_or_none()
    )

    now = utcnow()

    if existing is None:
        prop = Property(
            source=item.source,
            source_id=item.source_id,
            url=item.url,
            title=item.title,
            description=item.description,
            property_type=item.property_type,
            operation=item.operation,
            status=item.status,
            price=item.price,
            currency=item.currency,
            expenses_price=item.expenses_price,
            expenses_currency=item.expenses_currency,
            address=item.address,
            neighborhood=item.neighborhood,
            city=item.city,
            province=item.province,
            lat=item.lat,
            lon=item.lon,
            total_rooms=item.total_rooms,
            bedrooms=item.bedrooms,
            bathrooms=item.bathrooms,
            land_m2=item.land_m2,
            covered_m2=item.covered_m2,
            total_m2=item.total_m2,
            agent_name=item.agent_name,
            agent_phone=item.agent_phone,
            agent_email=item.agent_email,
            office_name=item.office_name,
            raw_json=item.raw,
            first_seen_at=now,
            last_seen_at=now,
            last_scraped_at=now,
        )
        prop.photos = [PropertyPhoto(url=url, position=i) for i, url in enumerate(item.photos)]
        prop.price_history = [
            PriceHistory(price=item.price, currency=item.currency, expenses_price=item.expenses_price, recorded_at=now)
        ]
        session.add(prop)
        return True

    price_changed = existing.price != item.price or existing.currency != item.currency
    if price_changed:
        session.add(
            PriceHistory(
                property_id=existing.id,
                price=item.price,
                currency=item.currency,
                expenses_price=item.expenses_price,
                recorded_at=now,
            )
        )

    existing.url = item.url
    existing.title = item.title
    existing.description = item.description or existing.description
    existing.property_type = item.property_type
    existing.operation = item.operation
    existing.status = item.status
    existing.price = item.price
    existing.currency = item.currency
    existing.expenses_price = item.expenses_price
    existing.expenses_currency = item.expenses_currency
    existing.address = item.address
    existing.neighborhood = item.neighborhood
    existing.city = item.city
    existing.province = item.province
    existing.lat = item.lat
    existing.lon = item.lon
    existing.total_rooms = item.total_rooms
    existing.bedrooms = item.bedrooms
    existing.bathrooms = item.bathrooms
    existing.land_m2 = item.land_m2
    existing.covered_m2 = item.covered_m2
    existing.total_m2 = item.total_m2
    existing.agent_name = item.agent_name
    existing.agent_phone = item.agent_phone
    existing.agent_email = item.agent_email
    existing.office_name = item.office_name
    existing.raw_json = item.raw
    existing.last_seen_at = now
    existing.last_scraped_at = now

    if item.photos and [p.url for p in sorted(existing.photos, key=lambda p: p.position)] != item.photos:
        for photo in list(existing.photos):
            session.delete(photo)
        existing.photos = [PropertyPhoto(url=url, position=i) for i, url in enumerate(item.photos)]

    return False
