from __future__ import annotations

import datetime as dt
from typing import Any

from pydantic import BaseModel, Field, ValidationInfo, field_validator

from .utils import decimal_to_string


class AmountModel(BaseModel):
    number: str
    currency: str

    @classmethod
    def from_amount(cls, amount) -> "AmountModel":  # type: ignore[override]
        return cls(number=decimal_to_string(amount.number), currency=amount.currency)


class InventoryModel(BaseModel):
    positions: list[AmountModel] = Field(default_factory=list)

    @classmethod
    def from_inventory(cls, inv) -> "InventoryModel":  # type: ignore[override]
        from beancount.core.inventory import Inventory

        if isinstance(inv, Inventory):
            positions = [AmountModel(number=decimal_to_string(pos.units.number), currency=pos.units.currency) for pos in inv]
        else:  # assume iterable of Amount
            positions = [AmountModel(number=decimal_to_string(pos.number), currency=pos.currency) for pos in inv]
        return cls(positions=positions)


class AccountInfo(BaseModel):
    name: str
    type: str
    open_date: dt.date | None = None
    close_date: dt.date | None = None
    currencies: list[str] = Field(default_factory=list)
    booking: str | None = None
    meta: dict[str, Any] = Field(default_factory=dict)


class ListAccountsResult(BaseModel):
    accounts: list[AccountInfo]
    errors: list[str] = Field(default_factory=list)


class BalanceRequest(BaseModel):
    accounts: list[str] | None = None
    include_children: bool = True
    start_date: dt.date | None = None
    end_date: dt.date | None = None
    at_date: dt.date | None = None
    convert_to: str | None = None
    rollup: bool = False

    @field_validator("end_date")
    def _validate_dates(cls, v, values: ValidationInfo):  # type: ignore[override]
        start = values.data.get("start_date")
        if start and v and v < start:
            raise ValueError("end_date must not precede start_date")
        return v


class AccountBalance(BaseModel):
    account: str
    balance: list[AmountModel]


class BalanceResult(BaseModel):
    balances: list[AccountBalance]
    total: list[AmountModel]
    as_of: dt.date | None = None


class IncomeSheetRequest(BaseModel):
    start_date: dt.date
    end_date: dt.date
    convert_to: str | None = None


class IncomeCategory(BaseModel):
    account: str
    amount: list[AmountModel]


class IncomeSheetResult(BaseModel):
    income: list[IncomeCategory]
    expenses: list[IncomeCategory]
    net: list[AmountModel]


class CostModel(BaseModel):
    number: str
    currency: str
    date: dt.date | None = None
    label: str | None = None


class TransactionPostingModel(BaseModel):
    account: str
    units: AmountModel
    cost: CostModel | None = None
    price: AmountModel | None = None
    meta: dict[str, Any] = Field(default_factory=dict)


class TransactionModel(BaseModel):
    txn_id: str | None = None
    date: dt.date
    flag: str | None = None
    payee: str | None = None
    narration: str | None = None
    tags: list[str] = Field(default_factory=list)
    meta: dict[str, Any] = Field(default_factory=dict)
    postings: list[TransactionPostingModel]


class ListTransactionsRequest(BaseModel):
    start_date: dt.date | None = None
    end_date: dt.date | None = None
    accounts: list[str] | None = None
    payee: str | None = None
    narration: str | None = None
    tags: list[str] | None = None
    metadata: dict[str, Any] | None = None
    limit: int | None = Field(default=50, ge=0)
    offset: int = Field(default=0, ge=0)
    include_postings: bool = True


class ListTransactionsResult(BaseModel):
    total: int
    transactions: list[TransactionModel]


class PostingInput(BaseModel):
    account: str
    amount: str
    currency: str
    cost_amount: str | None = None
    cost_currency: str | None = None
    cost_date: dt.date | None = None
    cost_label: str | None = None
    price_amount: str | None = None
    price_currency: str | None = None
    meta: dict[str, Any] | None = None


class InsertTransactionRequest(BaseModel):
    date: dt.date
    flag: str | None = None
    payee: str | None = None
    narration: str | None = None
    postings: list[PostingInput]
    tags: list[str] | None = None
    meta: dict[str, Any] | None = None
    txn_id: str | None = None
    dry_run: bool | None = None


class InsertTransactionResult(BaseModel):
    txn_id: str
    dry_run: bool
    diff: str


class RemoveTransactionRequest(BaseModel):
    txn_id: str
    dry_run: bool | None = None


class RemoveTransactionResult(BaseModel):
    txn_id: str
    dry_run: bool
    diff: str


class BeanQueryRequest(BaseModel):
    query: str


class BeanQueryResult(BaseModel):
    columns: list[str]
    rows: list[list[Any]]


class NaturalLanguageRequest(BaseModel):
    question: str


class NaturalLanguageResult(BaseModel):
    query: str
    columns: list[str]
    rows: list[list[Any]]
