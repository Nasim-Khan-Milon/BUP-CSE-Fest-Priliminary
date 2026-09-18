import json
import math
import requests
from pathlib import Path


# ============================================================
# CONFIG
# ============================================================

BASE_URL = "http://127.0.0.1:8000"
ENDPOINT = f"{BASE_URL}/optimize-energy"

JSON_FILE = Path("BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json")

TOLERANCE = 0.01


# ============================================================
# HELPERS
# ============================================================

def close(a, b, tolerance=TOLERANCE):
    return abs(float(a) - float(b)) <= tolerance


def fail(message):
    raise AssertionError(message)


def get_case_by_id(data, scenario_id):
    for case in data["cases"]:
        if case["id"] == scenario_id:
            return case

    fail(f"Case not found: {scenario_id}")


# ============================================================
# DIRECTIVE VALIDATION
# ============================================================

def validate_directives(case, result):
    expected = case["expected_output"]["directive_interpretation"]
    actual = result["directive_interpretation"]

    if len(actual) != len(expected):
        fail(
            f"directive_interpretation length mismatch: "
            f"expected {len(expected)}, got {len(actual)}"
        )

    for exp, act in zip(expected, actual):

        if act["note_index"] != exp["note_index"]:
            fail(
                f"note_index mismatch: "
                f"expected {exp['note_index']}, "
                f"got {act['note_index']}"
            )

        if act["applies"] != exp["applies"]:
            fail(
                f"note {exp['note_index']}: "
                f"applies expected {exp['applies']}, "
                f"got {act['applies']}"
            )

        if act["directive_type"] != exp["directive_type"]:
            fail(
                f"note {exp['note_index']}: "
                f"directive_type expected "
                f"{exp['directive_type']}, "
                f"got {act['directive_type']}"
            )

        expected_adjustment = exp["structured_adjustment"]
        actual_adjustment = act["structured_adjustment"]

        if expected_adjustment is None:
            if actual_adjustment is not None:
                fail(
                    f"note {exp['note_index']}: "
                    f"expected structured_adjustment=null"
                )

            continue

        if actual_adjustment is None:
            fail(
                f"note {exp['note_index']}: "
                f"structured_adjustment is missing"
            )

        # Validate hours
        if actual_adjustment.get("hours") != expected_adjustment.get("hours"):
            fail(
                f"note {exp['note_index']}: "
                f"hours expected "
                f"{expected_adjustment.get('hours')}, "
                f"got {actual_adjustment.get('hours')}"
            )

        # Validate numeric directive values
        if "factor" in expected_adjustment:
            if not close(
                actual_adjustment.get("factor"),
                expected_adjustment["factor"]
            ):
                fail(
                    f"note {exp['note_index']}: "
                    f"factor expected "
                    f"{expected_adjustment['factor']}, "
                    f"got {actual_adjustment.get('factor')}"
                )

        if "minimum_energy_kwh" in expected_adjustment:
            if not close(
                actual_adjustment.get("minimum_energy_kwh"),
                expected_adjustment["minimum_energy_kwh"]
            ):
                fail(
                    f"note {exp['note_index']}: "
                    f"minimum_energy_kwh expected "
                    f"{expected_adjustment['minimum_energy_kwh']}, "
                    f"got {actual_adjustment.get('minimum_energy_kwh')}"
                )

        if "max_grid_kwh" in expected_adjustment:
            if not close(
                actual_adjustment.get("max_grid_kwh"),
                expected_adjustment["max_grid_kwh"]
            ):
                fail(
                    f"note {exp['note_index']}: "
                    f"max_grid_kwh expected "
                    f"{expected_adjustment['max_grid_kwh']}, "
                    f"got {actual_adjustment.get('max_grid_kwh')}"
                )


# ============================================================
# HOURLY PLAN VALIDATION
# ============================================================

