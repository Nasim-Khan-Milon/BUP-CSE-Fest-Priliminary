from fastapi import FastAPI, HTTPException

from models import (
    ScenarioInput,
    ScenarioOutput,
)

from llm_interpreter import (
    interpret_operator_notes,
)

from guardrails import (
    validate_directives,
)

from optimizer import (
    solve_energy_schedule,
)


app = FastAPI(
    title="GridWise API",
    version="1.0.0",
)


MAX_LLM_ATTEMPTS = 3


@app.get("/health")
def health():
    return {
        "status": "ok"
    }


@app.post(
    "/optimize-energy",
    response_model=ScenarioOutput,
)
def optimize_energy(
    scenario: ScenarioInput,
):
    """
    Interpret operator notes, validate the resulting directives,
    and generate the optimal 24-hour energy schedule.
    """

    # ---------------------------------------------------------
    # 1. LLM interpretation + guardrail retry
    # ---------------------------------------------------------

    directives = None
    last_error = None

    for attempt in range(MAX_LLM_ATTEMPTS):
        try:
            # Gemini interprets the operator notes
            directives = interpret_operator_notes(
                scenario.operator_notes
            )

            # Validate Gemini output
            directives = validate_directives(
                directives=directives,
                expected_count=len(
                    scenario.operator_notes
                ),
            )

            # Validation successful
            break

        except ValueError as exc:
            last_error = exc

            if attempt == MAX_LLM_ATTEMPTS - 1:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        "Operator note interpretation failed "
                        f"after {MAX_LLM_ATTEMPTS} attempts: "
                        f"{last_error}"
                    ),
                ) from exc

    # ---------------------------------------------------------
    # 2. Deterministic optimization
    # ---------------------------------------------------------

    try:
        (
           plan, total_grid, total_cost, peak_grid, _
        ) = solve_energy_schedule(
            hours_data=scenario.hours,
            battery=scenario.battery,
            directives=directives,
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        ) from exc

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="Internal optimization error.",
        ) from exc

    # ---------------------------------------------------------
    # 3. Final response
    # ---------------------------------------------------------

    return ScenarioOutput(
        scenario_id=scenario.scenario_id,
        directive_interpretation=directives,
        hourly_plan=plan,
        total_grid_kwh=total_grid,
        total_cost_bdt=total_cost,
        peak_grid_kwh=peak_grid,
        plan_summary="",
    )