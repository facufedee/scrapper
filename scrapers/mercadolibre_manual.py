"""MercadoLibre Inmuebles — manual paste ingestion.

MercadoLibre's robots.txt names ClaudeBot/Claude-User explicitly with
`Disallow: /` across mercadolibre.com.ar and its subdomains (including
inmuebles.mercadolibre.com.ar), and api.mercadolibre.com disallows all bots
and now requires an authenticated app for item reads anyway. So there is no
automated scraper here, on purpose — this is not that.

Instead: the user browses inmuebles.mercadolibre.com.ar themselves, in their
own browser/session, and pastes the page content into the chat. This module
just parses text the user has already fetched — nothing in here makes a
request to any *.mercadolibre.com.ar or api.mercadolibre.com host.

Only "Destacado" (organic) result cards are parsed — "Ad" (sponsored) cards
link through a click1.mercadolibre.com.ar tracking redirect with no stable
item id, so they're skipped; there's nothing durable to upsert against.
"""

import re
from typing import Optional

from scrapers.base import PropertyItem

_ITEM_URL_RE = re.compile(
    r"https://(?P<subdomain>[a-z-]+)\.mercadolibre\.com\.ar/(?P<id>MLA-\d+)-(?P<slug>[a-z0-9-]+?)_JM"
)

_PROPERTY_TYPE_MAP = {
    "casa": "Casa",
    "departamento": "Departamento",
    "ph": "PH",
    "terreno": "Terreno y lote",
    "oficina": "Oficina",
    "local": "Local",
    "galpon": "Galpón",
    "quinta": "Quinta",
    "cochera": "Cochera",
    "inmueble": "Inmueble",
}

_OPERATION_MAP = {"venta": "sale", "alquiler": "rent", "alquiler temporal": "temporal"}


def parse_search_results(text: str, source_url: Optional[str] = None) -> list[PropertyItem]:
    """Parse a pasted MercadoLibre Inmuebles search-results page into
    PropertyItems, in whichever of the two pasted formats it comes in:

    - "linked": markdown-style, `[title](url)` links preserved — gives a real
      item id and URL, so upserts are exact and durable.
    - "plaintext": plain copy-pasted text, no links at all — falls back to a
      synthetic id hashed from (title, address), and `url` is left empty.
      Re-pasting the same listing produces the same id (no duplicates), but
      there's no link back to the source and a genuine title+address
      collision between two different listings would be mistaken for one.

    Only "Destacado" (organic) result cards are parsed in either format —
    "Ad" (sponsored) cards have no stable id to upsert against.
    """
    if "](https://" in text and _ITEM_URL_RE.search(text):
        return _parse_linked(text, source_url)
    return _parse_plaintext(text, source_url)


def _parse_linked(text: str, source_url: Optional[str]) -> list[PropertyItem]:
    lines = text.splitlines()
    items: list[PropertyItem] = []

    # index lines that start a numbered listing card, e.g. "5. Departamento en venta"
    header_re = re.compile(r"^\d+\.\s+([A-Za-zÁÉÍÓÚáéíóúñÑ ]+?)\s+en\s+(venta|alquiler(?: temporal)?)\s*$")

    i = 0
    n = len(lines)
    while i < n:
        header_match = header_re.match(lines[i].strip())
        if not header_match:
            i += 1
            continue

        raw_type, raw_operation = header_match.groups()
        block_start = i
        # gather this card's lines up to (and including) the WhatsApp / status marker
        j = i + 1
        block_lines = []
        status = None
        while j < n and j < i + 25:
            stripped = lines[j].strip()
            block_lines.append(stripped)
            if stripped in ("Ad", "Destacado"):
                status = stripped
                j += 1
                break
            j += 1
        i = j

        if status != "Destacado":
            continue  # sponsored card (or malformed block) — no stable id, skip

        block_text = "\n".join(block_lines)
        url_match = _ITEM_URL_RE.search(block_text)
        if not url_match:
            continue

        title_match = re.search(r"\[([^\]]+)\]\(https://[a-z-]+\.mercadolibre\.com\.ar/MLA-", block_text)
        title = title_match.group(1) if title_match else None

        price_match = re.search(r"(US\$|AR\$|\$)\s*([\d.,]+)", block_text)
        currency, price = (None, None)
        if price_match:
            currency = "USD" if price_match.group(1) == "US$" else "ARS"
            price = _to_float(price_match.group(2))

        total_rooms = _feature_int(block_text, r"([\d.,]+)\s*amb")
        bathrooms = _feature_int(block_text, r"([\d.,]+)\s*ba[ñn]o")
        total_m2 = _feature_float(block_text, r"([\d.,]+)\s*m²\s*totales")
        covered_m2 = _feature_float(block_text, r"([\d.,]+)\s*m²\s*cubiertos")

        # the address is the plain text line right before "WhatsApp"
        address = None
        for bl in reversed(block_lines):
            if bl in ("Ad", "Destacado", "WhatsApp"):
                continue
            if bl.startswith("*") or bl.startswith(("US$", "AR$")):
                continue
            if bl:
                address = bl
                break

        # addresses come as "calle, [barrio,] ciudad, zona" with inconsistent
        # granularity — only take a neighborhood when there are enough parts
        # that the 3rd-from-last isn't actually the street address
        addr_parts = [p.strip() for p in (address or "").split(",")]
        province = addr_parts[-1] if len(addr_parts) >= 1 else None
        city = addr_parts[-2] if len(addr_parts) >= 2 else None
        neighborhood = addr_parts[-3] if len(addr_parts) >= 4 else None

        source_id = url_match.group("id").replace("MLA-", "")
        item = PropertyItem(
            source="mercadolibre",
            source_id=source_id,
            url=f"https://{url_match.group('subdomain')}.mercadolibre.com.ar/{url_match.group('id')}-{url_match.group('slug')}_JM",
            title=title,
            property_type=_PROPERTY_TYPE_MAP.get(raw_type.strip().lower(), raw_type.strip()),
            operation=_OPERATION_MAP.get(raw_operation.strip().lower(), "sale"),
            price=price,
            currency=currency,
            address=address,
            neighborhood=neighborhood,
            city=city,
            province=province,
            total_rooms=total_rooms,
            bathrooms=bathrooms,
            total_m2=total_m2,
            covered_m2=covered_m2,
            raw={"pasted_from": source_url, "block": block_text},
        )
        items.append(item)

    return items


