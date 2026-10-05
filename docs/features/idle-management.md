# Idle Management

Idle Management identifies vessel gaps between charter assignments and evaluates ways to use or reposition a vessel during the gap. It has a database-backed idle-gap API and a charter-scenario API using demo charter records.

## 1. Idle gaps

### List gaps

```http
GET /idle/gaps
```

### Response — `200 OK`

```json
[
  {
    "vessel_id": "550e8400-e29b-41d4-a716-446655440000",
    "vessel_name": "MV Ocean Horizon",
    "gap_start_date": "2026-10-02",
    "gap_end_date": "2026-10-12",
    "gap_length_days": 10
  }
]
```

The endpoint returns an array, which can be empty. A gap is included when the interval between consecutive charter records is at least three days.

### Get options for a gap

```http
GET /idle/gaps/550e8400-e29b-41d4-a716-446655440000/options?gap_start=2026-10-02&gap_end=2026-10-12
```

| Parameter | Type | Required | Description |
| --- | --- | --- | --- |
| `vessel_id` (path) | UUID | Yes | Vessel record ID |
| `gap_start` (query) | date (`YYYY-MM-DD`) | Yes | Gap start date |
| `gap_end` (query) | date (`YYYY-MM-DD`) | Yes | Gap end date |

### Response — `200 OK`

```json
{
  "vessel_id": "550e8400-e29b-41d4-a716-446655440000",
  "vessel_name": "MV Ocean Horizon",
  "options": [
    {"option_type": "hold", "estimated_cost": 20000.0, "estimated_benefit": 0.0, "description": "Hold position at current port for 10 days."},
    {"option_type": "reposition", "estimated_cost": 138461.54, "estimated_benefit": 0.0, "description": "Reposition to high-demand region. Estimated 3.2 days sailing."},
    {"option_type": "short_fixture", "estimated_cost": 142461.54, "estimated_benefit": 150000.0, "description": "Take a short spot fixture for 10 days."}
  ]
}
```

`option_type` is `hold`, `reposition`, or `short_fixture`. These are estimates based on the current MVP assumptions.

## 2. Charter idle scenario

### List available scenario charters

```http
GET /api/v1/idle-scenario/charters
```

### Response — `200 OK`

```json
[
  {
    "charter_id": "CHT-2026-0417",
    "vessel_name": "MV Ocean Horizon",
    "vessel_type": "Panamax",
    "current_status": "Discharging at Paradip",
    "expected_discharge_complete": "2026-09-26"
  }
]
```

### Evaluate a charter

```http
POST /api/v1/idle-scenario
Content-Type: application/json
```

```json
{"charter_id": "CHT-2026-0417"}
```

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `charter_id` | string | Yes | ID returned by the charter-list endpoint |

### Response — `200 OK`

```json
{
  "vessel_name": "MV Ocean Horizon",
  "vessel_type": "Panamax",
  "charter_id": "CHT-2026-0417",
  "current_status": "Discharging at Paradip",
  "current_position": {"port": "Paradip", "lat": 20.31, "lng": 86.68},
  "expected_discharge_complete": "2026-09-26",
  "next_fixture": null,
  "forecasted_idle_windows": [
    {"start_date": "2026-09-26", "end_date": null, "status": "open-ended", "location": "Paradip anchorage"}
  ],
  "alternative_employment": [
    {"route": "Paradip → Visakhapatnam", "cargo_type": "Iron Ore", "cargo_qty_mt": 60000, "estimated_rate_per_mt": 6.8, "ballast_distance_nm": 210, "fit_score": 86, "data_note": "Simulated listing"}
  ],
  "repositioning_savings": {
    "best_option": "Paradip → Visakhapatnam",
    "estimated_backhaul_revenue": 408000.0,
    "estimated_ballast_fuel_cost": 27431.0,
    "estimated_savings_usd": 380569.0,
    "basis": "Backhaul cargo revenue minus ballast leg fuel cost, compared against zero revenue while idle at anchor"
  },
  "data_disclaimer": "Alternative employment listings are simulated for demo purposes."
}
```

The scenario fit score is `100 - (ballast_distance_nm / 10) + (estimated_rate_per_mt × 2)`, capped to `0..100`. Idle windows may be bounded or `open-ended`; `repositioning_savings` may be `null` if no alternative exists.

## Errors

| Endpoint | Status | When it occurs |
| --- | --- | --- |
| `/idle/gaps` | `200` | Always returns an array; it may be empty |
| `/idle/gaps/{vessel_id}/options` | `404` | Vessel does not exist or no options are available |
| `/idle/gaps/{vessel_id}/options` | `422` | Invalid UUID or date format |
| `/api/v1/idle-scenario` | `404` | Charter ID is not in the demo registry |
| `/api/v1/idle-scenario` | `422` | Missing/wrongly typed `charter_id` |

Standard error example:

```json
{"detail": "Charter 'UNKNOWN' not found. Available: ['CHT-2026-0417', 'CHT-2026-0389', 'CHT-2026-0402']"}
```

## Implementation

- Database-backed routes: `app/routers/idle.py`, `app/services/idle_management.py`
- Scenario routes/calculations: `app/routers/idle_scenario.py`
- Contracts: `app/schemas/idle_management.py`
