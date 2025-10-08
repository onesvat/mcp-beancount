from __future__ import annotations

from pathlib import Path

import beancount.loader as loader
from beancount.core import data as bcdata


def test_fixture_file_exists() -> None:
    path = Path(__file__).parent / "fixtures" / "example.beancount"
    assert path.exists(), f"Missing fixture: {path}"


def test_fixture_parses_cleanly() -> None:
    path = Path(__file__).parent / "fixtures" / "example.beancount"
    entries, errors, _ = loader.load_file(str(path))
    assert not errors, f"Beancount parse/validation errors: {errors}"

    # Confirm we have expected accounts declared via Open directives.
    accounts = {e.account for e in entries if isinstance(e, bcdata.Open)}
    assert {
        "Assets:Bank:Checking",
        "Expenses:Food",
        "Expenses:Rent",
        "Income:Salary",
        "Equity:Opening-Balances",
    }.issubset(accounts)

    # Confirm we have the expected number of transactions.
    txn_count = sum(1 for e in entries if isinstance(e, bcdata.Transaction))
    assert txn_count == 3

