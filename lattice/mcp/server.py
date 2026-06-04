"""lattice MCP server (stdio).

Exposes the in-process tools in `tools.py` over the Model Context Protocol so an
agent (Claude Code, Cursor, …) queries lattice NATIVELY instead of being told to
run a CLI. The `mcp` SDK is an OPTIONAL extra: importing this module never
requires it; only `main()` does, and it fails with a clear install hint.

Run:  lattice-mcp           (entry point; serves over stdio)
Install for an agent:  lattice install claude-code
"""
from __future__ import annotations

import sys

from . import tools


def main() -> None:
    """Start the stdio MCP server. Requires `pip install "memlattice[mcp]"`."""
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError:
        raise SystemExit(
            "the MCP server needs the optional extra — run:\n"
            '  pip install "memlattice[mcp]"'
        )

    mcp = FastMCP("lattice")

    @mcp.tool()
    def lattice_context(query: str, vault: str | None = None, budget: int = 4000) -> str:
        """Return the smallest relevant subgraph of the memory vault for a query
        (a token-bounded, cited manifest). Use this BEFORE answering questions
        about the project — it loads only what's relevant, already cited."""
        return tools.context(vault, query, budget)

    @mcp.tool()
    def lattice_search(query: str, vault: str | None = None) -> str:
        """Find the most relevant notes for a query (cheap; tighter budget)."""
        return tools.search(vault, query)

    @mcp.tool()
    def lattice_lint(vault: str | None = None) -> str:
        """Check the vault: uncited factual claims, missing sections, budgets."""
        return tools.lint(vault)

    @mcp.tool()
    def lattice_verify(vault: str | None = None, fetch: bool = False) -> str:
        """Verify that cited sources still exist/back their claims (JSON report).
        Run before trusting memory: a 'missing'/'contradicted' citation means the
        claim is no longer sourced."""
        return tools.verify(vault, fetch)

    mcp.run()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
