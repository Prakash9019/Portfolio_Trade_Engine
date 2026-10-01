# Kalpi Portfolio Trade Execution Engine

This repository is a submission for the Kalpi Builder Backend/Infrastructure assignment. It contains a runnable FastAPI implementation for Problem 1 and the design document plus architecture diagram for Problem 2.

The runnable workflow is deliberately safe: `mock` is the only adapter that can execute orders in this repository. It is deterministic, in-memory, and never contacts a broker or exchange. Named broker adapters are documented provider-specific integration scaffolds, not claims of live trading support.

## What is implemented

- `POST /api/v1/portfolios/execute` for `FIRST_TIME` and `REBALANCE` instructions.
- Pydantic validation for symbols, positive quantities, BUY/SELL/ADJUST semantics, order type/limit price, duplicate symbols, broker names, and idempotency headers.
- Normalized `BrokerAdapter` contract: authentication, holdings, order translation, response translation, error translation, placement, status, and cancellation.
- A deterministic mock broker with placement, status lookup, cancellation, rejection, and pre-acceptance transient-failure simulation.
- Idempotency fingerprinting and in-process concurrent-request coordination.
- Bounded retries only for known pre-acceptance transient failures; no retry after an ambiguous timeout.
- Structured per-order results, partial-failure reporting, execution UUIDs, and console completion notifications.
- Single-page vanilla HTML/CSS/JS frontend dashboard (`index.html`) to visually demo portfolio upload, broker connection, single-click execution, and order results.
- Docker/Compose, FastAPI OpenAPI docs, and 25 behavior-focused tests.

## Architecture

```text
HTTP request + Idempotency-Key
        |
        v
FastAPI schema validation
        |
        v
ExecutionService -----> ExecutionRepository (fingerprint + reservation)
        |
        +-----> BrokerRegistry -----> BrokerAdapter
        |                                 |-- MockBrokerAdapter (runnable)
        |                                 `-- named provider scaffolds
        |
        `-----> NotificationService (console summary)
```

`app/services/execution.py` contains no provider-specific request or response fields. Adding a sixth broker means implementing the adapter contract and registering it in `BrokerRegistry`; the execution workflow remains unchanged.

```text
app/
  api/             HTTP routes and dependency injection
  brokers/         adapter contract, registry, mock, provider scaffolds
  core/            environment-backed configuration
  domain/          normalized orders, status enums, request/response schemas
  notifications/   completion notification boundary
  repositories/    in-memory idempotency coordination
  services/        execution and retry workflow
index.html         Single-page visual frontend dashboard
styles.css         Vanilla CSS stylesheet
app.js             Vanilla JS frontend API integration & DOM logic
tests/             FastAPI and service behavior tests
docs/              Problem 2 design and Mermaid architecture diagram
```

## Frontend Dashboard (Bonus UI)

A zero-dependency, single-page Vanilla HTML/CSS/JS frontend dashboard (`index.html`) is provided to visually test the execution flow:

1. **Upload Target Portfolio**: Supports `.csv` or `.json` file upload and displays an interactive target portfolio breakdown table.
2. **Connect Broker**: Connects to the mock broker or named broker scaffolds (Zerodha, FYERS, AngelOne, Groww, Upstox).
3. **Review & Execute Trades**: Compares current position state against target portfolio, calculates order deltas, allows toggling between `REBALANCE` and `FIRST_TIME` modes, and triggers single-click trade execution.
4. **View Results & Order Status**: Real-time status breakdown, execution UUID tracking, success/failure metrics, and normalized order status logs.

### Step-by-Step UI User Testing Flow

1. **Start Backend Server**:
   ```bash
   uvicorn app.main:app --reload --port 8000
   ```
