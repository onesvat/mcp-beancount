import argparse
import sys
from typing import Any, Callable, Sequence, Annotated

from .config import AppConfig, load_config
from .exceptions import MCPBeancountError, NaturalLanguageError
from .ledger import LedgerManager
from .schemas import (
    BalanceRequest,
    BalanceResult,
    BeanQueryResult,
    IncomeSheetRequest,
    IncomeSheetResult,
    InsertTransactionRequest,
    InsertTransactionResult,
    ListAccountsResult,
    ListTransactionsRequest,
    ListTransactionsResult,
    NaturalLanguageRequest,
    NaturalLanguageResult,
    PostingInput,
    RemoveTransactionRequest,
    RemoveTransactionResult,
)
from pydantic import Field
from pathlib import Path
from mcp.server.fastmcp.resources import FileResource

INSTRUCTIONS = (
    "This MCP server exposes safe Beancount ledger tooling. "
    "All mutations are validated, balanced, and written atomically with backups."
)


def create_server(config: AppConfig):
    ledger = LedgerManager(config)

    # Optional Google OAuth authentication (if configured). We keep provider and server class consistent.
    _auth_active = False
    auth_provider = None
    FastMCP_cls = None
    if getattr(config, "google_auth_enabled", False):
        try:
            from fastmcp import FastMCP as _FastMCP  # type: ignore
            from fastmcp.server.auth.providers.google import GoogleProvider as _GP  # type: ignore
            FastMCP_cls = _FastMCP
            if config.google_client_id and config.google_client_secret:
                auth_provider = _GP(
                    client_id=config.google_client_id,
                    client_secret=config.google_client_secret,
                    base_url=(config.google_base_url or f"http://{config.http_host}:{config.http_port}"),
                    required_scopes=(config.google_required_scopes or [
                        "openid",
                        "https://www.googleapis.com/auth/userinfo.email",
                    ]),
                    **({"redirect_path": config.google_redirect_path} if config.google_redirect_path else {}),
                )
                _auth_active = True
            else:
                print(
                    "Warning: Google auth enabled but client_id/secret are missing; continuing without auth.",
                    file=sys.stderr,
                )
        except Exception as _exc:
            print(
                f"Warning: Google auth enabled but fastmcp auth stack not available ({_exc!s}); continuing without auth.",
                file=sys.stderr,
            )

    if FastMCP_cls is None:
        from mcp.server import FastMCP as FastMCP_cls  # type: ignore

    if _auth_active and auth_provider is not None:
        server = FastMCP_cls(
            name="mcp-beancount",
            instructions=INSTRUCTIONS,
            host=config.http_host,
            port=config.http_port,
            streamable_http_path=config.http_path,
            auth=auth_provider,  # type: ignore[arg-type]
        )
    else:
        server = FastMCP_cls(
            name="mcp-beancount",
            instructions=INSTRUCTIONS,
            host=config.http_host,
            port=config.http_port,
            streamable_http_path=config.http_path,
        )

    _get_access_token = None
    allowed_email_set: set[str] = set()
    if _auth_active:
        try:
            from fastmcp.server.dependencies import get_access_token as _gat  # type: ignore
            _get_access_token = _gat
        except Exception:
            try:
                from mcp.server.fastmcp.dependencies import get_access_token as _gat  # type: ignore
                _get_access_token = _gat
            except Exception:
                _get_access_token = None

        if config.google_allowed_emails:
            allowed_email_set = {email.lower() for email in config.google_allowed_emails if email}

    def _run_tool(callable_: Callable[[], Any]) -> Any:
        try:
            return callable_()
        except NaturalLanguageError as exc:
            raise ValueError(str(exc)) from exc
        except MCPBeancountError as exc:
            raise ValueError(str(exc)) from exc

    def _run_tool_authorized(callable_: Callable[[], Any]) -> Any:
        if allowed_email_set:
            if _get_access_token is None:
                raise ValueError("Authentication token unavailable; access denied.")
            try:
                token = _get_access_token()
            except Exception as exc:  # pragma: no cover - depends on auth backend
                raise ValueError("Authentication required.") from exc
            claims = getattr(token, "claims", {}) or {}
            email = str(claims.get("email", "")).lower()
            if email not in allowed_email_set:
                raise ValueError("Authenticated email is not allowed to access this server.")
        return _run_tool(callable_)

    # Register a read-only Markdown cheat sheet as a resource
    cheatsheet_path = (Path(__file__).resolve().parent.parent / "docs" / "beanquery-cheatsheet.md").resolve()
    if cheatsheet_path.exists():
        server._resource_manager.add_resource(
            FileResource(
                uri="mcp://mcp-beancount/beanquery-cheatsheet",
                name="beanquery-cheatsheet",
                title="BeanQuery Cheat Sheet",
                description="Common BeanQuery patterns and examples.",
                path=cheatsheet_path,
                mime_type="text/markdown",
            )
        )

    @server.tool(name="list_accounts", description="List accounts with metadata from the configured ledger.")
    def list_accounts(include_closed: bool = False) -> ListAccountsResult:
        return _run_tool_authorized(lambda: ledger.list_accounts(include_closed=include_closed))

    @server.tool(name="balance", description="Compute balances for accounts over a date range. Dates are ISO (YYYY-MM-DD). If you set only end_date, it's treated as 'as-of' date. Use convert_to to value in a target currency when price data exists.")
    def balance(
        accounts: Annotated[list[str] | None, Field(description="Account prefixes to include; children included if include_children is true.")] = None,
        include_children: Annotated[bool, Field(description="Include child accounts of any provided prefixes.")] = True,
        start_date: Annotated[str | None, Field(description="Start date (YYYY-MM-DD) inclusive.")] = None,
        end_date: Annotated[str | None, Field(description="End date (YYYY-MM-DD) inclusive.")] = None,
        at_date: Annotated[str | None, Field(description="As-of date (YYYY-MM-DD). Ignored if start/end provided.")] = None,
        convert_to: Annotated[str | None, Field(description="Target currency to value balances (uses price data if available). ")] = None,
        rollup: Annotated[bool, Field(description="Reserved for future rollup behavior.")] = False,
    ) -> BalanceResult:
        req = BalanceRequest(
            accounts=accounts,
            include_children=include_children,
            start_date=_opt_date(start_date),
            end_date=_opt_date(end_date),
            at_date=_opt_date(at_date),
            convert_to=convert_to,
            rollup=rollup,
        )
        return _run_tool_authorized(lambda: ledger.balance(req))

    @server.tool(name="income_sheet", description="Generate an income statement for the requested period (Income, Expenses, Net). Dates are ISO (YYYY-MM-DD).")
    def income_sheet(
        start_date: Annotated[str, Field(description="Start date (YYYY-MM-DD) inclusive.")],
        end_date: Annotated[str, Field(description="End date (YYYY-MM-DD) inclusive.")],
        convert_to: Annotated[str | None, Field(description="Target currency to value results (uses price data if available). ")] = None,
    ) -> IncomeSheetResult:
        req = IncomeSheetRequest(start_date=_req_date(start_date), end_date=_req_date(end_date), convert_to=convert_to)
        return _run_tool_authorized(lambda: ledger.income_sheet(req))

    @server.tool(name="list_transactions", description="List transactions with filters (date/account/payee/narration/tags/metadata) and pagination.")
    def list_transactions(
        start_date: Annotated[str | None, Field(description="Start date (YYYY-MM-DD) inclusive.")] = None,
        end_date: Annotated[str | None, Field(description="End date (YYYY-MM-DD) inclusive.")] = None,
        accounts: Annotated[list[str] | None, Field(description="Account prefixes to include (children always included). ")] = None,
        payee: Annotated[str | None, Field(description="Substring match against payee.")] = None,
        narration: Annotated[str | None, Field(description="Substring match against narration.")] = None,
        tags: Annotated[list[str] | None, Field(description="Require that all of these tags are present.")] = None,
        metadata: Annotated[dict[str, Any] | None, Field(description="Exact-match metadata key/value constraints.")] = None,
        limit: Annotated[int | None, Field(ge=0, description="Max number of results to return (null for all). ")] = 50,
        offset: Annotated[int, Field(ge=0, description="Result offset for pagination.")] = 0,
        include_postings: Annotated[bool, Field(description="Include postings in response.")] = True,
    ) -> ListTransactionsResult:
        req = ListTransactionsRequest(
            start_date=_opt_date(start_date),
            end_date=_opt_date(end_date),
            accounts=accounts,
            payee=payee,
            narration=narration,
            tags=tags,
            metadata=metadata,
            limit=limit,
            offset=offset,
            include_postings=include_postings,
        )
        return _run_tool_authorized(lambda: ledger.list_transactions(req))

    @server.tool(name="insert_transaction", description="Insert a balanced transaction; supports dry-run preview. Provide postings with amounts that sum to zero across currencies.")
    def insert_transaction(
        date: Annotated[str, Field(description="Transaction date (YYYY-MM-DD).")],
        flag: Annotated[str | None, Field(description="Transaction flag (e.g., *). ")] = None,
        payee: Annotated[str | None, Field(description="Payee.")] = None,
        narration: Annotated[str | None, Field(description="Narration/description.")] = None,
        postings: Annotated[list[PostingInput], Field(description="Postings with accounts and signed amounts.")] = [],
        tags: Annotated[list[str] | None, Field(description="Tags to attach.")] = None,
        meta: Annotated[dict[str, Any] | None, Field(description="Additional metadata.")] = None,
        txn_id: Annotated[str | None, Field(description="Optional stable unique id; auto-generated if omitted.")] = None,
        dry_run: Annotated[bool | None, Field(description="If true, do not write—return a diff preview only.")] = None,
    ) -> InsertTransactionResult:
        req = InsertTransactionRequest(
            date=_req_date(date),
            flag=flag,
            payee=payee,
            narration=narration,
            postings=postings,
            tags=tags,
            meta=meta,
            txn_id=txn_id,
            dry_run=dry_run,
        )
        return _run_tool_authorized(lambda: ledger.insert_transaction(req))

    @server.tool(name="remove_transaction", description="Remove a transaction by txn_id; supports dry-run preview.")
    def remove_transaction(
        txn_id: Annotated[str, Field(description="The txn_id metadata of the transaction to remove.")],
        dry_run: Annotated[bool | None, Field(description="If true, do not write—return a diff preview only.")] = None,
    ) -> RemoveTransactionResult:
        req = RemoveTransactionRequest(txn_id=txn_id, dry_run=dry_run)
        return _run_tool_authorized(lambda: ledger.remove_transaction(req))

    @server.tool(name="query", description="Execute a BeanQuery (BeanQuery/beanquery) read-only query. Example: SELECT account, sum(position) WHERE account ~ '^Assets' GROUP BY account ORDER BY account. Note: compare dates using date('YYYY-MM-DD').")
    def bean_query(
        query: Annotated[str, Field(description="BeanQuery SQL-like query. Use date('YYYY-MM-DD') for date comparisons.")]
    ) -> BeanQueryResult:
        return _run_tool_authorized(lambda: ledger.run_query(query))

    @server.tool(
        name="example_queries",
        description=(
            "Return curated example queries with names and descriptions. "
            "Use with the 'query' tool to run them."
        ),
    )
    def example_queries() -> list[dict[str, str]]:
        return _run_tool_authorized(
            lambda: [
                {
                    "name": "Assets by Account",
                    "description": "Sum asset balances per account.",
                    "query": "SELECT account, sum(position) WHERE account ~ '^Assets' GROUP BY account ORDER BY account",
                },
                {
                    "name": "Expenses Total (Jan 2020)",
                    "description": "Total expenses for January 2020.",
                    "query": "SELECT sum(position) WHERE account ~ '^Expenses' AND date >= date('2020-01-01') AND date <= date('2020-01-31')",
                },
                {
                    "name": "Expenses by Category",
                    "description": "Categorized expenses, largest first.",
                    "query": "SELECT account, sum(position) WHERE account ~ '^Expenses' GROUP BY account ORDER BY sum(position) DESC",
                },
                {
                    "name": "Income by Payee",
                    "description": "Income totals by payee.",
                    "query": "SELECT payee, sum(position) WHERE account ~ '^Income' GROUP BY payee ORDER BY sum(position)",
                },
            ]
        )

    @server.tool(
        name="natural_language_query",
        description=(
            "Answer common natural-language questions via safe templates. Examples: "
            "'Balance of Assets:Bank as of 2020-01-31', 'Spending by category in 2020-01', 'Total spending in 2020'."
        ),
    )
    def natural_language(
        question: Annotated[str, Field(description="Natural-language question to map to a safe query.")]
    ) -> NaturalLanguageResult:
        req = NaturalLanguageRequest(question=question)
        return _run_tool_authorized(lambda: ledger.natural_language_query(req))

    # Optionally expose a protected tool to introspect authenticated Google user info
    if _auth_active and _get_access_token is not None:

        @server.tool(
            name="get_user_info",
            description="Return information about the authenticated Google user (requires OAuth).",
        )
        def get_user_info() -> dict[str, Any]:

            def _build() -> dict[str, Any]:
                token = _get_access_token()
                claims = getattr(token, "claims", {}) or {}
                return {
                    "google_id": claims.get("sub"),
                    "email": claims.get("email"),
                    "name": claims.get("name"),
                    "picture": claims.get("picture"),
                    "locale": claims.get("locale"),
                }

            return _run_tool_authorized(_build)

    return server


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the MCP Beancount HTTP server.")
    parser.add_argument("--config", help="Path to configuration file.")
    parser.add_argument(
        "--transport",
        choices=["streamable-http", "stdio", "sse"],
        default="streamable-http",
        help="Transport to use for FastMCP (default: streamable-http).",
    )
    args = parser.parse_args(argv)

    try:
        config = load_config(args.config)
    except MCPBeancountError as exc:
        print(f"Failed to load configuration: {exc}", file=sys.stderr)
        return 2

    server = create_server(config)
    try:
        # Configure global settings before running
        from fastmcp import settings
        settings.host = config.http_host
        settings.port = config.http_port
        settings.streamable_http_path = config.http_path
        server.run(transport=args.transport)
    except Exception as exc:  # pragma: no cover - FastMCP handles signals internally
        print(f"Server error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


# ------------------------------ helpers ------------------------------

def _opt_date(value: str | None):
    if value is None:
        return None
    from datetime import date

    return date.fromisoformat(value)


def _req_date(value: str):
    from datetime import date

    return date.fromisoformat(value)
