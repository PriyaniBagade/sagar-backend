# SAGAR Backend

> FastAPI services for freight forecasting, vessel selection, landed-cost analysis, market timing, route risk, and idle-vessel management.

## Contents

- [1. Project Overview](#1-project-overview)
- [2. System Architecture](#2-system-architecture)
- [3. Backend Responsibilities](#3-backend-responsibilities)
- [4. Technology Stack](#4-technology-stack)
- [5. Repository Structure](#5-repository-structure)
- [6. Prerequisites](#6-prerequisites)
- [7. Local Installation](#7-local-installation)
- [8. Environment Configuration](#8-environment-configuration)
- [9. Database Initialization](#9-database-initialization)
- [10. Running the API](#10-running-the-api)
- [11. API Reference](#11-api-reference)
- [12. Forecasting and Models](#12-forecasting-and-models)
- [13. Data Ingestion and Scheduler](#13-data-ingestion-and-scheduler)
- [14. Running the Complete System](#14-running-the-complete-system)
- [15. Verification Checklist](#15-verification-checklist)
- [16. Troubleshooting](#16-troubleshooting)
- [17. Current Limitations](#17-current-limitations)

## 1. Project Overview

SAGAR is a backend platform for dry-bulk freight and vessel-chartering decisions. It receives route, cargo, vessel, and market inputs; applies business rules and forecasting models; and returns structured results for the frontend.

The backend is the source of truth for:

- ports and vessel classes;
- freight-index forecasts;
- route and vessel feasibility;
- freight and landed-cost calculations;
- market-entry recommendations;
- risk assessments;
- idle-vessel scenarios; and
- analysis history.

The frontend is located in the sibling `freight-forecast` folder.

## 2. System Architecture

```text
                         ┌─────────────────────┐
                         │  freight-forecast    │
                         │  Next.js frontend    │
                         └──────────┬──────────┘
                                    │ HTTP/JSON
                         ┌──────────▼──────────┐
                         │     SAGAR API        │
                         │ FastAPI + Uvicorn    │
                         └──────┬───────┬──────┘
                                │       │
                 ┌──────────────▼─┐ ┌─▼────────────────┐
                 │ PostgreSQL       │ │ LightGBM models  │
                 │ operational data │ │ models_output/   │
                 └──────────────┬──┘ └──────────────────┘
                                │
                         ┌──────▼──────┐
                         │ Data jobs    │
                         │ scrapers     │
                         │ features     │
                         │ retraining   │
                         └─────────────┘
```

## 3. Backend Responsibilities

### Decision modules

| Module | Purpose | Main route group | Detailed documentation |
| --- | --- | --- | --- |
| Freight Forecasting | Predict BDI, BCI, BPI, and BSI values | `/api/v1/forecast/*` | [Feature docs](docs/features/freight-forecasting.md) |
| Vessel Optimization | Check route feasibility and recommend a vessel class | `/api/vessel/*` | [Feature docs](docs/features/vessel_type_optimization.md) |
| Landed Cost | Calculate shipping or total landed cost | `/api/v1/landed-cost` | [Feature docs](docs/features/landed-cost.md) |
| Market Entry Timing | Recommend `BOOK` or `WAIT` and compare `SPOT`/`COA` | `/api/v1/market-entry-timing` | [Feature docs](docs/features/market-entry-timing.md) |
| Risk Mitigation | Identify weather, bunker, port, and disruption risks | `/risk/summary`, `/api/v1/risk-mitigation` | [Feature docs](docs/features/risk-management.md) |
| Idle Management | Find idle windows and alternative employment | `/idle/*`, `/api/v1/idle-scenario*` | [Feature docs](docs/features/idle-management.md) |

### Supporting services

- Reference-data endpoints for ports and vessel classes.
- Market snapshot for the overview dashboard.
- Analysis-log endpoint for recent user calculations.
- Scrapers for market, weather, port, and disruption signals.
- Daily feature-building pipeline.
- Monthly LightGBM retraining process.

## 4. Technology Stack

- **Language:** Python
- **API:** FastAPI, Uvicorn
- **Validation:** Pydantic
- **Database:** PostgreSQL with SQLAlchemy/SQLModel
- **Forecasting:** LightGBM, joblib, Pandas, NumPy
- **Data collection:** Requests, BeautifulSoup, external APIs
- **Scheduling:** APScheduler

## 5. Repository Structure

```text
SAGAR/
├── app/
│   ├── main.py                 FastAPI application entry point
│   ├── config/                 Database configuration
│   ├── models/                 Database models
│   ├── schemas/                API request/response contracts
│   ├── routers/                HTTP route handlers
│   ├── services/               Business logic and model inference
│   ├── scrapers/               External data collectors
│   ├── jobs/                   Ingestion, features, scheduler, retraining
│   └── seeds/                  Reference and demonstration data
├── models_output/              LightGBM model artifacts
├── data/                       Supporting data files
├── docs/                       Detailed feature documentation
├── requirements.txt            Python dependencies
├── .env.example                Environment-variable template
└── README.md                   This document
```

## 6. Prerequisites

Install the following before setup:

1. Python 3.11 or a version compatible with `requirements.txt`.
2. PostgreSQL.
3. Git, if the repository is being cloned.
4. Network access for external data sources used by scrapers.

Verify Python:

```bash
python --version
```

## 7. Local Installation

Run these commands from the `SAGAR` directory:

### Windows

```powershell
python -m venv venv
venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### macOS/Linux

```bash
python3 -m venv venv
source venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

## 8. Environment Configuration

Copy `.env.example` to `.env` and set the PostgreSQL connection string:

```env
DATABASE_URL=postgresql://user:password@host:5432/database_name?sslmode=require
```

For a local database, an example is:

```env
DATABASE_URL=postgresql://postgres:your_password@localhost:5432/sagar
```

`DATABASE_URL` is mandatory. Never commit `.env` or place credentials in source code.

## 9. Database Initialization

The application registers its models and creates missing tables at startup using `Base.metadata.create_all`. It does not automatically seed reference records.

After PostgreSQL and `.env` are ready, run:

```bash
python -m app.seeds.seed
python -m app.seeds.seed_idle
```

The first command seeds ports and vessel classes. The second command seeds idle-management records used by the idle scenario module.

## 10. Running the API

Start the development server from `SAGAR` with the virtual environment active:

```bash
uvicorn app.main:app --reload
```

On Windows, the explicit executable path is also supported:

```powershell
venv\Scripts\uvicorn.exe app.main:app --reload
```

The API is available at:

- Base URL: <http://localhost:8000>
- Health check: <http://localhost:8000/health>
- Swagger UI: <http://localhost:8000/docs>
- OpenAPI schema: <http://localhost:8000/openapi.json>

## 11. API Reference

The generated Swagger page at `/docs` contains exact request fields, response fields, validation rules, and interactive examples. The route inventory below provides a quick orientation.

### Health and reference data

```text
GET /                     API status
GET /health               Health status
GET /api/ports            Ports; optional ?port_type=LOADING or DISCHARGE
GET /api/vessel-classes   Vessel classes
GET /api/market/snapshot  Dashboard market snapshot
GET /api/v1/analysis-log  Recent analysis records
```

### Freight forecasting

Detailed request/response contracts and error behavior: [freight forecasting feature documentation](docs/features/freight-forecasting.md).

```text
GET  /api/v1/forecast/all?days=7
GET  /api/v1/forecast/{index}?days=7
GET  /api/v1/forecast/{index}/history?lookback_days=30
POST /api/v1/forecast/predict
POST /api/v1/forecast/signal
```

Supported indices are `bdi`, `bci`, `bpi`, and `bsi`.

### Vessel and cost decisions

Detailed contracts: [vessel optimization](docs/features/vessel_type_optimization.md), [landed cost](docs/features/landed-cost.md), and [market entry timing](docs/features/market-entry-timing.md).

```text
POST /api/vessel/optimization
POST /api/vessel/cost-summary
POST /api/v1/landed-cost
POST /api/v1/market-entry-timing
```

### Risk and idle management

Detailed contracts: [risk management](docs/features/risk-management.md) and [idle management](docs/features/idle-management.md).

```text
GET  /risk/summary?loading_port_id=<uuid>&discharge_port_id=<uuid>
POST /api/v1/risk-mitigation
GET  /idle/gaps
GET  /idle/gaps/{vessel_id}/options?gap_start=YYYY-MM-DD&gap_end=YYYY-MM-DD
GET  /api/v1/idle-scenario/charters
POST /api/v1/idle-scenario
```

## 12. Forecasting and Models

The backend currently loads these model files:

```text
models_output/bdi_lightgbm_model.joblib
models_output/bci_lightgbm_model.joblib
models_output/bpi_lightgbm_model.joblib
models_output/bsi_lightgbm_model.joblib
```

The forecast flow is:

1. Source values are collected by scrapers.
2. Ingestion stores validated source rows.
3. Feature building creates model features.
4. The forecast service loads the appropriate LightGBM model.
5. API routes return forecasts, ranges, history, and related decisions.

## 13. Data Ingestion and Scheduler

The scheduler is independent of Uvicorn. Starting the API does not start scheduled jobs.

Start the scheduler:

```bash
python -m app.jobs.scheduler
```

Scheduled work runs in UTC:

- **Daily at 00:00 UTC:** ingest sources, build features, save actuals, and generate one-day forecasts.
- **First day of each month at 00:00 UTC:** retrain forecasting models and promote accepted models.

Run jobs manually:

```bash
python -m app.jobs.scheduler --daily
python -m app.jobs.scheduler --retrain
python -m app.jobs.scheduler --now
```

Current source adapters cover BDI, bunker prices, coking coal, steel production, manufacturing PMI, cyclones, rainfall, geopolitical disruption, Malacca traffic, port activity, and seasonality.

## 14. Running the Complete System

Use two terminals.

### Terminal 1 — backend

```bash
cd SAGAR
venv\Scripts\Activate.ps1
uvicorn app.main:app --reload
```

### Terminal 2 — frontend

```bash
cd freight-forecast
npm install
npm run dev
```

Open <http://localhost:3000>. Configure the frontend with:

```env
NEXT_PUBLIC_API_URL=http://localhost:8000
```

## 15. Verification Checklist

Before reporting that the local setup is working, verify:

- [ ] PostgreSQL is running.
- [ ] `SAGAR/.env` contains a valid `DATABASE_URL`.
- [ ] Dependencies installed successfully.
- [ ] Seed scripts completed.
- [ ] `GET /health` returns `{"status":"ok"}`.
- [ ] `GET /api/ports` returns port records.
- [ ] `GET /api/vessel-classes` returns vessel classes.
- [ ] Swagger opens at `/docs`.
- [ ] Frontend opens at `http://localhost:3000`.
- [ ] Frontend API URL points to the running backend.

## 16. Troubleshooting

### `DATABASE_URL is missing`

Create `SAGAR/.env` and add a valid PostgreSQL URL.

### Database connection error

Confirm PostgreSQL is running, the database exists, credentials are correct, and the host/port is reachable.

### Empty port or vessel dropdowns

Run:

```bash
python -m app.seeds.seed
```

### Model loading error

Confirm that all four `.joblib` files exist in `models_output/` and reinstall dependencies from `requirements.txt`.

### Frontend cannot reach the API

Check `http://localhost:8000/health`, then confirm the frontend contains `NEXT_PUBLIC_API_URL=http://localhost:8000`. Restart Next.js after editing `.env.local`.

### Scraper failure

External sources may be unavailable, rate-limited, or changed. Review scheduler logs and retry after checking network access.

## 17. Current Limitations

- Authentication and authorization are not implemented.
- CORS is currently configured permissively for development.
- Vessel optimization cost functions are currently zero-value stubs; ranking falls back to eligible capacity/voyage logic.
- Some idle-scenario records are seed/demo data.
- External scraper reliability depends on third-party services.
- Startup table creation is not a replacement for a production migration strategy.