def validate_hourly_plan(case, result):

    input_data = case["input"]
    battery = input_data["battery"]
    hours = input_data["hours"]
    plan = result["hourly_plan"]

    # --------------------------------------------------------
    # Exactly 24 hours
    # --------------------------------------------------------

    if len(plan) != 24:
        fail(f"hourly_plan must contain 24 entries, got {len(plan)}")

    plan_hours = [row["hour"] for row in plan]

    if sorted(plan_hours) != list(range(24)):
        fail(
            "hourly_plan must contain exactly "
            "one entry for every hour 0-23"
        )

    input_hours = {row["hour"]: row for row in hours}

    if len(input_hours) != 24:
        fail("Input must contain exactly 24 unique hours")

    # --------------------------------------------------------
    # Extract active directives
    # --------------------------------------------------------

    directives = result["directive_interpretation"]

    solar_reductions = {}
    no_charge_hours = set()
    no_discharge_hours = set()
    minimum_reserves = {}
    max_grid_limits = {}

    for directive in directives:

        if not directive["applies"]:
            continue

        dtype = directive["directive_type"]
        adjustment = directive["structured_adjustment"]

        if dtype == "solar_reduction":

            factor = adjustment["factor"]

            for hour in adjustment["hours"]:
                solar_reductions[hour] = factor

        elif dtype == "no_charge_window":

            no_charge_hours.update(adjustment["hours"])

        elif dtype == "no_discharge_window":

            no_discharge_hours.update(adjustment["hours"])

        elif dtype == "minimum_battery_reserve":

            minimum = adjustment["minimum_energy_kwh"]

            for hour in adjustment["hours"]:
                minimum_reserves[hour] = minimum

        elif dtype == "max_grid_window":

            maximum = adjustment["max_grid_kwh"]

            for hour in adjustment["hours"]:
                max_grid_limits[hour] = maximum

    # --------------------------------------------------------
    # Battery configuration
    # --------------------------------------------------------

    capacity = battery["capacity_kwh"]
    initial_energy = battery["initial_energy_kwh"]
    minimum_energy = battery["minimum_energy_kwh"]
    max_charge = battery["max_charge_kwh_per_hour"]
    max_discharge = battery["max_discharge_kwh_per_hour"]

    previous_energy = initial_energy

    calculated_total_grid = 0
    calculated_total_cost = 0
    calculated_peak_grid = 0

    # --------------------------------------------------------
    # Validate every hour
    # --------------------------------------------------------

    for row in plan:

        hour = row["hour"]

        demand = input_hours[hour]["demand_kwh"]
        solar = input_hours[hour]["solar_kwh"]
        tariff = input_hours[hour]["tariff_bdt_per_kwh"]

        grid = float(row["grid_kwh"])
        solar_used = float(row["solar_used_kwh"])
        battery_action = row["battery_action"]
        battery_kwh = float(row["battery_kwh"])
        energy_after = float(row["battery_energy_after_kwh"])

        # ----------------------------------------------------
        # Basic non-negative checks
        # ----------------------------------------------------

        if grid < -TOLERANCE:
            fail(f"Hour {hour}: grid_kwh cannot be negative")

        if solar_used < -TOLERANCE:
            fail(f"Hour {hour}: solar_used_kwh cannot be negative")

        if battery_kwh < -TOLERANCE:
            fail(f"Hour {hour}: battery_kwh cannot be negative")

        # ----------------------------------------------------
        # Battery action
        # ----------------------------------------------------

        if battery_action not in {"charge", "discharge", "idle"}:
            fail(
                f"Hour {hour}: invalid battery_action "
                f"{battery_action}"
            )

        if battery_action == "idle":

            if not close(battery_kwh, 0):
                fail(
                    f"Hour {hour}: idle battery must have "
                    f"battery_kwh = 0"
                )

        elif battery_action == "charge":

            if battery_kwh <= TOLERANCE:
                fail(
                    f"Hour {hour}: charge action must have "
                    f"positive battery_kwh"
                )

            if battery_kwh > max_charge + TOLERANCE:
                fail(
                    f"Hour {hour}: charge exceeds hourly limit"
                )

        elif battery_action == "discharge":

            if battery_kwh <= TOLERANCE:
                fail(
                    f"Hour {hour}: discharge action must have "
                    f"positive battery_kwh"
                )

            if battery_kwh > max_discharge + TOLERANCE:
                fail(
                    f"Hour {hour}: discharge exceeds hourly limit"
                )

        # ----------------------------------------------------
        # Battery energy transition
        # ----------------------------------------------------

        if battery_action == "charge":
            expected_energy = previous_energy + battery_kwh

        elif battery_action == "discharge":
            expected_energy = previous_energy - battery_kwh

        else:
            expected_energy = previous_energy

        if not close(energy_after, expected_energy):
            fail(
                f"Hour {hour}: battery energy mismatch. "
                f"Expected {expected_energy}, "
                f"got {energy_after}"
            )

        # ----------------------------------------------------
        # Battery capacity
        # ----------------------------------------------------

        if energy_after < minimum_energy - TOLERANCE:
            fail(
                f"Hour {hour}: battery below minimum "
                f"reserve {minimum_energy}"
            )

        if energy_after > capacity + TOLERANCE:
            fail(
                f"Hour {hour}: battery exceeds capacity"
            )

        # ----------------------------------------------------
        # Directive: minimum battery reserve
        # ----------------------------------------------------

        if hour in minimum_reserves:

            required = minimum_reserves[hour]

            if energy_after < required - TOLERANCE:
                fail(
                    f"Hour {hour}: emergency reserve violated. "
                    f"Required {required}, "
                    f"got {energy_after}"
                )

        # ----------------------------------------------------
        # Directive: no charge
        # ----------------------------------------------------

        if hour in no_charge_hours:

            if battery_action == "charge" or battery_kwh > TOLERANCE:
                fail(
                    f"Hour {hour}: charging is prohibited"
                )

        # ----------------------------------------------------
        # Directive: no discharge
        # ----------------------------------------------------

        if hour in no_discharge_hours:

            if battery_action == "discharge" or battery_kwh > TOLERANCE:
                fail(
                    f"Hour {hour}: discharging is prohibited"
                )

        # ----------------------------------------------------
        # Effective solar
        # ----------------------------------------------------

        factor = solar_reductions.get(hour, 1.0)

        effective_solar = solar * factor

        if solar_used > effective_solar + TOLERANCE:
            fail(
                f"Hour {hour}: solar_used {solar_used} "
                f"exceeds effective solar {effective_solar}"
            )

        # ----------------------------------------------------
        # Grid limit
        # ----------------------------------------------------

        if hour in max_grid_limits:

            maximum_grid = max_grid_limits[hour]

            if grid > maximum_grid + TOLERANCE:
                fail(
                    f"Hour {hour}: grid import {grid} "
                    f"exceeds limit {maximum_grid}"
                )

        # ----------------------------------------------------
        # Energy balance
        #
        # grid + solar + discharge
        # =
        # demand + charge
        # ----------------------------------------------------

        discharge = (
            battery_kwh
            if battery_action == "discharge"
            else 0
        )

        charge = (
            battery_kwh
            if battery_action == "charge"
            else 0
        )

        lhs = grid + solar_used + discharge
        rhs = demand + charge

        if not close(lhs, rhs):
            fail(
                f"Hour {hour}: energy balance violated. "
                f"Supply={lhs}, Demand={rhs}"
            )

        # ----------------------------------------------------
        # Totals
        # ----------------------------------------------------

        calculated_total_grid += grid
        calculated_total_cost += grid * tariff
        calculated_peak_grid = max(
            calculated_peak_grid,
            grid
        )

        previous_energy = energy_after

    # ========================================================
    # End-of-day neutrality
    # ========================================================

    if not close(previous_energy, initial_energy):
        fail(
            f"End-of-day battery mismatch. "
            f"Initial={initial_energy}, "
            f"Final={previous_energy}"
        )

    # ========================================================
    # Validate reported totals
    # ========================================================

    if not close(
        result["total_grid_kwh"],
        calculated_total_grid
    ):
        fail(
            f"total_grid_kwh incorrect. "
            f"Expected {calculated_total_grid}, "
            f"got {result['total_grid_kwh']}"
        )

    if not close(
        result["total_cost_bdt"],
        calculated_total_cost
    ):
        fail(
            f"total_cost_bdt incorrect. "
            f"Expected {calculated_total_cost}, "
            f"got {result['total_cost_bdt']}"
        )

    if not close(
        result["peak_grid_kwh"],
        calculated_peak_grid
    ):
        fail(
            f"peak_grid_kwh incorrect. "
            f"Expected {calculated_peak_grid}, "
            f"got {result['peak_grid_kwh']}"
        )


