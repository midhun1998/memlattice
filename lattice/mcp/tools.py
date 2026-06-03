"""In-process MCP tool implementations.

These wrap lattice's existing core functions DIRECTLY (no subprocess) so the
agent gets typed, fast access to the same engine the CLI uses. This module must
NOT import the `mcp` SDK — it stays dependency-light so the core package imports
cleanly without the [mcp] extra. The server (server.py) registers these with the
SDK; tests call them directly.
"""
from __future__ import annotations

import json
from pathlib import Path

from ..config import citation_regex
from ..vault import find_vault, load_vault

# The advertised tool set — kept explicit so server + docs never drift.
TOOL_NAMES = ["lattice_context", "lattice_search", "lattice_lint", "lattice_verify"]


def _root(vault: str | None) -> Path:
    start = Path(vault) if vault else Path.cwd()
    root = find_vault(start)
    if root is None:
        raise ValueError(f"no lattice vault found from {start}")
    return root


def context(vault: str | None, query: str, budget: int = 4000) -> str:
    """Smallest relevant subgraph for a query (the token-bounded manifest)."""
    from ..cli import _build_context
    text, _used, _files, _reason = _build_context(_root(vault), query, budget)
    return text


def search(vault: str | None, query: str, budget: int = 2000) -> str:
    """Alias of context with a tighter default budget (kept distinct so agents
    can pick a cheap 'find' vs a fuller 'load')."""
    return context(vault, query, budget)


def lint(vault: str | None) -> str:
    """Run the citation/structure/budget lint; return a plain-text report."""
    root = _root(vault)
    from ..cli import _lint_note
    from ..config import budgets
    cite_re = citation_regex(root)
    b = budgets(root)
    lines = []
    problems_total = 0
    for n in load_vault(root):
        probs = _lint_note(n, cite_re, b["file_warn"], b["file_max"])
        rel = n.path.relative_to(root)
        if probs:
            problems_total += 1
            lines.append(f"{rel}")
            lines.extend(f"  ✗ {p}" for p in probs)
        else:
            lines.append(f"{rel}  ✓ ok")
    lines.append(f"\n{problems_total} file(s) with problems" if problems_total else "\nall clean")
    return "\n".join(lines)


def verify(vault: str | None, fetch: bool = False) -> str:
    """Run verify Layer 1 over the vault; return the JSON audit artifact."""
    root = _root(vault)
    from .. import verify as _verify
    cite_re = citation_regex(root)
    report = []
    for n in load_vault(root):
        tokens = _verify.citations_in(n.body, cite_re)
        if not tokens:
            continue
        line_of = {}
        for i, line in enumerate(n.body.splitlines(), start=1):
            for mt in cite_re.finditer(line):
                line_of.setdefault(mt.group(0)[1:-1], i)
        cites = []
        for tok in tokens:
            st = _verify.resolve_citation(tok, root=root, fetch=fetch)
            cites.append({"token": tok, "status": st.status, "detail": st.detail,
                          "line": line_of.get(tok, 1)})
        report.append({"path": str(n.path.relative_to(root)),
                       "status": _verify.worst([c["status"] for c in cites]),
                       "citations": cites})
    failed = sum(1 for r in report if _verify.is_fail(r["status"]))
    return json.dumps({"summary": {"notes": len(report), "failed": failed}, "notes": report}, indent=2)
