

import math
import pulp
import copy
from typing import List, Dict, Any, Tuple, Set

def _get(d: Any, k: str, default: Any = None) -> Any:
    return d.get(k, default) if isinstance(d, dict) else getattr(d, k, default)


def validate_plan(plan: List[Dict], hours_data: List[Any], battery: Any, 
                  effective_solar: List[float], reserve_floor: List[float], 
                  grid_cap: Dict[int, float], no_charge_hours: Set[int], 
                  no_discharge_hours: Set[int]) -> None:
    if len(plan) != 24 or set(p["hour"] for p in plan) != set(range(24)):
        raise ValueError("Plan must contain exactly 24 unique hours.")
    
    running_e = round(battery.initial_energy_kwh, 2)
    
    for p in plan:
        h = p["hour"]
        grid = p["grid_kwh"]
        solar = p["solar_used_kwh"]
        action = p["battery_action"]
        bat = p["battery_kwh"]
        e_after = p["battery_energy_after_kwh"]
        demand = _get(hours_data[h], "demand_kwh")
        
        if not all(math.isfinite(x) for x in [grid, solar, bat, e_after]):
            raise ValueError(f"Hour {h}: Contains non-finite numeric values.")
        if grid < 0:
            raise ValueError(f"Hour {h}: Grid {grid} is negative.")
            
        if action == "charge" and bat > battery.max_charge_kwh_per_hour:
            raise ValueError(f"Hour {h}: Charge {bat} exceeds limit.")
        if action == "discharge" and bat > battery.max_discharge_kwh_per_hour:
            raise ValueError(f"Hour {h}: Discharge {bat} exceeds limit.")
        if action == "idle" and bat != 0:
            raise ValueError(f"Hour {h}: Idle but bat_kwh is {bat}.")

        if h in no_charge_hours and action == "charge" and bat > 0:
            raise ValueError(f"Hour {h}: Charge action inside no_charge_window.")
        if h in no_discharge_hours and action == "discharge" and bat > 0:
            raise ValueError(f"Hour {h}: Discharge action inside no_discharge_window.")
        
        if h in grid_cap and grid > grid_cap[h] + 0.011:
            raise ValueError(f"Hour {h}: Grid {grid} exceeds cap {grid_cap[h]}.")
            
        if solar > round(effective_solar[h], 2) + 0.011:
            raise ValueError(f"Hour {h}: Solar {solar} exceeds effective {effective_solar[h]}.")
            
        charge_comp = bat if action == "charge" else 0.0
        discharge_comp = bat if action == "discharge" else 0.0
        lhs = round(grid + solar + discharge_comp, 2)
        rhs = round(demand + charge_comp, 2)
        if abs(lhs - rhs) > 0.011:
            raise ValueError(f"Hour {h}: Energy imbalance. grid+solar+dch={lhs}, demand+chg={rhs}")
            
        expected_e_after = round(running_e + charge_comp - discharge_comp, 2)
        if abs(e_after - expected_e_after) > 0.011:
            raise ValueError(f"Hour {h}: State drift. Expected {expected_e_after}, got {e_after}")
            
        if e_after < reserve_floor[h] - 0.011 or e_after > battery.capacity_kwh + 0.011:
            raise ValueError(f"Hour {h}: Energy {e_after} out of bounds (Reserve: {reserve_floor[h]}).")
            
        running_e = e_after

    if abs(running_e - battery.initial_energy_kwh) > 0.011:
        raise ValueError(f"Final energy {running_e} != initial {battery.initial_energy_kwh}")

