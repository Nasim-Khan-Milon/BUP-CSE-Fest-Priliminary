from guardrails import Guard
from models import DirectiveInterpretation


def create_directive_guard() -> Guard:
    return Guard.from_pydantic(
        output_class=DirectiveInterpretation
    )


directive_guard = create_directive_guard()