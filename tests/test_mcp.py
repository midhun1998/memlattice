"""MCP surface: tool functions wrap the core in-process; package works without
the `mcp` SDK installed (guarded); `install claude-code` writes a .mcp.json stub.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from click.testing import CliRunner

from lattice.cli import main
from lattice.mcp import tools


def _vault(tmp_path: Path) -> None:
    CliRunner().invoke(main, ["init", str(tmp_path)])


# ---------- vault resolution: explicit arg > LATTICE_VAULT env > cwd ----------

def test_tool_uses_lattice_vault_env_when_no_arg(tmp_path: Path, monkeypatch):
    """A globally-wired MCP server has an unpredictable cwd; LATTICE_VAULT pins
    the vault so tools resolve it regardless of where the server launched."""
    _vault(tmp_path)
    (tmp_path / "flows" / "x.md").write_text(
        "---\ntype: flow\nlast_verified: 2026-06-03\nrelated: []\n---\n\n"
        "# X\n\n## Open questions\n- none\n\n## Referenced by\n_none_\n"
    )
    monkeypatch.setenv("LATTICE_VAULT", str(tmp_path))
    monkeypatch.chdir(Path(__file__).parent)  # cwd is NOT the vault
    out = tools.lint(None)  # no explicit vault arg
    assert "x.md" in out  # resolved via env, not cwd


def test_explicit_vault_arg_overrides_env(tmp_path: Path, monkeypatch):
    _vault(tmp_path)
    monkeypatch.setenv("LATTICE_VAULT", "/nonexistent/elsewhere")
    out = tools.lint(str(tmp_path))  # explicit arg wins over the bad env
    assert isinstance(out, str)


# ---------- tool functions call the core in-process (no subprocess, no SDK) ----------

def test_tool_context_returns_manifest(tmp_path: Path):
    _vault(tmp_path)
    (tmp_path / "flows" / "checkout.md").write_text(
        "---\ntype: flow\nlast_verified: 2026-06-03\nrelated: []\n---\n\n"
        "# Checkout\n\n## settlement\nThe gateway settles payments here.\n\n"
        "## Open questions\n- none\n\n## Referenced by\n_none_\n"
    )
    out = tools.context(str(tmp_path), "how does checkout settle", budget=2000)
    assert "checkout" in out.lower()


def test_tool_lint_returns_text(tmp_path: Path):
    _vault(tmp_path)
    out = tools.lint(str(tmp_path))
    assert isinstance(out, str)


def test_tool_verify_returns_json(tmp_path: Path):
    _vault(tmp_path)
    (tmp_path / "flows" / "f.md").write_text(
        "---\ntype: flow\nlast_verified: 2026-06-03\nrelated: []\n---\n\n"
        "# F\n\nClaim with a bad cite [file:nope.txt].\n\n"
        "## Open questions\n- none\n\n## Referenced by\n_none_\n"
    )
    data = json.loads(tools.verify(str(tmp_path)))
    assert "summary" in data and "notes" in data


def test_tool_list_is_stable():
    """The advertised tool set is explicit (so the server + docs agree)."""
    assert tools.TOOL_NAMES == ["lattice_context", "lattice_search", "lattice_lint", "lattice_verify"]


# ---------- package imports without the mcp SDK ----------

def test_mcp_package_imports_without_sdk():
    """Importing lattice.mcp.tools must NOT require the `mcp` SDK (core stays
    dependency-light; the SDK is only needed to RUN the server)."""
    import importlib
    import lattice.mcp.tools as t
    importlib.reload(t)  # should not raise even though `mcp` is absent


def test_server_import_guarded():
    """lattice.mcp.server.main() errors clearly if the SDK is missing, rather
    than ImportError-ing at module import time."""
    from lattice.mcp import server
    # the module imports fine; running without the SDK raises a clear SystemExit
    import importlib.util
    if importlib.util.find_spec("mcp") is None:
        try:
            server.main()
            assert False, "expected a clear error without the mcp SDK"
        except SystemExit as e:
            assert "mcp" in str(e).lower() or "install" in str(e).lower()


# ---------- install claude-code ----------

def test_install_claude_code_writes_mcp_json(tmp_path: Path):
    _vault(tmp_path)
    cwd = os.getcwd()
    try:
        os.chdir(tmp_path)
        res = CliRunner().invoke(main, ["install", "claude-code", "--yes"])
        assert res.exit_code == 0, res.output
        mcp_json = tmp_path / ".mcp.json"
        assert mcp_json.exists()
        cfg = json.loads(mcp_json.read_text())
        # advertises a lattice MCP server invoking lattice-mcp
        servers = cfg.get("mcpServers", {})
        assert "lattice" in servers
        assert "lattice-mcp" in (servers["lattice"].get("command", "") + " ".join(servers["lattice"].get("args", [])))
    finally:
        os.chdir(cwd)


def test_install_claude_code_idempotent(tmp_path: Path):
    _vault(tmp_path)
    cwd = os.getcwd()
    try:
        os.chdir(tmp_path)
        CliRunner().invoke(main, ["install", "claude-code", "--yes"])
        first = (tmp_path / ".mcp.json").read_text()
        CliRunner().invoke(main, ["install", "claude-code", "--yes"])
        assert (tmp_path / ".mcp.json").read_text() == first
    finally:
        os.chdir(cwd)
