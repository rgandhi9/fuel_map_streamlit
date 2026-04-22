# ⛽ FleetFuel

**Live UK fuel price intelligence for fleet operators.**

FleetFuel helps logistics companies, fleet managers, and drivers make smarter refuelling decisions by surfacing live UK fuel prices, identifying the cheapest stops along a planned route, and calculating the real cost of a journey based on a specific vehicle's fuel consumption.

---

## What it does

### Price Overview
- Pulls live fuel prices from BigQuery
- Shows average, cheapest, and most expensive prices across all reporting stations
- Colour-coded map: green = cheapest, red = most expensive
- Filters by fuel type and brand
- Data freshness indicator per brand

### Vehicle Profiles
- Define named vehicles with MPG and tank size
- Set current fuel level via a slider — range is calculated automatically
- Add and remove vehicles within a session
- Three defaults pre-loaded: HGV (Artic), Transit Van, Company Car

### Route Cost Report
Enter a start and end location to get a full cost report:
- Route distance and estimated drive time (via Mapbox Directions)
- Whether a refuel is needed based on the active vehicle's current range
- **Recommended fuel stop** — the single cheapest reachable station along the route
- Cost comparison: best stop vs route average vs most expensive
- Annualised saving estimate for repeat routes
- Full ranked table of up to 10 reachable stops (collapsed by default)

---

## Architecture

```
┌─────────────────────┐     daily refresh      ┌─────────────────────┐
│  Fuel APIs          │ ──────────────────────▶│  Google BigQuery    │
│  (open, OCPI-based) │                        │  mart_latest_prices │
└─────────────────────┘                        └──────────┬──────────┘
                                                          │ query on load
                                               ┌──────────▼──────────┐
                                               │   Streamlit App     │
                                               │   (app.py)          │
                                               └──────────┬──────────┘
                                                          │
                                               ┌──────────▼───────────┐
                                               │   Mapbox API         │
                                               │   Geocoding +        │
                                               │   Directions         │
                                               └──────────────────────┘
```

- **Frontend**: [Streamlit](https://streamlit.io) — single `app.py`, no separate frontend build
- **Data warehouse**: Google BigQuery — queried directly via `google-cloud-bigquery`
- **Mapping**: [pydeck](https://deckgl.readthedocs.io) for the price map, [Mapbox](https://www.mapbox.com) for geocoding and routing
- **State**: Streamlit `session_state` — vehicle profiles persist within a session, reset on refresh

---

## Running locally

### Prerequisites
- Python 3.11+
- A Google Cloud service account with BigQuery read access
- A Mapbox API token

### Install dependencies
```bash
pip install -r requirements.txt
```

### Configure secrets
Create `.streamlit/secrets.toml`:

```toml
mapbox_access_token = "your_mapbox_token_here"

[gcp_service_account]
type = "service_account"
project_id = "your-project-id"
private_key_id = "..."
private_key = "-----BEGIN RSA PRIVATE KEY-----\n...\n-----END RSA PRIVATE KEY-----\n"
client_email = "your-service-account@your-project.iam.gserviceaccount.com"
client_id = "..."
auth_uri = "https://accounts.google.com/o/oauth2/auth"
token_uri = "https://oauth2.googleapis.com/token"
```

### Run
```bash
streamlit run app.py
```

App will be available at `http://localhost:8501`.

---

## Data notes

- Prices are sourced from open fuel price dataset, updated **daily**
- The API is currently open (no authentication required) as part of a pilot — this may change
- `mart_latest_prices` in BigQuery contains the most recent price per station per fuel type
- Historical price data is not currently stored — snapshots should be archived to BigQuery daily to build a trend dataset over time (see Roadmap)

---

## Roadmap

### Chunk 4 — Multi-stop routes
Allow more than A→B: enter multiple delivery stops and calculate optimal refuel points across the full journey.

### Chunk 5 — Price trend awareness
Surface whether today's prices are high or low relative to recent history. Requires daily archiving of price snapshots into BigQuery (straightforward addition to the ETL pipeline).

### Later / if validated
- Persistent vehicle profiles (database or Streamlit auth)
- Driver-facing mobile view
- Weekly fuel cost summary / fleet report export
- Price alerts — notify when a brand/region drops below a threshold
- Multi-vehicle fleet dashboard

---

## Project structure

```
├── app.py                  # Main Streamlit application
├── requirements.txt        # Python dependencies
├── .streamlit/
│   └── secrets.toml        # API keys and credentials (not committed)
└── .devcontainer/
    └── devcontainer.json   # GitHub Codespaces config
```

---

## Known limitations

- Vehicle profiles reset on page refresh (session state only)
- Route station matching uses straight-line geometry, not true road proximity — stations are filtered by detour distance, not road-network distance
- Data updates once daily; intraday price changes are not captured
- The fuel API has no guaranteed SLA and could change without notice
