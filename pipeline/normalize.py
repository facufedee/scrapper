"""Normalization of free-text values coming from heterogeneous source sites.

Scrapers write whatever the source site uses ("US$", "CASA", "departamento_estandar",
"galpón" with different Unicode encodings...). These helpers map those spellings to a small
canonical vocabulary so listings from different sites can be compared with each other.
"""

import re
import unicodedata
from typing import Optional

_USD_MARKERS = ("USD", "U$S", "U$D", "US$", "DOLAR")
_ARS_MARKERS = ("ARS", "PESO")


def _strip_accents(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def normalize_currency(raw: Optional[str]) -> Optional[str]:
    """Map currency spellings to ISO codes ("USD" / "ARS").

    Unknown non-empty values are kept (uppercased) instead of dropped, so no information
    is lost; empty values become None.
    """
    if raw is None:
        return None
    key = _strip_accents(raw).strip().upper()
    if not key:
        return None
    if any(marker in key for marker in _USD_MARKERS):
        return "USD"
    if any(marker in key for marker in _ARS_MARKERS) or key.startswith("$"):
        return "ARS"
    return key


def _clean_type(value: str) -> str:
    value = _strip_accents(value).lower().replace("_", " ")
    return re.sub(r"\s+", " ", value).strip()


def _canonical_single_type(value: str) -> Optional[str]:
    if value in ("ph", "phs", "casa en ph"):
        return "ph"
    if value in ("quinta", "quintas", "casa quinta"):
        return "weekend_house"
    if value.startswith(("campo", "chacra")):
        return "farm"
    if value.startswith("departamento") or value in ("monoambiente", "semipiso", "penthouse", "loft"):
        return "apartment"
    if value.startswith(("casa", "chalet", "duplex", "triplex")):
        return "house"
    if value.startswith(("terreno", "lote", "fraccion")):
        return "land"
    if value.startswith("local"):
        return "retail"
    if value.startswith(("oficina", "consultorio")):
        return "office"
    if value.startswith(("cochera", "garaje", "garage")):
        return "garage"
    if value.startswith(("galpon", "deposito")):
        return "warehouse"
    return None


def canonical_property_type(raw: Optional[str]) -> Optional[str]:
    """Map a source-specific property type to a canonical one.

    Canonical types: apartment, house, ph, land, retail, office, garage, warehouse,
    weekend_house, farm. Returns None for unknown values and for multi-valued types
    whose parts disagree (e.g. "casa, departamento, local").
    """
    if not raw:
        return None
    parts = [_clean_type(part) for part in raw.split(",")]
    canonical = {_canonical_single_type(part) for part in parts if part}
    if len(canonical) != 1:
        return None
    return canonical.pop()
