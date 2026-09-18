from models import DirectiveInterpretation
from ai import text_to_text


SYSTEM_PROMPT = """
You are an energy-management directive interpreter.

Interpret the operator's note into exactly one structured
DirectiveInterpretation.

Allowed directive types:

- solar_reduction
- minimum_battery_reserve
- no_charge_window
- no_discharge_window
- max_grid_window
- no_op

Rules:

1. Do not optimize the energy schedule.
2. Do not calculate battery charging or discharging.
3. Do not calculate grid usage.
4. Hours must be integers from 0 to 23.
5. Never invent missing information.
6. Use no_op when the instruction is unclear or not actionable.
7. no_op must have:
   - applies = false
   - structured_adjustment = null
8. Actionable directives must have:
   - applies = true
   - the appropriate structured_adjustment.
"""


def interpret_operator_note(
    note: str,
    note_index: int,
) -> DirectiveInterpretation:

    prompt = f"""
Operator note index: {note_index}

Operator note:
{note}

Interpret this note and return the structured directive.
"""

    result = text_to_text(
        input_text=note,
        system_prompt=SYSTEM_PROMPT,
        user_prompt=prompt,
        output_format=DirectiveInterpretation,
    )

    if result is None:
        raise ValueError(
            f"Failed to interpret operator note {note_index}"
        )

    # The application controls the index.
    result.note_index = note_index

    return result


def interpret_operator_notes(
    operator_notes: list[str],
) -> list[DirectiveInterpretation]:

    return [
        interpret_operator_note(
            note=note,
            note_index=index,
        )
        for index, note in enumerate(operator_notes)
    ]