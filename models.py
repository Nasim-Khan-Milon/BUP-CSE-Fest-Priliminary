from enum import Enum
from typing import List, Optional, Union
from pydantic import BaseModel, Field



class DirectiveType(str, Enum):
    SOLAR_REDUCTION = "solar_reduction"
    MINIMUM_BATTERY_RESERVE = "minimum_battery_reserve"
    NO_CHARGE_WINDOW = "no_charge_window"
    NO_DISCHARGE_WINDOW = "no_discharge_window"
    MAX_GRID_WINDOW = "max_grid_window"
    NO_OP = "no_op"


class BatteryAction(str, Enum):
    CHARGE = "charge"
    DISCHARGE = "discharge"
    IDLE = "idle"


# ==========================================
# Input Models
# ==========================================

class HourInput(BaseModel):
    hour: int = Field(..., ge=0, le=23, description="Hour of the day (0-23)")
    demand_kwh: float = Field(..., ge=0, description="Energy demand in kWh")
    solar_kwh: float = Field(..., ge=0, description="Forecasted solar energy in kWh")
    tariff_bdt_per_kwh: float = Field(..., ge=0, description="Tariff rate in BDT per kWh")


class BatteryInput(BaseModel):
    capacity_kwh: float = Field(..., gt=0, description="Total battery storage capacity")
    initial_energy_kwh: float = Field(..., ge=0, description="Starting battery energy level")
    minimum_energy_kwh: float = Field(..., ge=0, description="Default lower energy threshold")
    max_charge_kwh_per_hour: float = Field(..., ge=0, description="Maximum charging rate per hour")
    max_discharge_kwh_per_hour: float = Field(..., ge=0, description="Maximum discharging rate per hour")


class ScenarioInput(BaseModel):
    scenario_id: str = Field(..., description="Unique ID for the scenario")
    operator_notes: List[str] = Field(
        ...,
        min_length=1,
        max_length=3,
        description="Array of 1 to 3 non-empty natural language operator notes"
    )
    hours: List[HourInput] = Field(
        ...,
        min_length=24,
        max_length=24,
        description="24-hour time-series inputs"
    )
    battery: BatteryInput


# ==========================================
# Output & Directive Interpretation Models
# ==========================================

class SolarReductionAdjustment(BaseModel):
    hours: List[int] = Field(..., description="List of hour integers (0-23)")
    factor: float = Field(..., ge=0.0, le=1.0, description="Fraction of remaining usable solar capacity")


class MinimumBatteryReserveAdjustment(BaseModel):
    hours: List[int] = Field(..., description="List of hour integers (0-23)")
    minimum_energy_kwh: float = Field(..., ge=0, description="Required minimum battery energy reserve in kWh")


class WindowAdjustment(BaseModel):
    hours: List[int] = Field(..., description="List of hour integers (0-23)")


class MaxGridWindowAdjustment(BaseModel):
    hours: List[int] = Field(..., description="List of hour integers (0-23)")
    max_grid_kwh: float = Field(..., ge=0, description="Maximum grid draw cap in kWh")


StructuredAdjustmentType = Optional[
    Union[
        SolarReductionAdjustment,
        MinimumBatteryReserveAdjustment,
        WindowAdjustment,
        MaxGridWindowAdjustment
    ]
]


class DirectiveInterpretation(BaseModel):
    note_index: int = Field(..., ge=0, description="Zero-based index corresponding to operator note")
    applies: bool = Field(..., description="True if directive applies, False for no_op")
    directive_type: DirectiveType
    structured_adjustment: StructuredAdjustmentType = Field(
        None,
        description="Must be null when directive_type is 'no_op'"
    )
    explanation: str = Field(..., description="Reasoning for the interpretation")


class HourlyPlanItem(BaseModel):
    hour: int = Field(..., ge=0, le=23)
    grid_kwh: float = Field(..., ge=0)
    solar_used_kwh: float = Field(..., ge=0)
    battery_action: BatteryAction
    battery_kwh: float = Field(..., ge=0)
    battery_energy_after_kwh: float = Field(..., ge=0)


class ScenarioOutput(BaseModel):
    scenario_id: str
    directive_interpretation: List[DirectiveInterpretation]
    hourly_plan: List[HourlyPlanItem] = Field(..., min_length=24, max_length=24)
    total_grid_kwh: float = Field(..., ge=0)
    total_cost_bdt: float = Field(..., ge=0)
    peak_grid_kwh: float = Field(..., ge=0)
    plan_summary: str



def validate_directive(
    directive: DirectiveInterpretation,
) -> DirectiveInterpretation:

    adjustment = directive.structured_adjustment

    # -----------------------------
    # NO OP
    # -----------------------------

    if directive.directive_type == DirectiveType.NO_OP:

        if directive.applies:
            raise ValueError(
                "no_op directive must have applies=false"
            )

        if adjustment is not None:
            raise ValueError(
                "no_op directive must have "
                "structured_adjustment=null"
            )

        return directive

    # -----------------------------
    # ACTIONABLE DIRECTIVE
    # -----------------------------

    if not directive.applies:
        raise ValueError(
            f"{directive.directive_type.value} "
            "must have applies=true"
        )

    if adjustment is None:
        raise ValueError(
            f"{directive.directive_type.value} "
            "requires structured_adjustment"
        )

    # -----------------------------
    # SOLAR REDUCTION
    # -----------------------------

    if directive.directive_type == DirectiveType.SOLAR_REDUCTION:

        if not isinstance(
            adjustment,
            SolarReductionAdjustment,
        ):
            raise ValueError(
                "solar_reduction requires "
                "SolarReductionAdjustment"
            )

        validate_hours(adjustment.hours)

    # -----------------------------
    # MINIMUM BATTERY RESERVE
    # -----------------------------

    elif (
        directive.directive_type
        == DirectiveType.MINIMUM_BATTERY_RESERVE
    ):

        if not isinstance(
            adjustment,
            MinimumBatteryReserveAdjustment,
        ):
            raise ValueError(
                "minimum_battery_reserve requires "
                "MinimumBatteryReserveAdjustment"
            )

        validate_hours(adjustment.hours)

    # -----------------------------
    # NO CHARGE
    # -----------------------------

    elif directive.directive_type == DirectiveType.NO_CHARGE_WINDOW:

        if not isinstance(adjustment, WindowAdjustment):
            raise ValueError(
                "no_charge_window requires WindowAdjustment"
            )

        validate_hours(adjustment.hours)

    # -----------------------------
    # NO DISCHARGE
    # -----------------------------

    elif (
        directive.directive_type
        == DirectiveType.NO_DISCHARGE_WINDOW
    ):

        if not isinstance(adjustment, WindowAdjustment):
            raise ValueError(
                "no_discharge_window requires WindowAdjustment"
            )

        validate_hours(adjustment.hours)

    # -----------------------------
    # MAX GRID
    # -----------------------------

    elif directive.directive_type == DirectiveType.MAX_GRID_WINDOW:

        if not isinstance(
            adjustment,
            MaxGridWindowAdjustment,
        ):
            raise ValueError(
                "max_grid_window requires "
                "MaxGridWindowAdjustment"
            )

        validate_hours(adjustment.hours)

    return directive


def validate_hours(hours: list[int]) -> None:

    if not hours:
        raise ValueError(
            "Directive must contain at least one hour"
        )

    if any(hour < 0 or hour > 23 for hour in hours):
        raise ValueError(
            "Hours must be between 0 and 23"
        )

    if len(hours) != len(set(hours)):
        raise ValueError(
            "Hours must not contain duplicates"
        )