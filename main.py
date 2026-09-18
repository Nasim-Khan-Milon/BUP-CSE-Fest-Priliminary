from typing import List

from fastapi import FastAPI, HTTPException

from models import (
    ScenarioInput,
    DirectiveInterpretation,
)

from llm_interpreter import (
    interpret_operator_notes,
)

from guardrails import (
    validate_directives,
)


app = FastAPI(
    title="GridWise API",
    version="1.0.0",
)


@app.get("/health")
def health():
    return {
        "status": "ok"
    }


@app.post(
    "/energy/interpret",
    response_model=List[DirectiveInterpretation],
)
def interpret_energy_directives(
    scenario: ScenarioInput,
):
    """
    Interpret and validate operator directives.

    This endpoint does not generate the final
    24-hour energy schedule yet.
    """

    try:

        # 1. LLM interpretation
        directives = interpret_operator_notes(
            scenario.operator_notes
        )

        # 2. Manual guardrails
        validated_directives = validate_directives(
            directives=directives,
            expected_count=len(
                scenario.operator_notes
            ),
        )

        

        return validated_directives

    except ValueError as exc:

        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc