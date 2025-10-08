from __future__ import annotations

import datetime as dt
import difflib
import io
import os
import shutil
import tempfile
import threading
import uuid
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Iterable, Sequence

from beanquery import query as beanquery
from beancount import api
from beancount.core import data, inventory, prices
from beancount.core.amount import Amount
from beancount.core.number import D
from beancount.core.position import Cost
from beancount.loader import load_file
from beancount.parser.printer import format_entry, print_errors

from .config import AppConfig
from .exceptions import (
    LedgerLoadError,
    LedgerValidationError,
    NaturalLanguageError,
    TransactionNotFoundError,
    TransactionValidationError,
)
from .locking import FileLock
from .schemas import (
    AccountBalance,
    AccountInfo,
    BalanceRequest,
    BalanceResult,
    BeanQueryResult,
    IncomeCategory,
    IncomeSheetRequest,
    IncomeSheetResult,
    InsertTransactionRequest,
    InsertTransactionResult,
    ListAccountsResult,
    ListTransactionsRequest,
    ListTransactionsResult,
    NaturalLanguageRequest,
    NaturalLanguageResult,
    RemoveTransactionRequest,
    RemoveTransactionResult,
    TransactionModel,
    TransactionPostingModel,
)
from .utils import decimal_to_string, parse_decimal
from . import nl


@dataclass(slots=True)
class LedgerSnapshot:
    entries: data.Directives
    errors: list[data.BeancountError]
    options_map: dict[str, object]
    price_map: api.PriceMap
    text: str
    mtime: float
    size: int


def _error_messages(errors: Sequence[data.BeancountError]) -> list[str]:
    if not errors:
        return []
    messages: list[str] = []
    for err in errors:
        buffer = io.StringIO()
        print_errors([err], file=buffer)
        messages.append(buffer.getvalue().strip())
    return messages


