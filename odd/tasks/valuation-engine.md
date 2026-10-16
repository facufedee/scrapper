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
- [x] T4 Smoke-run the engine against the real DB (route: inline)
- [x] T5 Exclude placeholder coordinates shared by many listings (route: inline)
- [x] T6 Geographic (lat, lon) index for sub-second candidate queries (route: inline)

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
- T4: smoke on real DB OK (Palermo apt 60m2 USD 193k, Caballito apt 45m2 USD 95k). Type coverage 92%.
  Found 1,768 listings from one source on a single point in Castelar (placeholder location) and
  ~3,400 rows on points shared by >=10 listings; queries take ~0.9 s (no lat/lon index). Added T5, T6.
- T5: RED observed (placeholder listings counted), GREEN 80 passed.
- T6: RED observed (index missing), GREEN 81 passed. On a DB copy: bbox query 824 ms -> 100 ms, index build 0.5 s.
  End-to-end smoke on copy: 150-250 ms per valuation; Castelar house comparables 390 -> 53 (USD/m2 1,000 -> 1,508)
  after T5. The real DB gets the index on the next `cli.py run` (init_db); it was not modified in this feature.

## Review
Native review (medium risk, consent granted, lens: reliability): approved and acknowledged
(lineage review-831409253dc96b16). Non-blocking advisory findings, to address in a later task:
- WARNING placeholder heuristic may drop real buildings with >=10 listings on one point (valuation/repository.py).
- WARNING service tests depend on a module-level id counter / ordering (tests/test_valuation_service.py).
- WARNING tuning params (radii, target, min) are not validated (valuation/domain.py, valuation/service.py).
- SUGGESTION dedupe keeps whichever duplicate the query returns first (non-deterministic keeper).
- SUGGESTION subject coordinates are not range-validated (belongs in the API request schema).
- SUGGESTION currency validator assumes str input (scrapers/base.py).

## Next step
FastAPI layer (`POST /v1/valuations`), API keys, rate limiting, then Postgres migration for serving.
