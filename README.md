# GridWise Energy Optimization API

GridWise is an LLM-assisted energy management API for the BUP CSE Fest 2026 online preliminary hackathon. It converts natural-language operator notes into validated energy directives, applies those directives to a 24-hour campus energy scenario, and returns an optimized grid and battery schedule.

## What It Does

The API combines three stages:

1. **Directive interpretation:** Gemini classifies each operator note as one supported directive.
2. **Guardrail validation:** Pydantic models and custom validation verify the returned directive structure, note order, and hour ranges.
3. **Schedule optimization:** The solver minimizes grid energy cost while enforcing solar, battery, reserve, charging, discharging, and grid-cap constraints.

The final response includes the interpreted directives, a complete 24-hour plan, total grid usage, total cost, peak grid usage, and a short plan summary.

## Supported Directives

| Directive | Meaning |
| --- | --- |
| `solar_reduction` | Limits usable solar during selected hours with a remaining fraction from `0.0` to `1.0`. |
| `minimum_battery_reserve` | Raises the minimum battery energy allowed during selected hours. |
| `no_charge_window` | Prevents battery charging during selected hours. |
| `no_discharge_window` | Prevents battery discharging during selected hours. |
| `max_grid_window` | Caps grid import during selected hours. |
| `no_op` | Marks an irrelevant or ambiguous note as inactive. |

Time windows use start-inclusive, end-exclusive semantics. For example, 1 PM to 3 PM becomes `[13, 14]`.

## Requirements

- Python 3.12 or newer
- A Google Gemini API key
- `pip`
- CBC solver support through PuLP (included in the install command below)

## Configuration

Create a `.env` file in the project root:

```env
GOOGLE_API_KEY=your_gemini_api_key
```

Do not commit `.env` or expose the API key in client-side code. `.env` is already excluded by `.gitignore`.

## Run Locally

Create and activate a virtual environment, then install the dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt pulp
```

Start the development server:

```bash
uvicorn main:app --reload
```

The API is available at `http://127.0.0.1:8000`.

Interactive API documentation is available at:

- Swagger UI: `http://127.0.0.1:8000/docs`
- ReDoc: `http://127.0.0.1:8000/redoc`

## Run With Docker

Make sure `.env` exists, then build and start the service:

```bash
docker compose up --build
```

The container exposes the API on port `8000`.

## API Endpoints

### `GET /health`

Returns a basic service health response:

```json
{
	"status": "ok"
}
```

### `POST /optimize-energy`

Accepts one scenario. The request must contain:

- `scenario_id`: unique scenario identifier
- `operator_notes`: 1 to 3 natural-language notes
- `hours`: exactly 24 entries for hours `0` through `23`
- `battery`: battery capacity, initial energy, reserve, and charge/discharge limits

Example using the first public sample case:

```bash
curl -X POST "http://127.0.0.1:8000/optimize-energy" \
	-H "Content-Type: application/json" \
	--data-binary @<(python3 -c 'import json; print(json.dumps(json.load(open("BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json"))["cases"][0]["input"]))')
```

The response contains:

```json
{
	"scenario_id": "SAMPLE-01",
	"directive_interpretation": [],
	"hourly_plan": [],
	"total_grid_kwh": 0.0,
	"total_cost_bdt": 0.0,
	"peak_grid_kwh": 0.0,
	"plan_summary": "..."
}
```

The arrays are abbreviated above. A real response contains one directive interpretation per operator note and exactly 24 hourly plan entries.

## Public Sample Cases

`BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json` contains ten public cases with expected directive semantics and reference schedules. They are useful for manual API checks and must not be hard-coded into the implementation.

With the API running, execute the sample-case validator:

```bash
python3 test_runner.py
```

The validator sends each public case to `http://127.0.0.1:8000/optimize-energy` and checks directive interpretation, energy balance, battery constraints, end-of-day neutrality, and calculated totals.

## Project Layout

| File | Purpose |
| --- | --- |
| `main.py` | FastAPI application and HTTP endpoints |
| `models.py` | Pydantic request, response, and directive models |
| `llm_interpreter.py` | Gemini interpretation and plan summary generation |
| `guardrails.py` | Deterministic directive validation |
| `optimizer.py` | PuLP-based 24-hour energy schedule optimizer |
| `ai.py` | Gemini client wrapper and structured response parsing |
| `test_runner.py` | Public sample-case integration validator |
| `docker-compose.yml` | Containerized API configuration |

## Error Handling

- `422 Unprocessable Entity`: invalid input, invalid LLM directive output after retries, or an infeasible/invalid scenario.
- `500 Internal Server Error`: unexpected optimization failure.

The service retries invalid LLM directive output up to three times before returning a `422` response.

## Notes

- The API uses Gemini for natural-language interpretation and summary generation, so a valid `GOOGLE_API_KEY` is required for `/optimize-energy`.
- Operator notes are interpreted independently and returned in their original zero-based `note_index` order.
- The optimizer preserves end-of-day battery neutrality: battery energy after hour 23 must equal the initial battery energy.
- Equivalent optimal schedules may differ in their hourly action sequence while still satisfying the same constraints and cost tolerance.