class LedgerManager:
    """High-level operations over a Beancount ledger."""

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.ledger_path = config.ledger_path
        self._snapshot: LedgerSnapshot | None = None
        self._lock = threading.RLock()

    # ------------------------------------------------------------------ Loading

    def load(self, *, force: bool = False) -> LedgerSnapshot:
        with self._lock:
            stat = self.ledger_path.stat()
            if (
                not force
                and self._snapshot is not None
                and self._snapshot.mtime == stat.st_mtime
                and self._snapshot.size == stat.st_size
            ):
                return self._snapshot

            text = self.ledger_path.read_text(encoding="utf-8")
            entries, errors, options_map = load_file(str(self.ledger_path))
            price_map = prices.build_price_map(entries)
            snapshot = LedgerSnapshot(
                entries=entries,
                errors=list(errors),
                options_map=options_map,
                price_map=price_map,
                text=text,
                mtime=stat.st_mtime,
                size=stat.st_size,
            )
            self._snapshot = snapshot
            return snapshot

    # ----------------------------------------------------------------- Accounts

    def list_accounts(self, include_closed: bool = False) -> ListAccountsResult:
        snapshot = self.load()
        errors = _error_messages(snapshot.errors)

        open_entries: dict[str, data.Open] = {}
        close_entries: dict[str, data.Close] = {}
        currencies: dict[str, set[str]] = defaultdict(set)
        booking: dict[str, str | None] = {}
        metadata: dict[str, dict[str, object]] = {}

        for entry in snapshot.entries:
            if isinstance(entry, data.Open):
                open_entries[entry.account] = entry
                booking[entry.account] = entry.booking
                metadata[entry.account] = _clean_meta(entry.meta)
                for curr in entry.currencies or []:
                    currencies[entry.account].add(curr)
            elif isinstance(entry, data.Close):
                close_entries[entry.account] = entry
            elif isinstance(entry, data.Transaction):
                for posting in entry.postings:
                    currencies[posting.account].add(posting.units.currency)

        accounts = set(open_entries) | set(currencies) | set(close_entries)
        infos: list[AccountInfo] = []
        for account in sorted(accounts):
            closed = account in close_entries
            if closed and not include_closed:
                continue
            open_entry = open_entries.get(account)
            close_entry = close_entries.get(account)
            infos.append(
                AccountInfo(
                    name=account,
                    type=api.get_account_type(account) or "Unknown",
                    open_date=getattr(open_entry, "date", None),
                    close_date=getattr(close_entry, "date", None),
                    currencies=sorted(currencies.get(account, set())),
                    booking=booking.get(account),
                    meta=metadata.get(account, {}),
                )
            )

        return ListAccountsResult(accounts=infos, errors=errors)

    # ----------------------------------------------------------------- Balances

    def balance(self, request: BalanceRequest) -> BalanceResult:
        snapshot = self.load()
        entries = self._filter_entries(snapshot.entries, request.start_date, request.end_date, request.at_date)

        balances: dict[str, inventory.Inventory] = defaultdict(inventory.Inventory)
        total = inventory.Inventory()
        account_filters = request.accounts or []

        for entry in entries:
            if isinstance(entry, data.Transaction):
                for posting in entry.postings:
                    if account_filters and not _account_matches(posting.account, account_filters, request.include_children):
                        continue
                    balances[posting.account].add_amount(posting.units)
                    total.add_amount(posting.units)

        converted_balances = [
            AccountBalance(account=account, balance=_inventory_to_amounts(inv, snapshot.price_map, request.convert_to, request.end_date))
            for account, inv in sorted(balances.items())
        ]
        total_amounts = _inventory_to_amounts(total, snapshot.price_map, request.convert_to, request.end_date)

        return BalanceResult(balances=converted_balances, total=total_amounts, as_of=request.end_date or request.at_date)

    # --------------------------------------------------------------- Income sheet

    def income_sheet(self, request: IncomeSheetRequest) -> IncomeSheetResult:
        snapshot = self.load()
        entries = self._filter_entries(snapshot.entries, request.start_date, request.end_date, None)

        income_balances: dict[str, inventory.Inventory] = defaultdict(inventory.Inventory)
        expense_balances: dict[str, inventory.Inventory] = defaultdict(inventory.Inventory)

        for entry in entries:
            if isinstance(entry, data.Transaction):
                for posting in entry.postings:
                    if posting.account.startswith("Income:"):
                        income_balances[posting.account].add_amount(posting.units)
                    elif posting.account.startswith("Expenses:"):
                        expense_balances[posting.account].add_amount(posting.units)

        income = [
            IncomeCategory(account=account, amount=_inventory_to_amounts(inv, snapshot.price_map, request.convert_to, request.end_date))
            for account, inv in sorted(income_balances.items())
        ]
        expenses = [
            IncomeCategory(account=account, amount=_inventory_to_amounts(inv, snapshot.price_map, request.convert_to, request.end_date))
            for account, inv in sorted(expense_balances.items())
        ]

        net_inventory = inventory.Inventory()
        for inv in income_balances.values():
            net_inventory.add_inventory(inv)
        for inv in expense_balances.values():
            net_inventory.add_inventory(inv)
        net = _inventory_to_amounts(net_inventory, snapshot.price_map, request.convert_to, request.end_date)

        return IncomeSheetResult(income=income, expenses=expenses, net=net)

    # -------------------------------------------------------------- Transactions

    def list_transactions(self, request: ListTransactionsRequest) -> ListTransactionsResult:
        snapshot = self.load()
        matches: list[data.Transaction] = []
        accounts = request.accounts or []

        for entry in snapshot.entries:
            if not isinstance(entry, data.Transaction):
                continue
            if request.start_date and entry.date < request.start_date:
                continue
            if request.end_date and entry.date > request.end_date:
                continue
            if request.payee and (entry.payee or "").lower().find(request.payee.lower()) == -1:
                continue
            if request.narration and (entry.narration or "").lower().find(request.narration.lower()) == -1:
                continue
            if request.tags and not set(request.tags).issubset(entry.tags or set()):
                continue
            if request.metadata:
                if not _metadata_matches(entry.meta, request.metadata):
                    continue
            if accounts:
                if not any(_account_matches(posting.account, accounts, True) for posting in entry.postings):
                    continue
            matches.append(entry)

        total = len(matches)
        start = request.offset
        end = None if request.limit is None else start + request.limit
        selected = matches[start:end] if end is not None else matches[start:]

        transactions = [_to_transaction_model(txn, include_postings=request.include_postings) for txn in selected]
        return ListTransactionsResult(total=total, transactions=transactions)

    # ---------------------------------------------------------------- Mutations

    def insert_transaction(self, request: InsertTransactionRequest) -> InsertTransactionResult:
        snapshot = self.load()
        dry_run = request.dry_run if request.dry_run is not None else self.config.dry_run_default
        txn_id = request.txn_id or str(uuid.uuid4())

        if self._transaction_exists(snapshot.entries, txn_id):
            raise TransactionValidationError(f"Transaction with txn_id '{txn_id}' already exists.")

        transaction = _build_transaction(request, txn_id)
        formatted = format_entry(transaction)

        new_text = _append_entry(snapshot.text, formatted)
        self._validate_text(new_text)

        diff = _diff(snapshot.text, new_text, self.ledger_path.name)
        if dry_run:
            return InsertTransactionResult(txn_id=txn_id, dry_run=True, diff=diff)

        self._write_ledger(new_text)
        self.load(force=True)
        return InsertTransactionResult(txn_id=txn_id, dry_run=False, diff=diff)

    def remove_transaction(self, request: RemoveTransactionRequest) -> RemoveTransactionResult:
        snapshot = self.load()
        dry_run = request.dry_run if request.dry_run is not None else self.config.dry_run_default
        transaction = self._get_transaction(snapshot.entries, request.txn_id)
        new_text = _remove_entry(snapshot.text, transaction)
        self._validate_text(new_text)
        diff = _diff(snapshot.text, new_text, self.ledger_path.name)

        if dry_run:
            return RemoveTransactionResult(txn_id=request.txn_id, dry_run=True, diff=diff)

        self._write_ledger(new_text)
        self.load(force=True)
        return RemoveTransactionResult(txn_id=request.txn_id, dry_run=False, diff=diff)

    # ------------------------------------------------------------------- Queries

    def run_query(self, query_text: str) -> BeanQueryResult:
        snapshot = self.load()
        columns, rows = beanquery.run_query(snapshot.entries, snapshot.options_map, query_text, numberify=True)
        column_names = [column.name for column in columns]
        serialised_rows = [_serialise_row(row) for row in rows]
        return BeanQueryResult(columns=column_names, rows=serialised_rows)

    def natural_language_query(self, request: NaturalLanguageRequest) -> NaturalLanguageResult:
        if not self.config.enable_nl:
            raise NaturalLanguageError("Natural-language querying is disabled by configuration.")

        query_text = nl.render_query(request.question, self.config)
        result = self.run_query(query_text)
        return NaturalLanguageResult(query=query_text, columns=result.columns, rows=result.rows)

    # -------------------------------------------------------------- Helper logic

    def _write_ledger(self, text: str) -> None:
        lock = FileLock(self.ledger_path, timeout=self.config.lock_timeout)
        with lock:
            backup_dir = self.config.backup_dir
            backup_dir.mkdir(parents=True, exist_ok=True)
            timestamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d-%H%M%S")
            backup_path = backup_dir / f"{self.ledger_path.name}.{timestamp}.bak"
            shutil.copy2(self.ledger_path, backup_path)
            self._prune_backups()

            fd, tmp_path = tempfile.mkstemp(
                suffix=".tmp",
                dir=str(self.ledger_path.parent),
            )
            os.close(fd)
            try:
                mode = os.stat(self.ledger_path).st_mode
            except FileNotFoundError:  # pragma: no cover - defensive
                mode = None
            with open(tmp_path, "w", encoding="utf-8") as handle:
                handle.write(text)
            if mode is not None:
                os.chmod(tmp_path, mode)
            os.replace(tmp_path, self.ledger_path)

    def _prune_backups(self) -> None:
        retention = self.config.backup_retention
        if retention is None or retention <= 0:
            return
        backups = sorted(self.config.backup_dir.glob(f"{self.ledger_path.name}.*.bak"), reverse=True)
        for path in backups[retention:]:
            path.unlink(missing_ok=True)

    def _validate_text(self, text: str) -> None:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            suffix=".beancount",
            delete=False,
            dir=self.ledger_path.parent,
        ) as tmp:
            tmp.write(text)
            tmp_path = Path(tmp.name)
        try:
            entries, errors, _ = load_file(tmp_path)
            if errors:
                raise LedgerValidationError("; ".join(_error_messages(errors)))
        finally:
            tmp_path.unlink(missing_ok=True)

    def _filter_entries(
        self,
        entries: Sequence[data.Directive],
        start: dt.date | None,
        end: dt.date | None,
        at: dt.date | None,
    ) -> Iterable[data.Directive]:
        for entry in entries:
            entry_date = getattr(entry, "date", None)
            if isinstance(entry_date, dt.date):
                if start and entry_date < start:
                    continue
                if end and entry_date > end:
                    continue
                if at and entry_date > at:
                    continue
            yield entry

    def _transaction_exists(self, entries: Sequence[data.Directive], txn_id: str) -> bool:
        try:
            self._get_transaction(entries, txn_id)
        except TransactionNotFoundError:
            return False
        return True

    def _get_transaction(self, entries: Sequence[data.Directive], txn_id: str) -> data.Transaction:
        matches = [
            entry
            for entry in entries
            if isinstance(entry, data.Transaction) and entry.meta.get("txn_id") == txn_id
        ]
        if not matches:
            raise TransactionNotFoundError(f"No transaction found with txn_id '{txn_id}'")
        if len(matches) > 1:
            raise TransactionValidationError(f"Multiple transactions share txn_id '{txn_id}'")
        return matches[0]