2. **Open Dashboard**: Double-click `index.html` or open `http://localhost:8000` in your web browser. You will see a green banner indicating backend connection.
3. **Step 1 (Upload Portfolio)**: A default sample portfolio (`RELIANCE`, `INFY`, `TCS`, `HDFCBANK`) is pre-loaded. Optionally upload a custom CSV/JSON file using **Upload Portfolio**.
4. **Step 2 (Connect Broker)**: Select **Mock Broker (Runnable Demo)** or any broker adapter and click **Connect Broker**.
5. **Step 3 (Review & Execute)**: Choose execution type (`REBALANCE` or `FIRST_TIME`) and click **⚡ Execute Trades (Single-Click)**.
6. **Step 4 (View Results)**: Scroll to order results to view execution UUID, normalized status (`ACCEPTED`), and per-order attempts. Re-clicking **Execute Trades** demonstrates idempotency replay. No build steps, `npm`, or bundlers required.

## Broker adapter status

| Broker | Status in this repository | What is present | What is intentionally absent |
| --- | --- | --- | --- |
| Mock | Runnable mock | Auth, holdings, order placement, status, cancellation, deterministic failures | Any external brokerage or exchange call |
| Zerodha | Scaffold | Kite-style order/response/error translation boundary | Official SDK/session wiring, instrument catalog, postback/reconciliation |
| FYERS | Scaffold | FYERS v3-style order/response/error translation boundary | Current app activation, static-IP/compliance setup, official client/session wiring |
| Angel One | Scaffold | SmartAPI-style translation boundary and explicit symbol-token requirement | Token resolver, verified client/session, static-IP/compliance setup |
| Groww | Scaffold | Order-reference translation and response boundary | Verified access-token flow, account/instrument validation, live transport |
| Upstox | Scaffold | Order-tag translation boundary and explicit instrument-token requirement | OAuth client, token resolver, sandbox verification, live transport |

