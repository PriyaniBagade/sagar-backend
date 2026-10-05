# Risk Management

SAGAR exposes two related risk APIs: a compact route risk summary and a detailed risk-mitigation assessment.

## 1. Route risk summary

### Endpoint

```http
GET /risk/summary?loading_port_id=550e8400-e29b-41d4-a716-446655440000&discharge_port_id=6ba7b810-9dad-11d1-80b4-00c04fd430c8
```

| Query parameter | Type | Required | Description |
| --- | --- | --- | --- |
| `loading_port_id` | UUID | Yes | Loading port record ID |
| `discharge_port_id` | UUID | Yes | Discharge port record ID |

### Response — `200 OK`

```json
{
  "route": {"loading_port": "Abbot Point (NQXT)", "discharge_port": "Paradip"},
  "weather": {"risk": "LOW", "reason": "No active weather disruption"},
  "bunker": {"risk": "MEDIUM", "reason": "VLSFO price trend is rising"},
  "port_activity": {"risk": "MEDIUM", "reason": "High monitored-port activity; the aggregate is not stored per port"},
  "geopolitical": {"risk": "LOW", "reason": "No route-specific disruption flag"}
}
```

Each category has `risk` (`HIGH`, `MEDIUM`, or `LOW`) and a human-readable `reason`.

## 2. Risk mitigation

### Endpoint and request

```http
POST /api/v1/risk-mitigation
Content-Type: application/json
```

```json
{
  "origin_port": "Abbot Point (NQXT)",
  "destination_port": "Paradip"
}
```

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `origin_port` | string | Yes | Origin port name, matched case-insensitively |
| `destination_port` | string | Yes | Destination port name, matched case-insensitively |

### Response — `200 OK`

```json
{
  "cyclone_risk": {
    "origin": {"level": "LOW", "detail": "No active cyclonic systems within 500nm of Abbot Point (NQXT)."},
    "destination": {"level": "MODERATE", "detail": "Heavy rainfall recorded near Paradip; monsoon watch active."}
  },
  "port_congestion": {
    "origin": {"level": "LOW", "avg_wait_days": 0.5},
    "destination": {"level": "HIGH", "avg_wait_days": 4.2}
  },
  "bunker_fuel_price": {"vlsfo_usd_per_mt": 612.0, "trend_7d_pct": 1.85},
  "geopolitical_flags": [
    {"region": "Red Sea", "severity": "HIGH", "summary": "Ongoing shipping disruptions; rerouting advised."}
  ],
  "live_alerts": [
    {"timestamp": "2026-10-05T10:00:00Z", "severity": "HIGH", "source": "geopolitical", "message": "Red Sea: Ongoing shipping disruptions; rerouting advised."}
  ]
}
```

Risk-mitigation levels are `LOW`, `MODERATE`, or `HIGH`. Alerts contain only `MODERATE` and `HIGH` items and are sorted with `HIGH` first. `trend_7d_pct` may be `null` when a seven-day comparison row is unavailable.

## Error responses

Both endpoints use FastAPI's standard error envelope:

```json
{"detail": "Human-readable error message"}
```

| Endpoint | Status | When it occurs |
| --- | --- | --- |
| Both | `422` | Missing/wrongly typed query, path, or body value; malformed UUID for summary |
| `/risk/summary` | `404` | Port ID does not exist or risk service cannot resolve the route |
| `/api/v1/risk-mitigation` | `404` | Origin or destination port name does not exist |

Example validation response:

```json
{
  "detail": [
    {"type": "uuid_parsing", "loc": ["query", "loading_port_id"], "msg": "Input should be a valid UUID"}
  ]
}
```

## Processing flow

The summary evaluates latest feature-store values with fixed rules. Risk mitigation resolves ports by name, reads current and seven-day feature rows, evaluates cyclone/weather proxies, assigns port-congestion levels, calculates bunker trend, adds curated geopolitical flags, and builds live alerts.

## Implementation

- Summary route: `app/routers/risk_summary.py`
- Summary service and contract: `app/services/risk_summary.py`, `app/schemas/risk_summary.py`
- Mitigation route and contracts: `app/routers/risk_mitigation.py`
- Feature data: `app/models/feature_store.py`