# --------------------------------------------------------------------------- utils


def _account_matches(account: str, filters: Sequence[str], include_children: bool) -> bool:
    for prefix in filters:
        if account == prefix:
            return True
        if include_children and account.startswith(prefix + ":"):
            return True
    return False


def _inventory_to_amounts(
    inv: inventory.Inventory,
    price_map: api.PriceMap,
    convert_to: str | None,
    date: dt.date | None,
) -> list:
    result = inv
    if convert_to:
        result = inv.reduce(api.convert_position, convert_to, price_map, date)
    amounts = []
    for position in result:
        amount = position.units if hasattr(position, "units") else position
        amounts.append(
            {
                "number": decimal_to_string(amount.number),
                "currency": amount.currency,
            }
        )
    return amounts


def _metadata_matches(meta: data.Meta | None, expected: dict[str, object]) -> bool:
    if not expected:
        return True
    if not meta:
        return False
    for key, value in expected.items():
        if meta.get(key) != value:
            return False
    return True


def _clean_meta(meta: data.Meta | None) -> dict[str, object]:
    if not meta:
        return {}
    return {
        key: value
        for key, value in meta.items()
        if key not in {"filename", "lineno"}
    }


def _to_transaction_model(txn: data.Transaction, *, include_postings: bool) -> TransactionModel:
    postings: list[TransactionPostingModel] = []
    if include_postings:
        for posting in txn.postings:
            postings.append(
                TransactionPostingModel(
                    account=posting.account,
                    units=_amount_model(posting.units),
                    cost=_cost_model(posting.cost),
                    price=_amount_model(posting.price) if posting.price else None,
                    meta=_clean_meta(posting.meta),
                )
            )
    return TransactionModel(
        txn_id=txn.meta.get("txn_id"),
        date=txn.date,
        flag=txn.flag,
        payee=txn.payee,
        narration=txn.narration,
        tags=sorted(txn.tags or []),
        meta=_clean_meta(txn.meta),
        postings=postings,
    )