The linked official material is the implementation reference for a future live integration: [Zerodha Kite Connect orders](https://kite.trade/docs/connect/v3/orders/), [FYERS API v3 order guide](https://myapi.fyers.in/docsv3#tag/Order-Placement-Guide), [Angel One SmartAPI](https://smartapi.angelone.in/docs), [Groww orders](https://groww.in/trade-api/docs/curl/orders), and [Upstox Place Order V3](https://upstox.com/developer/api-documentation/v3/place-order/). Those APIs must be re-verified at implementation time; broker rules, authentication flows, sandbox support, static-IP requirements, and order schemas change.

## Run locally

Python 3.12+ is required.

```bash
cd /Users/lakshmi/Documents/Codex/2026-10-01/you-are-the-senior-backend-infrastructure
cp .env.example .env
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

OpenAPI is available at http://localhost:8000/docs. The canonical API is versioned under `/api/v1`; unversioned `/health`, `/brokers`, and `/portfolios/execute` are compatibility aliases for evaluator convenience.

## Docker

```bash
docker compose config
docker compose up --build
```

If port 8000 is already in use:

```bash
KALPI_HOST_PORT=18000 docker compose up --build
```

Then call `http://localhost:18000/health`. Compose explicitly sets `KALPI_LIVE_TRADING_ENABLED=false`.

## API demonstration

```bash
curl http://localhost:8000/health
curl http://localhost:8000/brokers
```

First-time creation accepts BUY instructions only:

```bash
curl -X POST http://localhost:8000/api/v1/portfolios/execute \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: first-time-demo-001' \
  -d '{
    "broker":"mock",
    "execution_type":"FIRST_TIME",
    "orders":[
      {"symbol":"INFY","quantity":5,"side":"BUY"},
      {"symbol":"TCS","quantity":2,"side":"BUY"}
    ]
  }'
```

Rebalance expects explicit instructions. It does not calculate a target-portfolio delta. `ADJUST` records an increase or reduction in an overlapping position, with `side` stating the direction:

```bash
curl -X POST http://localhost:8000/api/v1/portfolios/execute \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: rebalance-demo-001' \
  -d '{
    "broker":"mock",
    "execution_type":"REBALANCE",
    "orders":[
      {"symbol":"TCS","quantity":1,"side":"SELL","action":"SELL"},
      {"symbol":"RELIANCE","quantity":3,"side":"BUY","action":"BUY"},
      {"symbol":"INFY","quantity":2,"side":"BUY","action":"ADJUST"}
    ]
  }'
```

The response reports an execution ID, status (`SUCCESS`, `PARTIAL_FAILURE`, or `FAILURE`), counts, normalized per-order results, broker IDs where available, error codes, and retry attempts. `ACCEPTED` means the broker/mock accepted the request; it is not a claim of exchange fill.

To demonstrate partial failure through the running mock container, start it with `KALPI_MOCK_FAIL_SYMBOLS=FAIL` and submit a rebalance containing both `GOOD` and `FAIL`. That setting only changes the deterministic mock; it has no effect on named broker adapters.

## Reliability and trading safety

Every execution requires an `Idempotency-Key`. The service hashes the normalized request and reserves the key before starting order placement.

- Same key + same normalized payload returns the original execution result and does not create another mock order or notification.
- Same key + different payload returns HTTP 409.
- Concurrent same-key requests wait for the single owner and receive its result.
- The current repository stores reservations in memory. They are lost on process restart; a production replacement should persist request fingerprint, execution state, order client references, and result in a database with a unique key constraint.

Retry semantics are deliberately conservative:

| Outcome | Engine behavior |
| --- | --- |
| Known pre-acceptance transient/rate-limit failure | Retry up to `KALPI_RETRY_ATTEMPTS` with bounded backoff |
| Known broker rejection | Return `REJECTED`; do not retry |
| Ambiguous placement timeout/network outcome | Return `AMBIGUOUS`; do not retry |
| Successful broker acceptance | Return `ACCEPTED`; reconcile actual fill later through provider status/postbacks |

The console notification includes execution ID, broker, final status, successful trades, and failed trades. A production notification implementation should use a durable outbox plus webhook/email/WebSocket delivery.

## Configuration and security

Copy `.env.example` for local development. Relevant settings are:

- `KALPI_LIVE_TRADING_ENABLED=false` - safety switch; named provider execution is blocked by default.
- `KALPI_RETRY_ATTEMPTS=3` - bounded to 1-5.
- `KALPI_RETRY_BACKOFF_SECONDS=0.0` - bounded backoff for safe retries only.
- `KALPI_IDEMPOTENCY_WAIT_SECONDS=30` - max wait for a concurrent duplicate request.
- `KALPI_LOG_LEVEL=INFO`.
- `KALPI_MOCK_FAIL_SYMBOLS=` - comma-separated deterministic mock rejections for local/demo testing only.

No credentials, API keys, access tokens, private keys, local databases, or `.env` file are included. `.gitignore` excludes runtime configuration, virtual environments, test cache, bytecode, coverage, and work files.

## Testing

```bash
pytest -q
python -m compileall app tests
```

The suite covers health/broker routes, first-time BUY, explicit SELL/BUY/ADJUST rebalance behavior, invalid inputs, unsupported brokers, named-adapter safety, authentication failures, partial failures, same-key replay, different-payload conflict, concurrent duplicates, safe retries, rejected orders, ambiguous timeouts, mock status/cancel lifecycle, provider translation boundaries, and notification invocation.

## Problem 2 - multi-frequency data platform

The full 1,000-1,500 word design is in [docs/multi_frequency_financial_data_design.md](docs/multi_frequency_financial_data_design.md). The diagram is in [docs/architecture.mmd](docs/architecture.mmd).

It uses Kafka/Redpanda as the replayable stream boundary, ClickHouse for compressed tick/EOD analytical data, PostgreSQL for versioned fundamentals, Redis for live and historical cache, and S3/Parquet for archive. Historical P/E uses historical price plus the latest fundamental version whose `available_at <= calculation_timestamp`, preventing the look-ahead bias of using today's EPS for a 2022 price.

## Dependencies and production limitations

FastAPI provides routing and OpenAPI, Pydantic provides schema validation, Uvicorn runs ASGI, and pytest/HTTPX test real application behavior. No third-party broker normalization library is used because broker authentication, instrument identifiers, response semantics, and regulatory obligations are provider-specific and must remain visible at the adapter boundary.

This is a take-home implementation, not a live trading deployment. Before production, add a durable execution/idempotency store, encrypted secret management, verified official clients, per-broker rate limits/timeouts/circuit breakers, current instrument-master resolution, pre-trade risk checks, reconciliation through status/postbacks, a durable notification outbox, audit controls, observability, and an explicit deployment approval process for any live-trading switch.
