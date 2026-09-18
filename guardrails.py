from models import (
    DirectiveInterpretation,
    DirectiveType,
    SolarReductionAdjustment,
    MinimumBatteryReserveAdjustment,
    WindowAdjustment,
    MaxGridWindowAdjustment,
)


# ============================================================
# Constants
# ============================================================

MIN_HOUR = 0
MAX_HOUR = 23


# ============================================================
# Public API
# ============================================================

def validate_directive(
    directive: DirectiveInterpretation,
) -> DirectiveInterpretation:
    """
    Validate one LLM-generated directive.

    This function does not modify the energy schedule.
    It only verifies that the interpreted directive is valid
    according to the problem constraints.
    """

    validate_note_index(directive)
    validate_explanation(directive)

    if directive.directive_type == DirectiveType.NO_OP:
        validate_no_op(directive)
    else:
        validate_actionable_directive(directive)

    return directive


def validate_directives(
    directives: list[DirectiveInterpretation],
    expected_count: int,
) -> list[DirectiveInterpretation]:
    """
    Validate the complete set of LLM-generated directives.
    """

    if len(directives) != expected_count:
        raise ValueError(
            f"Expected {expected_count} directive interpretations, "
            f"got {len(directives)}"
        )

    note_indexes = []

    for directive in directives:
        validate_directive(directive)
        note_indexes.append(directive.note_index)

    # Every note must have exactly one interpretation.
    expected_indexes = set(range(expected_count))

    if set(note_indexes) != expected_indexes:
        raise ValueError(
            "Directive interpretations must contain exactly "
            "one result for every operator note"
        )

    if len(note_indexes) != len(set(note_indexes)):
        raise ValueError(
            "Duplicate note_index found in directive interpretations"
        )

    return directives


# ============================================================
# General Validation
# ============================================================

def validate_note_index(
    directive: DirectiveInterpretation,
) -> None:

    if directive.note_index < 0:
        raise ValueError(
            "note_index cannot be negative"
        )


def validate_explanation(
    directive: DirectiveInterpretation,
) -> None:

    if not directive.explanation.strip():
        raise ValueError(
            "Directive explanation cannot be empty"
        )

    if len(directive.explanation) > 500:
        raise ValueError(
            "Directive explanation is too long"
        )


# ============================================================
# NO OP
# ============================================================

def validate_no_op(
    directive: DirectiveInterpretation,
) -> None:

    if directive.applies:
        raise ValueError(
            "no_op directive must have applies=false"
        )

    if directive.structured_adjustment is not None:
        raise ValueError(
            "no_op directive must have "
            "structured_adjustment=null"
        )


# ============================================================
# Actionable Directives
# ============================================================

def validate_actionable_directive(
    directive: DirectiveInterpretation,
) -> None:

    if not directive.applies:
        raise ValueError(
            f"{directive.directive_type.value} "
            "must have applies=true"
        )

    if directive.structured_adjustment is None:
        raise ValueError(
            f"{directive.directive_type.value} requires "
            "structured_adjustment"
        )

    directive_type = directive.directive_type
    adjustment = directive.structured_adjustment

    if directive_type == DirectiveType.SOLAR_REDUCTION:
        validate_solar_reduction(adjustment)

    elif directive_type == DirectiveType.MINIMUM_BATTERY_RESERVE:
        validate_minimum_battery_reserve(adjustment)

    elif directive_type == DirectiveType.NO_CHARGE_WINDOW:
        validate_no_charge_window(adjustment)

    elif directive_type == DirectiveType.NO_DISCHARGE_WINDOW:
        validate_no_discharge_window(adjustment)

    elif directive_type == DirectiveType.MAX_GRID_WINDOW:
        validate_max_grid_window(adjustment)

    else:
        raise ValueError(
            f"Unsupported directive type: {directive_type}"
        )


# ============================================================
# SOLAR REDUCTION
# ============================================================

def validate_solar_reduction(
    adjustment,
) -> None:

    if not isinstance(
        adjustment,
        SolarReductionAdjustment,
    ):
        raise ValueError(
            "solar_reduction must use "
            "SolarReductionAdjustment"
        )

    validate_hours(adjustment.hours)

    if not 0 <= adjustment.factor <= 1:
        raise ValueError(
            "solar_reduction factor must be between 0 and 1"
        )


# ============================================================
# MINIMUM BATTERY RESERVE
# ============================================================

def validate_minimum_battery_reserve(
    adjustment,
) -> None:

    if not isinstance(
        adjustment,
        MinimumBatteryReserveAdjustment,
    ):
        raise ValueError(
            "minimum_battery_reserve must use "
            "MinimumBatteryReserveAdjustment"
        )

    validate_hours(adjustment.hours)

    if adjustment.minimum_energy_kwh < 0:
        raise ValueError(
            "minimum_energy_kwh cannot be negative"
        )


# ============================================================
# NO CHARGE WINDOW
# ============================================================

def validate_no_charge_window(
    adjustment,
) -> None:

    if not isinstance(
        adjustment,
        WindowAdjustment,
    ):
        raise ValueError(
            "no_charge_window must use WindowAdjustment"
        )

    validate_hours(adjustment.hours)


# ============================================================
# NO DISCHARGE WINDOW
# ============================================================

def validate_no_discharge_window(
    adjustment,
) -> None:

    if not isinstance(
        adjustment,
        WindowAdjustment,
    ):
        raise ValueError(
            "no_discharge_window must use WindowAdjustment"
        )

    validate_hours(adjustment.hours)


# ============================================================
# MAX GRID WINDOW
# ============================================================

def validate_max_grid_window(
    adjustment,
) -> None:

    if not isinstance(
        adjustment,
        MaxGridWindowAdjustment,
    ):
        raise ValueError(
            "max_grid_window must use "
            "MaxGridWindowAdjustment"
        )

    validate_hours(adjustment.hours)

    if adjustment.max_grid_kwh < 0:
        raise ValueError(
            "max_grid_kwh cannot be negative"
        )


# ============================================================
# Hour Validation
# ============================================================

def validate_hours(
    hours: list[int],
) -> None:

    if not hours:
        raise ValueError(
            "Directive must contain at least one hour"
        )

    for hour in hours:

        if not isinstance(hour, int):
            raise ValueError(
                "Directive hours must be integers"
            )

        if hour < MIN_HOUR or hour > MAX_HOUR:
            raise ValueError(
                f"Invalid hour {hour}. "
                "Hours must be between 0 and 23."
            )

    if len(hours) != len(set(hours)):
        raise ValueError(
            "Directive hours must not contain duplicates"
        )

    # Keep hours deterministic.
    if hours != sorted(hours):
        raise ValueError(
            "Directive hours must be sorted in ascending order"
        )