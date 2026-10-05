# Freight Forecasting

## Purpose

Freight forecasting estimates the near-term movement of the dry-bulk indices used by SAGAR and converts an index forecast into a route-level freight estimate. The feature powers dashboard charts, route-rate predictions, market-entry decisions, and booking signals.

## Supported indices

| Code | Meaning |
| --- | --- |
| `bdi` | Baltic Dry Index |
| `bci` | Baltic Capesize Index |
| `bpi` | Baltic Panamax Index |
| `bsi` | Baltic Supramax Index |

All forecast horizons are expressed in business days. The maximum horizon is 30 days.

## Endpoints

| Method and path | Purpose |
| --- | --- |
| `GET /api/v1/forecast/all` | Forecast all four indices |
| `GET /api/v1/forecast/{index}` | Forecast one index |
| `GET /api/v1/forecast/{index}/history` | Compare stored predictions with actual values |
| `POST /api/v1/forecast/predict` | Estimate route freight rate per MT |
| `POST /api/v1/forecast/signal` | Return a booking/timing signal and SPOT/COA strategy |

`{index}` must be `bdi`, `bci`, `bpi`, or `bsi` (lowercase).

## 1. Forecast all indices

### Request

```http
GET /api/v1/forecast/all?days=7
```

| Query parameter | Type | Required | Default | Constraints |
| --- | --- | --- | --- | --- |
| `days` | integer | No | `1` | `1`–`30` |

### Response — `200 OK`

```json
{
  "forecast_horizon_days": 7,
  "indices": {
    "bdi": {
      "current_value": 1842.5,
      "forecast": [
        {"date": "2026-10-06", "predicted_value": 1856.2, "low": 1764.0, "high": 1948.4}
      ],
      "confidence_pct": 78
    },
    "bci": {"current_value": 3210.0, "forecast": [], "confidence_pct": 74},
    "bpi": {"current_value": 1410.0, "forecast": [], "confidence_pct": 72},
    "bsi": {"current_value": 980.0, "forecast": [], "confidence_pct": 70}
  }
}
```

`forecast` contains one item for each requested business day. Each item has `date`, `predicted_value`, `low`, and `high`. `current_value` may be `null` when no current observation is available.

## 2. Forecast one index

### Request

```http
GET /api/v1/forecast/bdi?days=7
```

| Parameter | Type | Required | Default | Constraints |
| --- | --- | --- | --- | --- |
| `index` (path) | string | Yes | — | `bdi`, `bci`, `bpi`, or `bsi` |
| `days` (query) | integer | No | `1` | `1`–`30` |

### Response — `200 OK`

```json
{
  "index": "bdi",
  "forecast_horizon_days": 7,
  "current_value": 1842.5,
  "forecast": [
    {"date": "2026-10-06", "predicted_value": 1856.2, "low": 1764.0, "high": 1948.4}
  ],
  "confidence_pct": 78
}
```

## 3. Forecast history

### Request

```http
GET /api/v1/forecast/bdi/history?lookback_days=90
```

| Parameter | Type | Required | Default | Constraints |
| --- | --- | --- | --- | --- |
| `lookback_days` (query) | integer | No | `90` | `1`–`365` |

### Response — `200 OK`

```json
{
  "index": "bdi",
  "lookback_days": 90,
  "history": [
    {"date": "2026-10-01", "predicted_value": 1810.0, "actual_value": 1798.0},
    {"date": "2026-10-02", "predicted_value": 1822.0, "actual_value": null}
  ],
  "mean_absolute_error_pct": 2.41
}
```

`actual_value` and `mean_absolute_error_pct` can be `null` when actual observations are not available.

## 4. Route freight prediction

This endpoint maps the vessel class to an index, checks port and vessel compatibility, finds the route distance, and converts the index forecast to USD/MT.

### Request

```http
POST /api/v1/forecast/predict
Content-Type: application/json
```

```json
{
  "origin_port": "550e8400-e29b-41d4-a716-446655440000",
  "destination_port": "6ba7b810-9dad-11d1-80b4-00c04fd430c8",
  "cargo_qty_mt": 50000,
  "cargo_type": "iron_ore",
  "vessel_type": "7c1e9b2a-6a3d-4b2d-9e2a-123456789abc",
  "forecast_horizon_days": 7
}
```

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `origin_port` | string | Yes | Origin port UUID |
| `destination_port` | string | Yes | Destination port UUID |
| `cargo_qty_mt` | number | Yes | Cargo quantity in metric tons |
| `cargo_type` | string | Yes | Cargo category |
| `vessel_type` | string | Yes | Vessel-class UUID |
| `forecast_horizon_days` | integer | No | Forecast horizon; defaults to `7` |

