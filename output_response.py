import os
import google.generativeai as genai
from typing import List, Dict, Any

# Ensure you have configured your API key in your main app initialization:
# genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))

def generate_plan_summary_with_gemini(status_msg: str, directives: List[Any], total_cost: float) -> str:
    """
    Calls the Gemini API to generate a dynamic, human-readable summary 
    based on the solver's execution state and active constraints.
    """
    active_rules = []
    for d in directives:
        applies = d.get("applies", False) if isinstance(d, dict) else getattr(d, "applies", False)
        dtype = d.get("directive_type", "no_op") if isinstance(d, dict) else getattr(d, "directive_type", "no_op")
        if applies and dtype != "no_op":
            active_rules.append(dtype.replace("_", " "))

    prompt = f"""
    You are an AI assistant for a smart campus energy grid. Write a concise, 1-sentence summary 
    of the daily optimization plan. Do not use markdown formatting.

    Context:
    - Solver Status: {status_msg}
    - Operator Rules Enforced: {', '.join(active_rules) if active_rules else 'None'}
    - Final Grid Cost: {total_cost} BDT

    Explain that the system shifted battery energy to offset peak grid tariffs while strictly 
    respecting the operator rules and hardware limits.
    """
    
    try:
        # Use gemini-1.5-flash (or gemini-2.5-flash) for low-latency text generation
        model = genai.GenerativeModel("gemini-1.5-flash")
        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        # STRICT REQUIREMENT: Safe Failure fallback. 
        # If the LLM API times out or fails, do not crash the endpoint.
        rule_str = f" maintaining {', '.join(active_rules)}." if active_rules else "."
        return f"{status_msg} Optimized battery schedule applied successfully{rule_str}"


def process_scenario_endpoint(scenario_id: str, hours_data: List[Any], battery: Any, directive_interpretations: List[Any]) -> Dict[str, Any]:
    """
    Top-level wrapper that calls the LP solver, generates the LLM summary, 
    and returns the exact dictionary schema required by the API contract.
    """
    # 1. Execute the strictly validated mathematical optimization
    plan, total_grid, total_cost, peak_grid, status_msg = solve_energy_schedule(
        hours_data, battery, directive_interpretations
    )
    
    # 2. Generate the plan summary via Gemini API
    summary_text = generate_plan_summary_with_gemini(status_msg, directive_interpretations, total_cost)
    
    # 3. Assemble and return the precise schema required by Section 10.1
    return {
        "scenario_id": scenario_id,
        "directive_interpretation": directive_interpretations,
        "hourly_plan": plan,
        "total_grid_kwh": total_grid,
        "total_cost_bdt": total_cost,
        "peak_grid_kwh": peak_grid,
        "plan_summary": summary_text
    }