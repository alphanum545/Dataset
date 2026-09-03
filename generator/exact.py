from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_CEILING


def parse_positive_decimal(value: str, *, field: str) -> Decimal:
    try:
        parsed = Decimal(value)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{field} must be a valid decimal: {value!r}") from exc
    if not parsed.is_finite() or parsed <= 0:
        raise ValueError(f"{field} must be finite and > 0: {value!r}")
    return parsed


def ceil_decimal(value: Decimal) -> int:
    if not value.is_finite():
        raise ValueError("cannot round a non-finite decimal")
    return int(value.to_integral_value(rounding=ROUND_CEILING))


def ceil_div(numerator: int, denominator: int) -> int:
    if numerator < 0:
        raise ValueError("numerator must be >= 0")
    if denominator <= 0:
        raise ValueError("denominator must be > 0")
    return (numerator + denominator - 1) // denominator


def mul_ratio_floor(value: int, numerator: int, denominator: int) -> int:
    if value < 0 or numerator < 0 or denominator <= 0:
        raise ValueError("invalid rational multiplication operands")
    return value * numerator // denominator


def mul_ratio_ceil(value: int, numerator: int, denominator: int) -> int:
    if value < 0 or numerator < 0 or denominator <= 0:
        raise ValueError("invalid rational multiplication operands")
    return ceil_div(value * numerator, denominator)
