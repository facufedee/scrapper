# Feature: valuation-api

## Objective
Expose the valuation engine (`valuation.service.value_property`) as an authenticated,
rate-limited REST API so ZetaProp and other clients can request property valuations.

## Problem
The valuation engine only exists as a Python function. Clients need an HTTP contract,
access control per client and protection against abuse or bulk extraction of the dataset.

## Why
REST + FastAPI: single well-defined operation, cache-friendly, auto-generated OpenAPI docs
to hand to clients. GraphQL adds no value for one fixed-shape query.

## Scope
- `POST /v1/valuations` with validated request schema and stable response schema.
- `GET /health` (unauthenticated).
- API key auth via `X-API-Key`; keys configured as SHA-256 hashes per client in `ZANO_API_KEYS`
  (`client:sha256hex,...`); helper to generate a key and its hash.
- Per-key in-memory sliding-window rate limit (`ZANO_RATE_LIMIT_PER_MINUTE`, default 60), 429 + `Retry-After`.
- Out of scope: geocoding (clients send lat/lon), DB-backed key management, distributed rate limiting
  (Redis) for multi-worker deployments, deployment/hosting, Supabase index creation.

## Constraints
- Base branch `feat/valuation-engine` (stacked).
- Prices are asking prices; response carries a disclaimer.
- Production `DATABASE_URL` points to Supabase Postgres; local verification uses a SQLite copy only.

## Tasks
- [x] T1 Request/response schemas + `POST /v1/valuations` + `/health` (route: inline)
- [x] T2 API key authentication (route: inline)
- [x] T3 Per-key rate limiting (route: inline)
- [x] T4 Run the server against a local copy of the real DB and verify via HTTP (route: inline)

## Route declaration
Inline: small new package with already-designed contracts; the parent holds the engine context.

## Acceptance criteria
- `pytest` passes; endpoint returns valuation JSON, 401 without/with invalid key, 422 on invalid input
  or insufficient comparables, 429 over the limit.
- OpenAPI docs available at `/docs`.

## Checks
- `.venv/Scripts/python.exe -m pytest -q`
- Live run with uvicorn against the DB copy.

## Progress / evidence
- T1: RED observed (api package missing), GREEN 89 passed.
- T2: RED observed (api.keys missing), GREEN 95 passed. Keys stored as sha256 in ZANO_API_KEYS; empty = deny all.
- T3: RED observed (api.rate_limit missing), GREEN 99 passed. In-memory per-process limiter; Redis needed for multi-worker.
- T4: live uvicorn run against a local SQLite copy (never Supabase). /health 200; no key 401; invalid key 401;
  Palermo apt 60m2 200 (USD 193k, 0.48 s incl. first request); remote area 422 insufficient_comparables;
  invalid type 422; 6th counted request 429 with Retry-After. Found /docs lacked an Authorize button:
  switched to APIKeyHeader security scheme (RED->GREEN, 100 passed). Note: requests with invalid bodies
  also count against the rate limit.

## Next step
Deploy: hosting for the API, create `idx_properties_lat_lon` on Supabase (runs via init_db on next
`cli.py run`), generate the ZetaProp key, and integrate the call from ZetaProp's backend (never the browser).
