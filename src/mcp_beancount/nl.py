from __future__ import annotations

import calendar
import datetime as dt
import re
from dataclasses import dataclass
from typing import Callable

from .config import AppConfig
from .exceptions import NaturalLanguageError


_SAFE_ACCOUNT = re.compile(r"^[A-Z][A-Za-z0-9:-]*$")


def render_query(question: str, config: AppConfig) -> str:
    """Return a safe BeanQuery string for the provided natural-language question."""

    if not question.strip():
        raise NaturalLanguageError("Question cannot be empty.")

    normalised = question.strip()
    for template in _TEMPLATES:
        match = template.pattern.match(normalised)
        if match:
            return template.builder(match, config)

    raise NaturalLanguageError("Could not map question to a supported query template.")


@dataclass(frozen=True)
class _Template:
    pattern: re.Pattern[str]
    builder: Callable[[re.Match[str], AppConfig], str]


def _balance_builder(match: re.Match[str], _: AppConfig) -> str:
    account = _sanitize_account(match.group("account"))
    date = match.group("date")
    conditions = [f"account ~ '^{account}(:.*)?'"]
    if date:
        _validate_date(date)
        conditions.append(f"date <= date('{date}')")
    where_clause = " AND ".join(conditions)
    return (
        "SELECT account, sum(position) "
        f"WHERE {where_clause} "
        "GROUP BY account ORDER BY account"
    )


def _total_spending_builder(match: re.Match[str], _: AppConfig) -> str:
    start, end = _parse_period(match.group("period"))
    conditions = ["account ~ '^Expenses'"]
    if start:
        conditions.append(f"date >= date('{start.isoformat()}')")
    if end:
        conditions.append(f"date <= date('{end.isoformat()}')")
    where_clause = " AND ".join(conditions)
    return f"SELECT sum(position) WHERE {where_clause}"


def _spending_by_category_builder(match: re.Match[str], _: AppConfig) -> str:
    start, end = _parse_period(match.group("period"))
    conditions = ["account ~ '^Expenses'"]
    if start:
        conditions.append(f"date >= date('{start.isoformat()}')")
    if end:
        conditions.append(f"date <= date('{end.isoformat()}')")
    where_clause = " AND ".join(conditions)
    return (
        "SELECT account, sum(position) "
        f"WHERE {where_clause} "
        "GROUP BY account ORDER BY account"
    )


_TEMPLATES = [
    _Template(
        re.compile(r"(?i)^balance of (?P<account>[A-Za-z0-9:-]+)(?: as of (?P<date>\d{4}-\d{2}-\d{2}))?$"),
        _balance_builder,
    ),
    _Template(
        re.compile(r"(?i)^total spending(?: in (?P<period>.+))?$"),
        _total_spending_builder,
    ),
    _Template(
        re.compile(r"(?i)^spending by category(?: in (?P<period>.+))?$"),
        _spending_by_category_builder,
    ),
]


def _sanitize_account(account: str) -> str:
    if not _SAFE_ACCOUNT.match(account):
        raise NaturalLanguageError("Account names may only contain A-Z, digits, ':', and '-'.")
    return account


def _validate_date(date_text: str) -> None:
    try:
        dt.date.fromisoformat(date_text)
    except ValueError as exc:  # pragma: no cover - defensive
        raise NaturalLanguageError(f"Invalid date '{date_text}'") from exc


def _parse_period(period: str | None) -> tuple[dt.date | None, dt.date | None]:
    if not period:
        return None, None
    trimmed = period.strip()
    if " to " in trimmed:
        start_text, end_text = [part.strip() for part in trimmed.split(" to ", 1)]
        start = dt.date.fromisoformat(start_text)
        end = dt.date.fromisoformat(end_text)
        if end < start:
            raise NaturalLanguageError("End date must be on or after start date.")
        return start, end
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", trimmed):
        date = dt.date.fromisoformat(trimmed)
        return date, date
    if re.fullmatch(r"\d{4}-\d{2}", trimmed):
        year, month = map(int, trimmed.split("-"))
        last_day = calendar.monthrange(year, month)[1]
        return dt.date(year, month, 1), dt.date(year, month, last_day)
    if re.fullmatch(r"\d{4}", trimmed):
        year = int(trimmed)
        return dt.date(year, 1, 1), dt.date(year, 12, 31)
    raise NaturalLanguageError(f"Unsupported period format: '{period}'")
