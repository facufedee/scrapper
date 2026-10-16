# Feature: valuation-engine

## Objective
Turn the scraped listings database into a property valuation engine that a future
HTTP API (FastAPI, REST) can expose to ZetaProp and other clients.

## Problem
The scraper collects ~90k listings (~63k sales with price, area and coordinates) but has
no valuation logic and no API. Raw data is inconsistent: currency spellings (`USD`, `US$`,
`U$D 85000 /`, empty), ~106 free-text property types (`casa`, `CASA`, `casa_duplex`,
`departamento_estandar`, accent variants), cross-portal duplicate listings and price outliers.

## Why
Reusing the existing dataset is far cheaper than rebuilding scraping inside ZetaProp. The
valuation logic must live in a pure, testable module so the API layer stays thin.

## Scope
- Shared normalization (currency, canonical property type) usable by scrapers and valuation.
- Currency normalization at ingest (`PropertyItem`) so new data lands clean.
- Pure valuation domain: dedupe, area filter, IQR outlier removal, median USD/m2, p25-p75 range, confidence.
- Repository + service: bounding-box candidate query, haversine filter, radius expansion.
- Out of scope (next feature): FastAPI layer, API keys, rate limiting, Postgres migration, DB backfill.

## Constraints
- Existing DB is not rewritten; normalization happens at read time for valuation.
- Sale operations in USD only for v1.
- Prices are asking prices, not closing prices; output must be described as market asking value.

## Tasks
- [x] T1 Shared normalization module + currency validator on `PropertyItem` (route: inline)
- [x] T2 Valuation domain (pure functions) with unit tests (route: inline)
- [x] T3 Repository + service with radius expansion, tested on in-memory SQLite (route: inline)
- [ ] T4 Smoke-run the engine against the real DB (route: inline)

## Route declaration
Inline: the parent already holds the full data-quality evidence from exploration; the
modules are new, small and self-contained. Recorded so skipped delegation is observable.

## Acceptance criteria
- `pytest` passes.
- Normalization maps all high-volume raw types and currency spellings; ambiguous multi-type values map to `None`.
- Valuation returns estimate, range, median USD/m2, comparable count, radius and confidence, or raises
  `InsufficientComparablesError` when fewer than the minimum comparables exist within the max radius.

## Checks
- `.venv/Scripts/python.exe -m pytest -q`
- Smoke run on `data/properties.db` (read-only) for a few known areas.

## Progress / evidence
(see below, updated per task)
- T1: RED observed (module missing), GREEN 57 passed. Currency validator on `PropertyItem` will add one
  extra `price_history` row on next scrape for rows stored as `US$` (one-time, harmless).
- T2: RED observed (module missing), GREEN 71 passed (14 domain tests).
- T3: RED observed (module missing), GREEN 79 passed (8 service tests on in-memory SQLite).