# ============================================================
# RESPONSE STRUCTURE VALIDATION
# ============================================================

def validate_response_structure(case, result):

    required_fields = [
        "scenario_id",
        "directive_interpretation",
        "hourly_plan",
        "total_grid_kwh",
        "total_cost_bdt",
        "peak_grid_kwh",
        "plan_summary",
    ]

    for field in required_fields:

        if field not in result:
            fail(
                f"Missing required output field: {field}"
            )

    if result["scenario_id"] != case["input"]["scenario_id"]:
        fail(
            f"scenario_id mismatch: "
            f"expected {case['input']['scenario_id']}, "
            f"got {result['scenario_id']}"
        )


# ============================================================
# RUN ONE CASE
# ============================================================

def run_case(case):

    scenario_id = case["id"]

    print(f"\n{'=' * 60}")
    print(f"Testing {scenario_id}")
    print(f"{'=' * 60}")

    try:

        response = requests.post(
            ENDPOINT,
            json=case["input"],
            timeout=120
        )

        if response.status_code != 200:
            fail(
                f"HTTP {response.status_code}: "
                f"{response.text}"
            )

        result = response.json()

        validate_response_structure(
            case,
            result
        )

        validate_directives(
            case,
            result
        )

        validate_hourly_plan(
            case,
            result
        )

        print(f"✅ {scenario_id} PASSED")

        print(
            f"   Grid: {result['total_grid_kwh']:.2f} kWh"
        )

        print(
            f"   Cost: {result['total_cost_bdt']:.2f} BDT"
        )

        print(
            f"   Peak: {result['peak_grid_kwh']:.2f} kWh"
        )

        return True

    except Exception as e:

        print(f"❌ {scenario_id} FAILED")
        print(f"   Reason: {e}")

        return False


# ============================================================
# MAIN
# ============================================================

def main():

    print("GridWise Public Test Runner")
    print("============================")

    if not JSON_FILE.exists():
        print(
            f"❌ Test file not found: {JSON_FILE}"
        )
        return

    with open(
        JSON_FILE,
        "r",
        encoding="utf-8"
    ) as f:

        data = json.load(f)

    cases = data["cases"]

    print(f"Found {len(cases)} public test cases")
    print(f"Testing endpoint: {ENDPOINT}")

    passed = 0
    failed = 0

    for case in cases:

        if run_case(case):
            passed += 1
        else:
            failed += 1

    # ========================================================
    # SUMMARY
    # ========================================================

    print(f"\n{'=' * 60}")
    print("TEST SUMMARY")
    print(f"{'=' * 60}")

    print(f"Total : {len(cases)}")
    print(f"Passed: {passed}")
    print(f"Failed: {failed}")

    if failed == 0:
        print("\n🎉 ALL PUBLIC TEST CASES PASSED")
    else:
        print(
            f"\n {failed} TEST CASE(S) FAILED"
        )


if __name__ == "__main__":
    main()