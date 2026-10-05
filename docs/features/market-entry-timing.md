# Market Entry Timing

## Purpose

Market Entry Timing recommends whether to book freight now or wait. It combines forecast direction, current freight, route disruption, cyclone/weather factors, and a SPOT-versus-COA cost comparison.

## Endpoint

```http
POST /api/v1/market-entry-timing
Content-Type: application/json
```

## Request

```json
{
  "origin_port": "Abbot Point (NQXT)",
  "destination_port": "Paradip",
  "cargo_quantity_mt": 210000,
  "cargo_type": "Coking Coal",
  "vessel_type": "Panamax",
  "contract_duration_months": 3
}
```

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `origin_port` | string | Yes | Loading port name, matched case-insensitively |
| `destination_port` | string | Yes | Discharge port name, matched case-insensitively |
| `cargo_quantity_mt` | number | Yes | Cargo quantity per shipment |
| `cargo_type` | string | Yes | Cargo category |
| `vessel_type` | string | Yes | Vessel class name |
| `contract_duration_months` | number | Yes | Contract horizon used for voyages and forecast; normally 1–24 months |

The current Pydantic request model does not enforce numeric minimum/maximum values. Clients should nevertheless send positive quantities and a positive contract duration.

## Decision response — `200 OK`

```json
{
  "verdict": "BOOK",
  "confidence_pct": 78,
  "reason": "Freight rates are forecast to strengthen; booking now locks in better pricing.",
  "score": 56.4,
  "expected_rate_change_pct": 4.25,
  "top_factors": [
    {"factor": "Freight Forecast", "impact": 21.3, "summary": "Expected to rise 4.3% over the horizon"},
    {"factor": "Geopolitical Disruption", "impact": -10.0, "summary": "Active disruption flagged on/near the selected route"}
  ],
  "contract_strategy": {
    "recommendation": "COA",
    "confidence": "HIGH",
    "comparison": {
      "spot": {"rate_per_mt": 7.25, "voyages_estimated": 3, "total_mt": 630000, "total_cost": 4567500.0},
      "coa": {"duration_months": 3, "rate_per_mt": 6.8, "voyages_estimated": 3, "total_mt": 630000, "total_cost": 4284000.0, "vs_spot_label": "Saves $283,500 (6.2% cheaper than spot)"}
    },
    "reasons": [
      "Because rates are forecast to strengthen, securing a COA now protects against further increases.",
      "COA estimate based on forecasted rates; not actual negotiated rates."
    ]
  }
}
```

`verdict` is `BOOK`, `WAIT`, or `NEUTRAL`. `score` is clamped to `-100..100`; positive values favor booking. The contract recommendation is `SPOT` or `COA`, with `LOW`, `MEDIUM`, or `HIGH` confidence.

## Feasibility/data failure — `200 OK`

The endpoint currently returns a structured failure body rather than an HTTP error when a port, vessel, route, or required feasibility condition cannot be resolved:

```json
{
  "feasible": false,
  "reason": "Origin port 'Unknown Port' not found."
}
```

Possible reasons include origin/destination port not found, vessel type not found or unsupported, vessel incompatibility with port limits, and missing route distance.

## Processing flow

1. Resolve named ports and vessel class.
2. Check vessel draft, LOA, and beam at both ports.
3. Resolve route distance and estimate voyage geometry.
4. Calculate current rate and forecasted rate direction.
5. Score freight, geopolitical, and cyclone/weather factors.
6. Compare SPOT cost with average forecasted COA cost over the contract duration.

## Errors

| Status | When it occurs |
| --- | --- |
| `200` | Decision response or structured feasibility/data failure |
| `422` | Missing/wrongly typed request field or malformed JSON |

Validation errors use FastAPI's standard envelope:

```json
{
  "detail": [
    {"type": "missing", "loc": ["body", "vessel_type"], "msg": "Field required"}
  ]
}
```

## Implementation

- Request/response models: `app/schemas/market_entry_timing.py`
- Endpoint and scoring: `app/routers/market_entry_timing.py`
- Forecast data: `app/services/freight_prediction.py`
- Port and route records: `app/models/`