def _amount_model(amount: Amount | None) -> dict[str, str] | None:
    if amount is None:
        return None
    return {"number": decimal_to_string(amount.number), "currency": amount.currency}


def _cost_model(cost: Cost | None) -> dict[str, object] | None:
    if cost is None:
        return None
    if not hasattr(cost, "number") or not hasattr(cost, "currency"):
        return None
    return {
        "number": decimal_to_string(cost.number),
        "currency": cost.currency,
        "date": getattr(cost, "date", None),
        "label": getattr(cost, "label", None),
    }


def _build_transaction(request: InsertTransactionRequest, txn_id: str) -> data.Transaction:
    postings: list[data.Posting] = []
    for posting in request.postings:
        amount = Amount(parse_decimal(posting.amount), posting.currency)
        cost = None
        if posting.cost_amount and posting.cost_currency:
            cost = Cost(
                parse_decimal(posting.cost_amount),
                posting.cost_currency,
                posting.cost_date,
                posting.cost_label,
            )
        price = None
        if posting.price_amount and posting.price_currency:
            price = Amount(parse_decimal(posting.price_amount), posting.price_currency)

        postings.append(
            data.Posting(
                account=posting.account,
                units=amount,
                cost=cost,
                price=price,
                flag=None,
                meta=posting.meta or {},
            )
        )

    inv = inventory.Inventory()
    for posting in postings:
        inv.add_amount(posting.units)
    if not inv.is_empty():
        raise TransactionValidationError("Transaction postings must balance.")

    meta = data.new_metadata(str(request.meta.get("source", "")) if request.meta else "generated", 0)
    meta["txn_id"] = txn_id
    if request.meta:
        for key, value in request.meta.items():
            if key in {"filename", "lineno"}:
                continue
            meta[key] = value

    transaction = data.Transaction(
        meta=meta,
        date=request.date,
        flag=request.flag or api.FLAG_OKAY,
        payee=request.payee,
        narration=request.narration,
        tags=frozenset(request.tags or []),
        links=frozenset(),
        postings=postings,
    )
    return transaction


