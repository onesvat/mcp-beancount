MCP Beancount Tool — Project Documentation

**Description**
- Build an MCP server that integrates with Beancount 3.2.0 to expose safe, structured tools for: viewing accounts, balances, income sheet (income statement), and transactions; inserting new transactions; removing transactions; and answering natural‑language questions via BeanQuery.
- Provide deterministic, validated, and auditable interactions with a local Beancount ledger, suitable for MCP‑compatible clients (e.g., IDE agents or chat assistants) operating offline.
- Emphasize correctness (balanced postings, type‑checked inputs), safety (file locking, atomic writes, backups), and usability (clear schemas and messages). Each created transaction receives a stable unique identifier to support safe updates/deletions.

**Requirements**
- Functional
  - List accounts: return name, type, open/close metadata, currencies, and optional tags/commodities.
  - Balances: compute account and roll‑up balances at a date or over a period; optionally convert using available price data.
  - Income sheet: produce an income statement (Income/Expenses and net result) for a specified period.
  - List transactions: filter by date range, account(s), payee, narration, tags, and metadata; include postings and totals.
  - Insert transaction: accept structured input (date, flag, payee, narration, postings, metadata), enforce balance; assign `txn_id` (UUID) if missing; validate with Beancount before persisting.
  - Remove transaction: delete by `txn_id` (required for deletion); refuse ambiguous deletes; validate resulting ledger.
  - Query (BeanQuery): execute read‑only BeanQuery strings and return typed rows/columns.
  - Natural‑language Q&A: map NL questions to safe BeanQuery templates (read‑only); return results and the generated query for transparency.
  - Dry‑run mode for mutations to preview effects without writing.
- Non‑functional
  - Local‑first and offline; no network dependencies during normal operation.
  - Performance targets appropriate for 100k+ postings; avoid re‑parsing on trivial reads when possible.
  - Deterministic output formats and stable ordering for repeatability.
  - Clear, actionable errors (parse issues, validation failures, unbalanced postings, ambiguous matches).
  - Strong auditability: atomic writes, automatic timestamped backups, and file locking to prevent concurrent corruption.
- Technical
  - Beancount 3.2.0 for parsing, validation, and query (`beancount.loader`, `beancount.core.*`, `beancount.query`).
  - Language/runtime: Python 3.11+.
  - MCP server SDK (Python) using the latest `modelcontextprotocol/python-sdk`; expose tools with JSON‑schema input/output; define stable tool names and schemas.
  - Transport: HTTP transport from the MCP Python SDK (server runs over HTTP).
  - Testing: `pytest`; sample fixture ledgers; golden files for tool responses where applicable.
  - Cross‑platform file locking and atomic replace on write; UTF‑8 encoding.
  - Configuration via file and environment: main ledger path, default currency, price/commodities options, locale/timezone.
- Security & Privacy
  - Operate only on configured ledger roots; reject path traversal/out‑of‑scope files.
  - Sanitize and bound NL→BeanQuery generation to read‑only, parameterized templates; never perform writes from NL intents.
  - Never transmit ledger data over network; logs must redact sensitive fields when necessary.

**Tasks**
- Project scaffolding
  - Initialize Python project with `uv`, dependency pins (Beancount 3.2.0), and basic packaging.
  - Add configuration loader (env + config file) for ledger path and options.
  - Set up `pytest` with sample fixture ledgers for repeatable tests.
  - Provide a minimal example ledger at `tests/fixtures/example.beancount` for testing.
- MCP server foundation
  - Integrate the latest `modelcontextprotocol/python-sdk`.
  - Use HTTP transport for the server; document default port and configuration.
  - Scaffold server entrypoint and lifecycle (no business logic yet).
  - Define tool manifests with JSON schemas for inputs/outputs and consistent error models.
- Ledger loading & validation
  - Implement loader using `beancount.loader` with include handling, cache, and diagnostics capture.
  - Provide a validation layer to surface Beancount errors/warnings in a structured form.
- Read‑only tools
  - `list_accounts`: enumerate accounts with metadata and inferred types.
  - `balance`: compute balances at date/period; include options for cost/value and conversions when price data exists.
  - `income_sheet`: generate period income statement (Income, Expenses, Net) with grouping and totals.
  - `list_transactions`: filters (date/account/payee/tag/metadata) and pagination; include postings.
  - `query`: execute BeanQuery safely; return columns + typed rows.
- Mutation tools
  - `insert_transaction`: define input schema; normalize/validate postings; auto‑assign `txn_id`; pretty‑format; atomic write with backup; re‑load to verify.
  - `remove_transaction`: require `txn_id`; locate uniquely; remove; atomic write; re‑load to verify.
  - Introduce optional `dry_run` flag for both mutations; return proposed diff.
- Natural‑language layer
  - Implement a rule/template‑based NL→BeanQuery mapper for common intents (balances, spending by category, income by month, etc.).
  - Validate generated queries as read‑only; expose the final query in responses for transparency.
- Reliability & UX
  - Add file locking, atomic replace, and timestamped backups; configurable backup retention.
  - Normalize amounts/commodities and present deterministic output ordering.
  - Structured, user‑facing error messages with remediation hints.
- Testing & examples
  - Unit tests for each tool, including edge cases (unbalanced inserts, ambiguous deletes, parse errors).
  - End‑to‑end tests against fixture ledgers and golden responses.
  - Example configuration and sample queries in docs.
- Packaging & release
  - Package as a Python distribution; pin dependencies; provide entrypoint for MCP server.
  - Versioning and changelog; minimal quickstart documentation for MCP clients.

**MCP SDK & Transport**
- SDK: Use the latest `modelcontextprotocol/python-sdk` (installed as `modelcontextprotocol`).
- Transport: HTTP transport. The server will expose an HTTP endpoint for MCP clients; default host/port and CORS/security considerations will be documented alongside configuration. No stdio transport is planned for the default setup.

**Development (uv)**
- Create and sync the environment:
  - `uv sync`  (installs project and dev dependencies)
- Run tests:
  - `uv run -m pytest`
- Lint (if desired):
  - `uv run ruff check .`

**Example configuration**
- `tests/fixtures/mcp-beancount.toml` demonstrates a minimal config pointing at the bundled example ledger. Copy and adjust paths before running `uv run mcp-beancount --config <file>`.