def solve_energy_schedule(hours_data: List[Any], battery: Any, directives: List[Any]) -> Tuple[List[Dict], float, float, float, str, List[Dict]]:
    if len(hours_data) != 24 or set(_get(h, "hour") for h in hours_data) != set(range(24)):
        raise ValueError("hours_data must contain exactly 24 unique hours from 0 to 23.")
    
    hours_data = sorted(hours_data, key=lambda x: _get(x, "hour"))

    base_solar = [_get(h, "solar_kwh") for h in hours_data]
    effective_solar = list(base_solar)
    reserve_floor = [battery.minimum_energy_kwh for _ in range(24)]
    no_charge_hours = set()
    no_discharge_hours = set()
    grid_cap = {}
    
    invalid_directives = []
    
    # Isolate schema sanitization to a deep copy so returned interpretations match actual execution
    sanitized_directives = copy.deepcopy(directives)

    for d in sanitized_directives:
        if not isinstance(d, dict): continue
        
        dtype = d.get('directive_type', 'no_op')
        if not d.get('applies', False) or dtype == "no_op":
            d['applies'] = False; d['directive_type'] = 'no_op'; d['structured_adjustment'] = None
            continue
            
        adj = d.get('structured_adjustment')
        if not isinstance(adj, dict):
            d['applies'] = False; d['directive_type'] = 'no_op'; d['structured_adjustment'] = None
            invalid_directives.append(dtype)
            continue
            
        raw_hours = adj.get("hours", [])
        if not isinstance(raw_hours, list): raw_hours = []
        clean_hours = sorted(list(set(h for h in raw_hours if isinstance(h, int) and 0 <= h <= 23)))
        adj["hours"] = clean_hours
        
        try:
            if dtype == "solar_reduction":
                factor = float(adj.get("factor", 1.0))
                if not (0.0 <= factor <= 1.0): raise ValueError 
                adj["factor"] = factor
            elif dtype == "minimum_battery_reserve":
                min_e = float(adj.get("minimum_energy_kwh", 0.0))
                if min_e < 0 or min_e > battery.capacity_kwh: raise ValueError 
                adj["minimum_energy_kwh"] = min_e
            elif dtype == "max_grid_window":
                cap = float(adj.get("max_grid_kwh", float('inf')))
                if cap < 0: raise ValueError
                adj["max_grid_kwh"] = cap
            elif dtype not in ["no_charge_window", "no_discharge_window"]:
                raise ValueError
        except (ValueError, TypeError):
            invalid_directives.append(dtype)
            d['applies'] = False; d['directive_type'] = 'no_op'; d['structured_adjustment'] = None

    for directive in sanitized_directives:
        if not _get(directive, 'applies', False): continue
        dtype = _get(directive, 'directive_type')
        adj = _get(directive, 'structured_adjustment')
        valid_hours = _get(adj, "hours", [])

        if dtype == "solar_reduction":
            factor = _get(adj, "factor", 1.0)
            for h in valid_hours:
                effective_solar[h] = min(effective_solar[h], base_solar[h] * factor)
        elif dtype == "minimum_battery_reserve":
            min_e = _get(adj, "minimum_energy_kwh", 0.0)
            for h in valid_hours:
                reserve_floor[h] = max(reserve_floor[h], min_e)
        elif dtype == "no_charge_window":
            no_charge_hours.update(valid_hours)
        elif dtype == "no_discharge_window":
            no_discharge_hours.update(valid_hours)
        elif dtype == "max_grid_window":
            cap = _get(adj, "max_grid_kwh", float('inf'))
            for h in valid_hours:
                grid_cap[h] = min(grid_cap.get(h, float('inf')), cap)

    original_grid_cap = dict(grid_cap)
    original_reserve_floor = list(reserve_floor)
    init_e = round(battery.initial_energy_kwh, 2)

    def attempt_solve(active_grid_cap, active_reserve_floor, time_limit=5):
        prob = pulp.LpProblem("GridWise", pulp.LpMinimize)
        H = range(24)

        g = pulp.LpVariable.dicts("grid", H, lowBound=0)
        s = pulp.LpVariable.dicts("solar", H, lowBound=0)
        c = pulp.LpVariable.dicts("charge", H, lowBound=0, upBound=battery.max_charge_kwh_per_hour)
        dch = pulp.LpVariable.dicts("discharge", H, lowBound=0, upBound=battery.max_discharge_kwh_per_hour)
        E = pulp.LpVariable.dicts("energy", H, lowBound=0, upBound=battery.capacity_kwh)

        base_cost = pulp.lpSum(g[h] * _get(hours_data[h], "tariff_bdt_per_kwh") for h in H)
        tie_breaker = 1e-6 * pulp.lpSum(c[h] + dch[h] for h in H)
        prob += base_cost + tie_breaker

        for h in H:
            prob += g[h] + s[h] + dch[h] == _get(hours_data[h], "demand_kwh") + c[h]
            prob += s[h] <= effective_solar[h]

            prev_E = init_e if h == 0 else E[h - 1]
            prob += E[h] == prev_E + c[h] - dch[h]
            
            prob += E[h] >= active_reserve_floor[h]

            if h in no_charge_hours:
                prob += c[h] == 0
            if h in no_discharge_hours:
                prob += dch[h] == 0
            if h in active_grid_cap:
                prob += g[h] <= active_grid_cap[h]

        prob += E[23] == init_e
        prob.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=time_limit))
        
        # Sound Acceptance Check: strictly handles optimal and verified feasible incumbents
        status = prob.status
        if status == pulp.LpStatusOptimal:
            return c, dch, s
        elif status == pulp.LpStatusNotSolved:
            # Verify incumbent existence safely without relying on raw unvalidated pointers
            try:
                if c[0].varValue is not None and all(c[h].varValue is not None for h in H):
                    return c, dch, s
            except Exception:
                pass
        return None

    active_caps = dict(grid_cap)
    active_reserves = list(reserve_floor)
    degradation_notes = []
    
    result = attempt_solve(active_caps, active_reserves, time_limit=5)
    
    if not result:
        cap_hours = sorted(list(active_caps.keys()), reverse=True)
        for h in cap_hours:
            del active_caps[h]
            degradation_notes.append(f"Dropped grid cap at hour {h}")
            result = attempt_solve(active_caps, active_reserves, time_limit=1)
            if result: break
            
    if not result:
        reserve_hours = sorted([h for h in range(24) if active_reserves[h] > battery.minimum_energy_kwh], reverse=True)
        for h in reserve_hours:
            active_reserves[h] = battery.minimum_energy_kwh
            degradation_notes.append(f"Dropped reserve override at hour {h}")
            result = attempt_solve(active_caps, active_reserves, time_limit=1)
            if result: break

    plan = []
    if result:
        c, dch, s = result
        deltas = [round((c[h].varValue or 0.0) - (dch[h].varValue or 0.0), 2) for h in range(24)]
        
        unadjusted_E = []
        tmp_E = init_e
        for d in deltas:
            tmp_E = round(tmp_E + d, 2)
            unadjusted_E.append(tmp_E)

        residual = round(sum(deltas), 2)
        if residual != 0.0:
            for h in reversed(range(24)):
                new_delta = round(deltas[h] - residual, 2)
                is_charge = new_delta > 0
                is_discharge = new_delta < 0
                
                if is_charge and h in no_charge_hours: continue
                if is_discharge and h in no_discharge_hours: continue
                if is_charge and new_delta > battery.max_charge_kwh_per_hour: continue
                if is_discharge and -new_delta > battery.max_discharge_kwh_per_hour: continue
                
                if h in active_caps:
                    test_c = new_delta if is_charge else 0.0
                    test_dch = -new_delta if is_discharge else 0.0
                    cap_solar = math.floor(effective_solar[h] * 100) / 100.0
                    test_s = min(round(s[h].varValue or 0.0, 2), cap_solar)
                    test_demand = _get(hours_data[h], "demand_kwh")
                    
                    test_grid = round(test_demand + test_c - test_s - test_dch, 2)
                    if test_grid < 0:
                        test_grid = 0.0
                    if test_grid > active_caps[h] + 0.001:
                        continue
                
                valid_bounds = True
                for k in range(h, 24):
                    shifted_E = round(unadjusted_E[k] - residual, 2)
                    if shifted_E < active_reserves[k] - 0.011 or shifted_E > battery.capacity_kwh + 0.011:
                        valid_bounds = False
                        break
                
                if not valid_bounds: continue
                
                deltas[h] = new_delta
                break

        prev = init_e
        for h in range(24):
            if deltas[h] > 0:
                action, bat = "charge", deltas[h]
            elif deltas[h] < 0:
                action, bat = "discharge", -deltas[h]
            else:
                action, bat = "idle", 0.0

            cap_solar = math.floor(effective_solar[h] * 100) / 100.0
            solar_r = min(round(s[h].varValue or 0.0, 2), cap_solar)

            charge_comp = bat if action == "charge" else 0.0
            discharge_comp = bat if action == "discharge" else 0.0
            demand = _get(hours_data[h], "demand_kwh")
            
            grid_derived = round(demand + charge_comp - solar_r - discharge_comp, 2)
            
            if grid_derived < 0:
                solar_r = max(0.0, round(solar_r + grid_derived, 2))
                grid_derived = 0.0

            E_r = round(prev + charge_comp - discharge_comp, 2)
            prev = E_r

            plan.append({
                "hour": h,
                "grid_kwh": grid_derived,
                "solar_used_kwh": solar_r,
                "battery_action": action,
                "battery_kwh": bat,
                "battery_energy_after_kwh": E_r
            })
    else:
        prev = init_e
        degradation_notes = ["Forced total battery idle mode due to unsolvable directive matrix."]
        for h in range(24):
            demand = _get(hours_data[h], "demand_kwh")
            cap_solar = math.floor(effective_solar[h] * 100) / 100.0
            solar_r = min(demand, cap_solar)
            grid_derived = round(demand - solar_r, 2)
            
            plan.append({
                "hour": h,
                "grid_kwh": grid_derived,
                "solar_used_kwh": solar_r,
                "battery_action": "idle",
                "battery_kwh": 0.0,
                "battery_energy_after_kwh": prev
            })

    validate_plan(plan, hours_data, battery, effective_solar, original_reserve_floor, original_grid_cap, no_charge_hours, no_discharge_hours)

    total_grid = round(sum(p["grid_kwh"] for p in plan), 2)
    total_cost = round(sum(plan[h]["grid_kwh"] * _get(hours_data[h], "tariff_bdt_per_kwh") for h in range(24)), 2)
    peak_grid = round(max(p["grid_kwh"] for p in plan), 2)
    
    status_msg = "Optimal schedule achieved."
    if degradation_notes:
        status_msg = f"Degraded: {'; '.join(degradation_notes)}."
    if invalid_directives:
        status_msg += f" Ignored unrecognized directives: {', '.join(invalid_directives)}."

    return plan, total_grid, total_cost, peak_grid, status_msg, sanitized_directives