def _append_entry(original: str, entry_text: str) -> str:
    stripped = original.rstrip()
    if not stripped:
        return entry_text + "\n"
    return f"{stripped}\n\n{entry_text}\n"


def _remove_entry(original: str, transaction: data.Transaction) -> str:
    trailing_newlines = len(original) - len(original.rstrip("\n"))
    if trailing_newlines <= 0:
        trailing_newlines = 1
    lines = original.splitlines()
    start = transaction.meta.get("lineno")
    if start is None:
        raise TransactionValidationError("Transaction is missing 'lineno' metadata; cannot remove safely.")

    index = start - 1
    if index < 0 or index >= len(lines):
        raise LedgerLoadError("Transaction line number is out of range.")

    end = index
    while end < len(lines) and lines[end].strip() != "":
        end += 1
    while end < len(lines) and lines[end].strip() == "":
        end += 1

    new_lines = lines[:index] + lines[end:]
    stripped = "\n".join(new_lines).rstrip("\n")
    return stripped + ("\n" * trailing_newlines)


def _diff(before: str, after: str, name: str) -> str:
    diff = difflib.unified_diff(
        before.splitlines(),
        after.splitlines(),
        fromfile=f"{name} (before)",
        tofile=f"{name} (after)",
        lineterm="",
    )
    return "\n".join(diff)


def _serialise_row(row: Sequence[object]) -> list[object]:
    serialised: list[object] = []
    for value in row:
        if hasattr(value, "currency") and hasattr(value, "number"):
            serialised.append({"number": decimal_to_string(value.number), "currency": value.currency})
        elif isinstance(value, inventory.Inventory):
            serialised.append(
                [
                    {"number": decimal_to_string(pos.units.number), "currency": pos.units.currency}
                    for pos in value
                ]
            )
        elif isinstance(value, Decimal):
            serialised.append(decimal_to_string(value))
        elif isinstance(value, dt.date):
            serialised.append(value.isoformat())
        else:
            serialised.append(value)
    return serialised