### Feasible response — `200 OK`

```json
{
  "feasible": true,
  "infeasibility_reason": null,
  "predicted_rate_per_mt": 12.4832,
  "confidence_range": {"low": 11.86, "high": 13.1},
  "confidence_pct": 78,
  "forecast_date": "2026-10-12",
  "based_on_index": "BCI"
}
```

### Infeasible response — `200 OK`

Feasibility failures are a successful API response, not an HTTP error. The client must check `feasible` before using the rate.

```json
{
  "feasible": false,
  "infeasibility_reason": "No shipping route found from Port A to Port B",
  "predicted_rate_per_mt": null,
  "confidence_range": null,
  "confidence_pct": null,
  "forecast_date": null,
  "based_on_index": null
}
```

Supported vessel-class mappings are `capesize → BCI`, `panamax → BPI`, and `supramax`, `handymax`, or `handysize → BSI`.

## 5. Forecast timing signal

### Request

```http
POST /api/v1/forecast/signal
Content-Type: application/json
```

```json
{
  "vessel_class": "panamax",
  "loading_port_id": "550e8400-e29b-41d4-a716-446655440000",
  "discharge_port_id": "6ba7b810-9dad-11d1-80b4-00c04fd430c8",
  "quantity_mt": 50000
}
```

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `vessel_class` | string | Yes | Vessel class name |
| `loading_port_id` | UUID string | Yes | Loading port UUID |
| `discharge_port_id` | UUID string | Yes | Discharge port UUID |
| `quantity_mt` | number | Yes | Cargo quantity in metric tons |

### Response — `200 OK`

```json
{
  "verdict": "BOOK_NOW",
  "confidence": 82,
  "reason": "Rates are forecast to strengthen.",
  "score": 64,
  "expected_bdi_change_pct": 4.25,
  "top_factors": [
    {"factor": "Freight trend", "impact": 35, "summary": "BDI is expected to rise."}
  ],
  "strategy_cards": [],
  "contract_strategy": {
    "recommendation": "SPOT",
    "score": 61,
    "confidence": "HIGH",
    "reasons": ["Positive near-term trend"],
    "factors": {
      "trend_percent": 4.25,
      "confidence_band_width": 4.7,
      "voyage_count": 1,
      "disruption_risk": false
    }
  }
}
```

`verdict` is `BOOK_NOW`, `HOLD`, or `WAIT`. `contract_strategy.recommendation` is `SPOT` or `COA`; its confidence is `HIGH`, `MEDIUM`, or `LOW`.

## Error responses

Unless stated otherwise, errors use FastAPI's standard envelope:

```json
{"detail": "Human-readable error message"}
```

Validation errors use a list in `detail`:

```json
{
  "detail": [
    {"type": "less_than_equal", "loc": ["query", "days"], "msg": "Input should be less than or equal to 30"}
  ]
}
```

| Status | When it occurs |
| --- | --- |
| `200` | Request processed; a route may still be infeasible in `forecast/predict` |
| `400` | Forecast service rejects a value while reading history or a single index |
| `404` | Vessel class, loading port, or discharge port does not exist |
| `422` | Invalid index, missing/wrongly typed body field, invalid UUID, or query value outside its bounds |
| `503` | Forecast model/data is unavailable, or the feature store is empty |

For `forecast/signal`, a missing port returns `404` and an empty feature store returns `503`. For `forecast/predict`, an unknown vessel class returns `404`; missing ports, unsupported vessel mappings, incompatible vessel dimensions, and missing route distances return `200` with `feasible: false`.

## Processing flow and implementation

1. The service loads current feature data from the database.
2. The matching LightGBM model predicts one or more future business days.
3. A confidence range is derived for each prediction.
4. Daily pipeline runs persist forecast rows for later predicted-vs-actual history.
5. Route prediction checks vessel/port constraints and route distance before calculating USD/MT.

Models are loaded from `models_output/`:

```text
bdi_lightgbm_model.joblib
bci_lightgbm_model.joblib
bpi_lightgbm_model.joblib
bsi_lightgbm_model.joblib
```

Request and response models are in `app/schemas/freight_prediction.py` and `app/schemas/forecast_signal.py`. HTTP handlers are in `app/routers/forecast.py` and `app/routers/forecast_signal.py`.

