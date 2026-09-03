# Vessel Type Optimization

**Feature Priority:** P1  
**Problem Statement:** PS 26006 — Intelligent Freight Forecasting Model for Vessel Chartering (Ministry of Steel / SAIL, Smart India Hackathon 2026)

---

## What it does

Given a trade route (loading port → discharge port) and a cargo quantity in metric tons, this feature recommends the best-fitting vessel class to carry the cargo.

It never returns a black box answer — every rejection is explained, every unverified constraint is flagged, and the reasoning is always included in the response.

---

## Files

```
app/
  models/
    port.py                      — Port DB model (SQLAlchemy)
    vessel_class.py              — VesselClass DB model (SQLAlchemy)
  schemas/
    vessel_optimization.py       — Pydantic request/response models
  services/
    vessel_optimization.py       — Core algorithm (pure Python, no FastAPI deps)
  routers/
    vessel_optimization.py       — POST /api/vessel-optimization
  seeds/
    seed.py                      — Seed script for vessel classes + ports
```

---

## Data model

### VesselClass

Seeded from a peer-reviewed AIS-tracking dataset. These figures are fixed — do not change them without a source.

| Class            | DWT     | Draft (m) | LOA (m) | Beam (m)       |
|------------------|---------|-----------|---------|----------------|
| Small Handysize  | 11,568  | 9         | 132     | null           |
| Large Handysize  | 27,834  | 10        | 177     | null           |
| Handymax         | 54,049  | 12        | 227     | null           |
| Panamax          | 82,618  | 12        | 288     | 32.3 (canal limit, not confirmed built-beam) |
| Capesize         | 156,000 | 18        | 295     | 46.5           |

### Port

Two port types enforced via enum: `LOADING` and `DISCHARGE`.

- **Discharge ports** — Indian ports only (fixed by the PS text): Paradip, Visakhapatnam Outer/Inner, Gangavaram, Dhamra, Gopalpur, Haldia Dock Complex, Sagar-Sandheads.
- **Loading ports** — Australia, USA, Mozambique, Indonesia (31 ports total).

Draft is stored as a single static conservative figure per port. Tide-aware / tidal-window logic is out of scope for this MVP — this is an intentional scoping decision, not a missed feature.

Port constraints with `null` values mean the figure was not found in research. They are treated as **unverified**, not as zero or no-limit. See Filter 1 below.

---

## Algorithm — 4 sequential filters

### Filter 0 — Route validity

Runs before any physical check. Validates that the given ports are in the correct trade direction.

```
if loading_port.type != LOADING  → 400 error
if discharge_port.type != DISCHARGE → 400 error
```

**Why this exists:** Without this guard, passing an Indian port as `loading_port_id` would pass all physical checks, since draft/LOA filters have no concept of trade direction.

---

### Filter 1 — Physical feasibility (hard gate)

For each vessel class, checks three constraints against both ports:

**Draft**
```
vessel.draft <= min(loading_port.max_draft, discharge_port.max_draft)
```

**LOA (Length Overall)**
```
vessel.loa <= min(loading_port.max_loa, discharge_port.max_loa)
```

**Beam**
```
vessel.beam <= min(loading_port.max_beam, discharge_port.max_beam)
```

Null handling rule: if a port's constraint field is `null`, **skip that specific check** for that port — but add a warning to the response: `"Beam constraint unverified for <port name>"`. Do not reject on missing data.

Any vessel that fails even one constraint is hard-rejected with a specific reason, e.g.:
> `"Capesize rejected: draft 18m exceeds Paradip's 14.5m limit"`

---

### Filter 2 — Capacity

For each vessel that passed Filter 1:

```
voyages_needed = ceil(cargo_quantity / vessel.dwt)
```

---

### Filter 3 — Cost ranking

```
total_cost = (freight_rate_per_voyage × voyages_needed)
           + handling_cost
           + congestion_risk
           + demurrage_estimate
```

The vessel with the lowest `total_cost` is recommended.

**Note:** Freight rate, handling cost, congestion risk, and demurrage are currently stubbed as pluggable function parameters (all return `0.0`). They will be replaced by the P2/P4 modules without changing this algorithm. Since all stubs return 0, the current ranking falls back to fewest voyages needed (largest eligible vessel).

---

## API

### `POST /api/vessel-optimization`

**Request**
```json
{
  "loading_port_id": "0e1a74ca-374f-40b4-b1b8-86bd8ce0b822",
  "discharge_port_id": "3f1fc772-830c-47cd-88b2-a94ff542c7ae",
  "cargo_quantity": 50000
}
```

**Response**
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
      "rejection_reason": "Capesize rejected: draft 18m exceeds Paradip's 14.5m limit; LOA 295m exceeds Newcastle — PWCS Carrington's 275m limit"
    }
  ],
  "warnings": []
}
```

**Error responses**

| Status | Cause |
|--------|-------|
| 400 | Port passed in wrong trade direction (Filter 0) |
| 400 | No vessel class can physically serve the route |
| 404 | Port ID not found in DB |
| 422 | Malformed UUID in request body |

---

## Running locally

**Seed the DB** (safe to re-run — skips if already seeded):
```
python -m app.seeds.seed
```

**Start the server:**
```
venv\Scripts\uvicorn.exe app.main:app --reload
```

---

## Extending cost functions (P2/P4)

The four cost stubs in `app/services/vessel_optimization.py` are designed to be swapped out:

```python
def optimize_vessel(
    ...
    freight_rate_fn=stub_freight_rate_per_voyage,
    handling_cost_fn=stub_handling_cost,
    congestion_risk_fn=stub_congestion_risk,
    demurrage_fn=stub_demurrage_estimate,
)
```

Pass your real implementations as arguments — no changes needed inside the algorithm itself.
