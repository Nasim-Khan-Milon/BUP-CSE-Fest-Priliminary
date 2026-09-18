from fastapi import FastAPI, HTTPException

from models import (
    ScenarioInput,
    ScenarioOutput,
)

from llm_interpreter import (
    interpret_operator_notes,
    process_scenario_endpoint,
)

from guardrails import (
    validate_directives,
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
    Interpret operator notes, validate the directives,
    run the energy optimizer, generate the plan summary,
    and return the final response.
    """

    # ---------------------------------------------------------
    # 1. LLM interpretation + guardrail retry
    # ---------------------------------------------------------

    directives = None
    last_error = None

    for attempt in range(MAX_LLM_ATTEMPTS):
        try:
            directives = interpret_operator_notes(
                scenario.operator_notes
            )

            directives = validate_directives(
                directives=directives,
                expected_count=len(
                    scenario.operator_notes
                ),
            )

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
    # 2. Optimization + final response
    # ---------------------------------------------------------

    try:
        result = process_scenario_endpoint(
            scenario_id=scenario.scenario_id,
            hours_data=scenario.hours,
            battery=scenario.battery,
            directive_interpretations=directives,
        )

        return ScenarioOutput(**result)

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