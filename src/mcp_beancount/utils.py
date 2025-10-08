from __future__ import annotations

import datetime as dt
from decimal import Decimal, InvalidOperation
from typing import Any


def decimal_to_string(value: Decimal) -> str:
    """Render a Decimal deterministically without scientific notation."""
    return format(value, "f")


def parse_decimal(value: str | int | float | Decimal) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:  # pragma: no cover - defensive
        raise ValueError(f"Invalid decimal value '{value}'") from exc


def parse_date(value: str) -> dt.date:
    return dt.date.fromisoformat(value)


def utc_now() -> dt.datetime:
    return dt.datetime.now(tz=dt.timezone.utc)
