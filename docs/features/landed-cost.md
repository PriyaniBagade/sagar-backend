# Landed Cost

## Purpose

The landed-cost feature estimates the total cost of moving cargo from an origin port to a destination port. With a cargo price it returns landed cost; without one it returns shipping cost only.

## Endpoint

```http
POST /api/v1/landed-cost
Content-Type: application/json
```

## Request

```json
{
  "vessel_class_id": "7c1e9b2a-6a3d-4b2d-9e2a-123456789abc",
  "origin_port_id": "550e8400-e29b-41d4-a716-446655440000",
  "destination_port_id": "6ba7b810-9dad-11d1-80b4-00c04fd430c8",
  "cargo_quantity_mt": 50000,
  "cargo_type": "coking coal",
  "cargo_price_per_mt": 125.0,
  "insurance_rate_pct": 0.5
}
```

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `vessel_class_id` | UUID string | Yes | — | Vessel-class record ID |
| `origin_port_id` | UUID string | Yes | — | Loading port record ID |
| `destination_port_id` | UUID string | Yes | — | Discharge port record ID |
| `cargo_quantity_mt` | number | Yes | — | Cargo quantity in metric tons |
| `cargo_type` | string | Yes | — | Cargo category |
| `cargo_price_per_mt` | number | No | `null` | Cargo value per metric ton; enables landed-cost mode |
| `insurance_rate_pct` | number | No | `0.5` | Insurance percentage when cargo price is supplied |

## Successful response — `200 OK`

```json
{
  "feasible": true,
  "breakdown": {
    "num_voyages": 1,
    "vessel_capacity_mt": 82618,
    "voyage_days": 28.42,
    "sailing_days": 17.5,
    "load_days": 4.13,
    "discharge_days": 6.79,
    "distance_nm": 6300,
    "route_type": "suez",
    "freight_cost_usd": 182450.0,
    "origin_port_charges_usd": 25000.0,
    "destination_port_charges_usd": 18000.0,
    "cargo_value_usd": 6250000.0,
    "insurance_usd": 35771.25,
    "insurance_rate_pct": 0.5,
    "insurance_basis": "0.5% × (cargo value + freight) × 1.10 [Institute Cargo Clauses convention]",
    "total_usd": 6511221.25,
    "total_per_mt_usd": 130.2244,
    "mode": "landed_cost",
    "index_used": "BPI",
    "index_points": 1410,
    "freight_rate_per_mt_usd": 3.649
  }
}
```

When `cargo_price_per_mt` is omitted, `mode` is `shipping_cost`, the cargo-value and insurance fields are `null`, and the total contains freight plus port charges only.

## Feasibility failure — `200 OK`

Feasibility failures are returned as a normal response and do not include a `breakdown`:

```json
{
  "feasible": false,
  "reason": "Vessel physically incompatible with this route: panamax draft (12m) exceeds Port A's limit (10m)."
}
```

This response is used when the vessel class is missing/unsupported, a port is missing, the vessel violates draft/LOA/beam limits, or no route distance is seeded.

## Calculation flow

1. Resolve vessel class and both ports.
2. Check draft, LOA, and beam against both ports.
3. Resolve the seeded route distance and route type.
4. Read the latest market index and use the configured fallback when no feature row exists.
5. Calculate voyages, sailing/load/discharge days, canal time, freight, and port charges.
6. Add cargo value and insurance when cargo price is supplied.

## Errors

| Status | When it occurs |
| --- | --- |
| `200` | Successful calculation or structured feasibility failure |
| `422` | Missing/wrongly typed field or invalid UUID in a UUID field |

Validation errors use FastAPI's standard shape:

```json
{
  "detail": [
    {"type": "value_error", "loc": ["body", "origin_port_id"], "msg": "Value error, 'not-a-uuid' is not a valid UUID"}
  ]
}
```

## Implementation

- Request/response contract: `app/schemas/landed_cost.py`
- Endpoint and calculation: `app/routers/landed_cost.py`
- Shared vessel/port data: `app/models/`
- Route distance: `app/models/route_distance.py`
- Vessel cost assumptions: `app/config/vessel_cost.py`