"""Ejemplo de cómo tus otras aplicaciones pueden leer la base de datos generada."""

from db.database import get_session
from db.models import Property

session = get_session()

query = (
    session.query(Property)
    .filter(Property.source == "remax", Property.operation == "sale", Property.city == "Tigre")
    .order_by(Property.price.asc())
    .limit(10)
)

for p in query:
    print(f"[{p.id}] {p.title} - {p.price} {p.currency} - {p.address} ({p.city}) - {p.url}")

session.close()
