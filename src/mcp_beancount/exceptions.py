from __future__ import annotations


class MCPBeancountError(Exception):
    """Base class for all MCP Beancount errors."""


class ConfigError(MCPBeancountError):
    """Raised when configuration cannot be loaded or is invalid."""


class LedgerLoadError(MCPBeancountError):
    """Raised when the ledger cannot be loaded."""


class LedgerValidationError(LedgerLoadError):
    """Raised when the ledger contains validation errors."""


class FileLockTimeout(MCPBeancountError):
    """Raised when acquiring the ledger file lock times out."""


class TransactionValidationError(MCPBeancountError):
    """Raised when a transaction fails validation."""


class TransactionNotFoundError(MCPBeancountError):
    """Raised when the requested transaction cannot be located."""


class NaturalLanguageError(MCPBeancountError):
    """Raised when we cannot map an NL question to a safe query."""