_TITLE_TYPE_RE = re.compile(
    r"^(?P<title>[^\n]+)\n(?P<type>Casa|Departamento|PH|Terreno y lote|Oficina|Local|Galp[oó]n|Quinta|Cochera|Inmueble)"
    r" en (?P<operation>venta|alquiler(?: temporal)?)\n(?P=title)\n",
    re.MULTILINE,
)


def _parse_plaintext(text: str, source_url: Optional[str]) -> list[PropertyItem]:
    """Parse the plain-text (no links at all) paste format — same page,
    copied without a link-preserving method. See parse_search_results."""

    markers = list(re.finditer(r"\nWhatsApp\n(Ad|Destacado)\n?", text))
    items: list[PropertyItem] = []
    block_start = 0

    for m in markers:
        block = text[block_start:m.start()]
        status = m.group(1)
        block_start = m.end()
        if status != "Destacado":
            continue

        title_match = _TITLE_TYPE_RE.search(block)
        if not title_match:
            continue
        title = title_match.group("title").strip()

        price_match = re.search(r"(US\$|AR\$|\$)\s*\n?\s*([\d.,]+)", block)
        currency, price = (None, None)
        if price_match:
            currency = "USD" if price_match.group(1) == "US$" else "ARS"
            price = _to_float(price_match.group(2))

        total_rooms = _feature_int(block, r"([\d.,]+)\s*amb")
        bathrooms = _feature_int(block, r"([\d.,]+)\s*ba[ñn]o")
        total_m2 = _feature_float(block, r"([\d.,]+)\s*m²\s*totales")
        covered_m2 = _feature_float(block, r"([\d.,]+)\s*m²\s*cubiertos")

        # address is the last non-empty line of the block that isn't a
        # feature/price/WhatsApp line — i.e. scan back from the very end
        address = None
        for bl in reversed(block.splitlines()):
            bl = bl.strip()
            if not bl or bl.startswith(("US$", "AR$", "$")) or re.match(r"^[\d.,]+\s*(amb|ba[ñn]o|m²)", bl):
                continue
            address = bl
            break

        addr_parts = [p.strip() for p in (address or "").split(",")]
        province = addr_parts[-1] if len(addr_parts) >= 1 else None
        city = addr_parts[-2] if len(addr_parts) >= 2 else None
        neighborhood = addr_parts[-3] if len(addr_parts) >= 4 else None

        source_id = "plain-" + _stable_hash(title, address)
        item = PropertyItem(
            source="mercadolibre",
            source_id=source_id,
            url=None,
            title=title,
            property_type=_PROPERTY_TYPE_MAP.get(title_match.group("type").strip().lower(), title_match.group("type").strip()),
            operation=_OPERATION_MAP.get(title_match.group("operation").strip().lower(), "sale"),
            price=price,
            currency=currency,
            address=address,
            neighborhood=neighborhood,
            city=city,
            province=province,
            total_rooms=total_rooms,
            bathrooms=bathrooms,
            total_m2=total_m2,
            covered_m2=covered_m2,
            raw={"pasted_from": source_url, "block": block, "format": "plaintext"},
        )
        items.append(item)

    return items


def _stable_hash(*parts: Optional[str]) -> str:
    import hashlib

    normalized = "|".join((p or "").strip().lower() for p in parts)
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:16]


def _to_float(value: str) -> Optional[float]:
    if not value:
        return None
    cleaned = value.replace(".", "").replace(",", ".") if "," in value else value.replace(".", "")
    try:
        return float(cleaned)
    except ValueError:
        return None


def _feature_int(text: str, pattern: str) -> Optional[int]:
    m = re.search(pattern, text, re.IGNORECASE)
    return int(_to_float(m.group(1))) if m else None


def _feature_float(text: str, pattern: str) -> Optional[float]:
    m = re.search(pattern, text, re.IGNORECASE)
    return _to_float(m.group(1)) if m else None
