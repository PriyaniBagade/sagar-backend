# Vessel Type Optimization

## Purpose

Vessel Type Optimization recommends the best eligible vessel class for a loading-port/discharge-port route and cargo quantity. It explains accepted and rejected classes instead of returning an unexplained score.

## Endpoint

```http
POST /api/vessel/optimization
Content-Type: application/json
```

## Request

```json
{
  "cargo_type": "coking coal",
  "loading_port_id": "0e1a74ca-374f-40b4-b1b8-86bd8ce0b822",
  "discharge_port_id": "3f1fc772-830c-47cd-88b2-a94ff542c7ae",
  "cargo_quantity": 50000
}
```

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `cargo_type` | string | No | Free-text cargo category; may be `null` |
| `loading_port_id` | UUID string | Yes | Loading port record ID |
| `discharge_port_id` | UUID string | Yes | Discharge port record ID |
| `cargo_quantity` | number | Yes | Cargo quantity in metric tons |

## Response — `200 OK`

```json
{
  "recommended_class": "Handymax",
  "voyages_needed": 1,
  "eligible_classes": ["Small Handysize", "Large Handysize", "Handymax"],
  "rejected_classes": [
    {
      "vessel_class": "Panamax",
      "rejection_reason": "Panamax rejected: LOA 288m exceeds Newcastle — PWCS Carrington's 275m limit"
    },
    {
      "vessel_class": "Capesize",
      "rejection_reason": "Capesize rejected: draft 18m exceeds Paradip's 14.5m limit"
    }
  ],
  "explanation": "Handymax is the best eligible class for the requested cargo and route."
}
```

| Response field | Description |
| --- | --- |
| `recommended_class` | Selected eligible vessel class |
| `voyages_needed` | `ceil(cargo_quantity / vessel_dwt)` for the recommendation |
| `eligible_classes` | Classes that passed physical checks |
| `rejected_classes` | Class and specific rejection reason for each failure |
| `explanation` | Human-readable recommendation reasoning |

## Decision algorithm

1. Resolve both port IDs.
2. Validate trade direction: loading port must be `LOADING` and discharge port must be `DISCHARGE`.
3. Check draft, LOA, and beam against both ports. A `null` port constraint is treated as unverified and that check is skipped.
4. Calculate voyages for each eligible class.
5. Rank eligible classes using the configured cost functions. Current cost stubs return `0.0`, so the fallback effectively favors fewer voyages/larger eligible capacity.
6. Persist the request and recommendation in the vessel-request table.

## Errors

Errors use FastAPI's standard envelope:

```json
{"detail": "Human-readable error message"}
```

| Status | When it occurs |
| --- | --- |
| `400` | Loading/discharge port has the wrong trade direction, or no vessel class can serve the route |
| `404` | Loading or discharge port ID does not exist |
| `422` | Missing/wrongly typed field, malformed UUID, or malformed JSON |

Examples:

```json
{"detail": "Loading port ... not found"}
```

```json
{
  "detail": [
    {"type": "value_error", "loc": ["body", "loading_port_id"], "msg": "Value error, 'not-a-uuid' is not a valid UUID"}
  ]
}
```

## Data model and implementation

- Request/response models: `app/schemas/vessel_optimization.py`
- HTTP route: `app/routers/vessel_optimization.py`
- Core algorithm: `app/services/vessel_optimization.py`
- Port and vessel records: `app/models/port.py`, `app/models/vessel_class.py`
- Persisted request record: `app/models/vessel_request.py`

Supported seeded vessel classes include Small Handysize, Large Handysize, Handymax, Panamax, and Capesize. Port constraints are static conservative values; tide-aware windows are outside the current MVP.
