from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from mcp_beancount.exceptions import TransactionNotFoundError, TransactionValidationError
from mcp_beancount.ledger import LedgerManager
from mcp_beancount.schemas import (
    BalanceRequest,
    IncomeSheetRequest,
    InsertTransactionRequest,
    ListTransactionsRequest,
    NaturalLanguageRequest,
    PostingInput,
    RemoveTransactionRequest,
)


def test_list_accounts_includes_fixture_accounts(ledger_manager: LedgerManager) -> None:
    result = ledger_manager.list_accounts()
    names = {account.name for account in result.accounts}
    assert "Assets:Bank:Checking" in names
    assert "Expenses:Food" in names
    assert not result.errors


def test_balance_returns_expected_amount(ledger_manager: LedgerManager) -> None:
    request = BalanceRequest(accounts=["Assets:Bank"], include_children=True, end_date=dt.date(2020, 1, 31))
    result = ledger_manager.balance(request)
    checking = next(acc for acc in result.balances if acc.account == "Assets:Bank:Checking")
    assert checking.balance[0].number == "1649.75"
    assert checking.balance[0].currency == "USD"


def test_income_sheet_totals(ledger_manager: LedgerManager) -> None:
    request = IncomeSheetRequest(start_date=dt.date(2020, 1, 1), end_date=dt.date(2020, 1, 31), convert_to=None)
    result = ledger_manager.income_sheet(request)
    income_total = sum(float(amount.number) for row in result.income for amount in row.amount)
    expense_total = sum(float(amount.number) for row in result.expenses for amount in row.amount)
    net_total = sum(float(amount.number) for amount in result.net)
    assert pytest.approx(income_total) == -3000.0
    assert pytest.approx(expense_total) == 1350.25
    assert pytest.approx(net_total) == -1649.75


def test_list_transactions_filters_by_payee(ledger_manager: LedgerManager) -> None:
    request = ListTransactionsRequest(payee="Landlord")
    result = ledger_manager.list_transactions(request)
    assert result.total == 1
    transaction = result.transactions[0]
    assert transaction.payee == "Landlord"
    assert len(transaction.postings) == 2


def test_insert_transaction_dry_run_does_not_modify_file(ledger_manager: LedgerManager, ledger_path: Path) -> None:
    original = ledger_path.read_text(encoding="utf-8")
    request = InsertTransactionRequest(
        date=dt.date(2020, 1, 15),
        payee="Coffee Shop",
        narration="Coffee",
        postings=[
            PostingInput(account="Expenses:Food", amount="5.00", currency="USD"),
            PostingInput(account="Assets:Bank:Checking", amount="-5.00", currency="USD"),
        ],
        dry_run=True,
    )
    result = ledger_manager.insert_transaction(request)
    assert result.dry_run is True
    assert ledger_path.read_text(encoding="utf-8") == original
    assert "Coffee Shop" in result.diff


def test_insert_and_remove_transaction(ledger_manager: LedgerManager, ledger_path: Path) -> None:
    original = ledger_path.read_text(encoding="utf-8")
    insert_request = InsertTransactionRequest(
        date=dt.date(2020, 1, 20),
        payee="Book Store",
        narration="Books",
        postings=[
            PostingInput(account="Expenses:Food", amount="20.00", currency="USD"),
            PostingInput(account="Assets:Bank:Checking", amount="-20.00", currency="USD"),
        ],
    )
    insert_result = ledger_manager.insert_transaction(insert_request)
    assert insert_result.dry_run is False
    txn_id = insert_result.txn_id
    ledger_manager.load(force=True)

    remove_result = ledger_manager.remove_transaction(RemoveTransactionRequest(txn_id=txn_id))
    assert remove_result.dry_run is False
    assert ledger_path.read_text(encoding="utf-8") == original


def test_remove_transaction_missing_id(ledger_manager: LedgerManager) -> None:
    with pytest.raises(TransactionNotFoundError):
        ledger_manager.remove_transaction(RemoveTransactionRequest(txn_id="missing"))


def test_insert_transaction_requires_balanced_postings(ledger_manager: LedgerManager) -> None:
    request = InsertTransactionRequest(
        date=dt.date(2020, 1, 15),
        payee="Mismatch",
        narration="Uneven",
        postings=[
            PostingInput(account="Expenses:Food", amount="5.00", currency="USD"),
            PostingInput(account="Assets:Bank:Checking", amount="-6.00", currency="USD"),
        ],
    )
    with pytest.raises(TransactionValidationError):
        ledger_manager.insert_transaction(request)


def test_run_query_and_natural_language(ledger_manager: LedgerManager) -> None:
    query_result = ledger_manager.run_query("SELECT sum(position) WHERE account ~ '^Expenses'")
    assert query_result.columns == ["sum(position) (USD)"]
    assert query_result.rows[0][0] == "1350.25"

    nl_result = ledger_manager.natural_language_query(
        NaturalLanguageRequest(question="Balance of Assets:Bank as of 2020-01-31")
    )
    assert "Assets:Bank" in nl_result.query
    assert nl_result.rows
