from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from mcp_beancount.config import AppConfig
from mcp_beancount.ledger import LedgerManager


@pytest.fixture()
def ledger_path(tmp_path: Path) -> Path:
    source = Path(__file__).parent / "fixtures" / "example.beancount"
    target = tmp_path / "example.beancount"
    shutil.copy(source, target)
    return target


@pytest.fixture()
def ledger_manager(ledger_path: Path, tmp_path: Path) -> LedgerManager:
    config = AppConfig(ledger_path=ledger_path, backup_dir=tmp_path / "backups")
    return LedgerManager(config)


@pytest.fixture()
def ledger_config(ledger_path: Path, tmp_path: Path) -> AppConfig:
    return AppConfig(ledger_path=ledger_path, backup_dir=tmp_path / "backups")
