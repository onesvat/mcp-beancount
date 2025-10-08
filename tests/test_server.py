from __future__ import annotations

import asyncio

from mcp_beancount.server import create_server


def test_server_lists_expected_tools(ledger_config) -> None:
    server = create_server(ledger_config)
    tools = asyncio.run(server.list_tools())
    names = {tool.name for tool in tools}
    expected = {
        "list_accounts",
        "balance",
        "income_sheet",
        "list_transactions",
        "insert_transaction",
        "remove_transaction",
        "query",
        "natural_language_query",
    }
    assert expected.issubset(names)
