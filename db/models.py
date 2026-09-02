from datetime import datetime, timezone

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Property(Base):
    """Normalized property record. One row per (source, source_id), no matter
    which site it came from — this is the common schema every scraper writes into."""

    __tablename__ = "properties"
    __table_args__ = (UniqueConstraint("source", "source_id", name="uq_source_id"),)

    id = Column(Integer, primary_key=True, autoincrement=True)

    source = Column(String(50), nullable=False, index=True)  # 'remax', 'zonaprop', ...
    source_id = Column(String(100), nullable=False)  # id/slug as used by the source site
    url = Column(String(500))  # nullable: not every ingest path has a real listing URL (e.g. link-less manual pastes)

    title = Column(String(500))
    description = Column(Text)
    property_type = Column(String(100))  # casa, departamento, ph, terreno...
    operation = Column(String(20), index=True)  # sale, rent, temporal
    status = Column(String(50))  # active, inactive, sold...

    price = Column(Float)
    currency = Column(String(10))
    expenses_price = Column(Float)
    expenses_currency = Column(String(10))

    address = Column(String(300))
    neighborhood = Column(String(150))
    city = Column(String(150))
    province = Column(String(150))
    lat = Column(Float)
    lon = Column(Float)

    total_rooms = Column(Integer)
    bedrooms = Column(Integer)
    bathrooms = Column(Integer)
    land_m2 = Column(Float)
    covered_m2 = Column(Float)
    total_m2 = Column(Float)

    agent_name = Column(String(200))
    agent_phone = Column(String(100))
    agent_email = Column(String(200))
    office_name = Column(String(200))

    raw_json = Column(JSON)  # full original payload, in case we need a field later

    first_seen_at = Column(DateTime, default=utcnow, nullable=False)
    last_seen_at = Column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)
    last_scraped_at = Column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    photos = relationship("PropertyPhoto", back_populates="property", cascade="all, delete-orphan")
    price_history = relationship("PriceHistory", back_populates="property", cascade="all, delete-orphan")


class PropertyPhoto(Base):
    __tablename__ = "property_photos"

    id = Column(Integer, primary_key=True, autoincrement=True)
    property_id = Column(Integer, ForeignKey("properties.id"), nullable=False)
    url = Column(String(500), nullable=False)
    position = Column(Integer, default=0)

    property = relationship("Property", back_populates="photos")


class PriceHistory(Base):
    __tablename__ = "price_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    property_id = Column(Integer, ForeignKey("properties.id"), nullable=False)
    price = Column(Float)
    currency = Column(String(10))
    expenses_price = Column(Float)
    recorded_at = Column(DateTime, default=utcnow, nullable=False)

    property = relationship("Property", back_populates="price_history")


class ScrapeRun(Base):
    __tablename__ = "scrape_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source = Column(String(50), nullable=False)
    operation = Column(String(20))
    started_at = Column(DateTime, default=utcnow, nullable=False)
    finished_at = Column(DateTime)
    status = Column(String(20), default="running")  # running, success, failed
    items_found = Column(Integer, default=0)
    items_new = Column(Integer, default=0)
    items_updated = Column(Integer, default=0)
    error = Column(Text)
