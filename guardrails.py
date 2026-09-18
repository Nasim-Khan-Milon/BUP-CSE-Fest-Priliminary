
from models import (
    DirectiveInterpretation,
    DirectiveType,
    SolarReductionAdjustment,
    MinimumBatteryReserveAdjustment,
    WindowAdjustment,
    MaxGridWindowAdjustment,
)


# ============================================================
# Public API
# ============================================================

def validate_directive(
    directive: DirectiveInterpretation,
) -> DirectiveInterpretation:
    """
    Custom guardrails for a single directive.

    Pydantic handles basic type/value validation.
    These checks enforce the problem-specific directive rules.
    """

    adjustment = directive.structured_adjustment

    # --------------------------------------------------------
    # NO OP
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # ACTIONABLE DIRECTIVE
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # SOLAR REDUCTION
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # MINIMUM BATTERY RESERVE
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # NO CHARGE WINDOW
    # --------------------------------------------------------

    elif directive.directive_type == DirectiveType.NO_CHARGE_WINDOW:

        if not isinstance(
            adjustment,
            WindowAdjustment,
        ):
            raise ValueError(
                "no_charge_window requires "
                "WindowAdjustment"
            )

        validate_hours(adjustment.hours)

    # --------------------------------------------------------
    # NO DISCHARGE WINDOW
    # --------------------------------------------------------

    elif (
        directive.directive_type
        == DirectiveType.NO_DISCHARGE_WINDOW
    ):

        if not isinstance(
            adjustment,
            WindowAdjustment,
        ):
            raise ValueError(
                "no_discharge_window requires "
                "WindowAdjustment"
            )

        validate_hours(adjustment.hours)

    # --------------------------------------------------------
    # MAX GRID WINDOW
    # --------------------------------------------------------

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


# ============================================================
# Validate Complete Directive List
# ============================================================

def validate_directives(
    directives: list[DirectiveInterpretation],
    expected_count: int,
) -> list[DirectiveInterpretation]:
    """
    Custom guardrails for the complete directive list.

    The problem requires exactly one interpretation per note
    and requires the entries to appear in note_index order.
    """

    if len(directives) != expected_count:
        raise ValueError(
            f"Expected {expected_count} directive interpretations, "
            f"got {len(directives)}"
        )

    # Validate every directive.
    for directive in directives:
        validate_directive(directive)

    # Required order:
    #
    # note_index = 0, 1, 2, ..., N-1
    expected_indexes = list(range(expected_count))

    actual_indexes = [
        directive.note_index
        for directive in directives
    ]

    if actual_indexes != expected_indexes:
        raise ValueError(
            "Directive interpretations must be returned "
            "in note_index order: 0, 1, ..., N-1"
        )

    return directives


# ============================================================
# Hour Guardrails
# ============================================================

def validate_hours(
    hours: list[int],
) -> None:
    """
    Problem requirements:

    - hours must contain integers from 0 through 23
    - hours must be unique
    - hours must be ascending

    Basic integer/range validation is also present in the
    Pydantic models; these checks protect the custom layer
    independently.
    """

    if any(type(hour) is not int for hour in hours):
        raise ValueError(
            "Directive hours must be integers"
        )

    if any(hour < 0 or hour > 23 for hour in hours):
        raise ValueError(
            "Directive hours must be between 0 and 23"
        )

    if len(hours) != len(set(hours)):
        raise ValueError(
            "Directive hours must be unique"
        )

    if hours != sorted(hours):
        raise ValueError(
            "Directive hours must be in ascending order"
        )
