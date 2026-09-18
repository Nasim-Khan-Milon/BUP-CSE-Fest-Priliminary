from models import DirectiveInterpretation
from ai import text_to_text

from typing import List, Dict, Any

from optimizer import solve_energy_schedule


SYSTEM_PROMPT = """
You are an expert energy-management directive interpreter for a smart campus optimization API. 
Your exact task is to read a single human operator note and map it to a strict, machine-readable JSON structure.

You will be provided with:
1. The `operator_note` (string).
2. The `note_index` (integer).
3. The `battery` parameters (JSON object)
The battery parameters may be used only when the operator note explicitly expresses a battery reserve as a percentage of battery capacity. Do not use battery parameters to infer or invent constraints.

=== CRITICAL RULES ===
1. NO OPTIMIZATION: Do not calculate grid usage, schedule battery actions, or invent demand. You are strictly a text-to-JSON parser.
2. TIME WINDOWS: Time is 24-hour military time. Windows are start-inclusive and end-exclusive. 
   - Example: "1 PM to 3 PM" means 13:00 to 15:00. The array MUST be [13, 14].
   - Example: "6 PM until 9 PM" MUST be [18, 19, 20].
   - The `hours` array must always be unique integers sorted in ascending order.
3. HOUR VALIDATION:
Every directive hour must be an integer from 0 through 23.
Convert all explicitly stated time windows to hours using start-inclusive/end-exclusive semantics.
If multiple time ranges are mentioned, combine them into one unique, ascending hours array.
Do not add hours that were not specified or logically included by the stated time range.

4. PERCENTAGE MATH: 
   - If a reserve is explicitly given as a percentage of battery capacity (e.g., "50% of capacity"), multiply it by battery.capacity_kwh to output the absolute minimum_energy_kwh.
   Do not convert percentages using any other battery field.
   If the note gives an absolute kWh value, use that exact value without modification.
   Never infer a percentage or value that is not explicitly stated.
   - For `solar_reduction`, the `factor` is the usable fraction remaining (0.0 to 1.0). "Drops to 20%" means factor is 0.2. "Reduced by 80%" means factor is 0.2.

5.NO HALLUCINATION: 
Use only information explicitly stated in the operator note and the permitted battery.capacity_kwh calculation. Do not invent missing times, values, limits, or directives.
If the note clearly expresses one of the five supported directives, it MUST be classified as that directive and applies MUST be true. Do not classify a clearly stated supported directive as no_op.
Use no_op only when the note is irrelevant to energy optimization or does not express any of the five supported directive types.

=== DIRECTIVE TYPES & SCHEMA ===
You must output exactly one JSON object matching this schema. Choose exactly ONE of the 6 allowed directive_type values. The note_index must be copied exactly from the input. Do not add, remove, rename, or invent fields.

1.solar_reduction: Restricts usable solar generation during specified hours.
    Required: {"hours": [int, ...], "factor": float}
    factor must be between 0.0 and 1.0 inclusive.
    "Reduced by X%" means factor = 1 - X/100.
    "Drops to X%" means factor = X/100.
Do not confuse "reduced by" with "drops to".
2. minimum_battery_reserve: Requires the battery to maintain at least the specified energy level during the specified hours.
  Required: {"hours": [int, ...], "minimum_energy_kwh": float}
  A percentage explicitly stated as a percentage of battery capacity MUST be converted using battery.capacity_kwh.
  Example: "Keep at least 50% of the battery capacity" means minimum_energy_kwh = 0.50 × battery.capacity_kwh.
3. no_charge_window: Battery cannot charge. 
   - Required: {"hours": [int, ...]}
4. no_discharge_window: Battery cannot discharge. 
   - Required: {"hours": [int, ...]}
5. max_grid_window: Limit on grid import. 
   - Required: {"hours": [int, ...], "max_grid_kwh": float}
6. no_op: Note that is irrelevant to energy optimization, does not express one of the five supported directives, or is too ambiguous to map safely to a supported directive.
Required: "applies": false
Required: "structured_adjustment": null
Do not invent or infer an unsupported directive.

=== OUTPUT FORMAT ===
Return ONLY valid JSON. No markdown formatting blocks, no conversational text.

{
  "note_index": <integer passed to you>,
  "applies": <boolean: false ONLY if no_op, true for all others>,
  "directive_type": "<one of the 6 allowed strings>",
  "structured_adjustment": <object or null based on type>,
  "explanation": "<1-sentence brief explanation of why this was chosen>"
}
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

def generate_plan_summary_with_gemini(
    status_msg: str,
    directives: List[Any],
    total_cost: float,
) -> str:
    """
    Generate a concise human-readable summary of the
    optimized energy schedule using Gemini.
    """

    active_rules = []

    for directive in directives:
        applies = (
            directive.get("applies", False)
            if isinstance(directive, dict)
            else getattr(directive, "applies", False)
        )

        directive_type = (
            directive.get("directive_type", "no_op")
            if isinstance(directive, dict)
            else getattr(directive, "directive_type", "no_op")
        )

        # Handle Pydantic Enum
        if hasattr(directive_type, "value"):
            directive_type = directive_type.value

        if applies and directive_type != "no_op":
            active_rules.append(
                directive_type.replace("_", " ")
            )

    system_prompt = """
You are an AI assistant for a smart campus energy grid.

Generate a concise one-sentence summary of the
daily energy optimization plan.

Rules:
- Do not use markdown.
- Do not invent numerical values.
- Do not invent operator rules.
- Do not claim battery behavior unless supported by the input.
- Only use the provided solver status, rules, and cost.
"""

    user_prompt = f"""
Solver Status:
{status_msg}

Operator Rules Enforced:
{", ".join(active_rules) if active_rules else "None"}

Final Grid Cost:
{total_cost} BDT

Write one concise sentence summarizing the optimization result.
"""

    try:
        result = text_to_text(
            input_text="Generate the final optimization summary.",
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model="gemini-2.5-flash",
        )

        if result:
            return str(result).strip()

    except Exception:
        pass

    # Safe fallback if Gemini fails
    rule_str = (
        f" while maintaining {', '.join(active_rules)}."
        if active_rules
        else "."
    )

    return (
        f"{status_msg} "
        f"Optimized energy schedule applied successfully"
        f"{rule_str}"
    )


def process_scenario_endpoint(
    scenario_id: str,
    hours_data: List[Any],
    battery: Any,
    directive_interpretations: List[Any],
) -> Dict[str, Any]:
    """
    Run the energy optimizer, generate the Gemini summary,
    and return the final API response dictionary.
    """

    # ---------------------------------------------------------
    # 1. Run mathematical optimization
    # ---------------------------------------------------------

    (
        plan,
        total_grid,
        total_cost,
        peak_grid,
        status_msg,
        sanitized_directives
    ) = solve_energy_schedule(
        hours_data,
        battery,
        directive_interpretations,
    )

    # ---------------------------------------------------------
    # 2. Generate final plan summary
    # ---------------------------------------------------------

    summary_text = generate_plan_summary_with_gemini(
        status_msg=status_msg,
        directives=sanitized_directives,
        total_cost=total_cost,
    )

    # ---------------------------------------------------------
    # 3. Final API response
    # ---------------------------------------------------------

    return {
        "scenario_id": scenario_id,
        "directive_interpretation": sanitized_directives,
        "hourly_plan": plan,
        "total_grid_kwh": total_grid,
        "total_cost_bdt": total_cost,
        "peak_grid_kwh": peak_grid,
        "plan_summary": summary_text,
    }