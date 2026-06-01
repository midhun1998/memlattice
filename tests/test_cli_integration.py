"""End-to-end: lint honors configured citations; new accepts custom types."""
from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from lattice.cli import main


def _init(root: Path) -> None:
    CliRunner().invoke(main, ["init", str(root)])


def test_new_creates_custom_type_note(tmp_path: Path):
    _init(tmp_path)
    cfg = tmp_path / ".lattice" / "config.toml"
    cfg.write_text('[types]\nrunbook = "runbooks"\n')
    import os
    cwd = os.getcwd()
    try:
        os.chdir(tmp_path)
        res = CliRunner().invoke(main, ["new", "runbook", "deploy-rollback"])
        assert res.exit_code == 0, res.output
        assert (tmp_path / "runbooks" / "deploy-rollback.md").exists()
    finally:
        os.chdir(cwd)


def test_new_rejects_unconfigured_type(tmp_path: Path):
    _init(tmp_path)
    import os
    cwd = os.getcwd()
    try:
        os.chdir(tmp_path)
        res = CliRunner().invoke(main, ["new", "bogustype", "x"])
        assert res.exit_code != 0
        assert "bogustype" in res.output or "unknown" in res.output.lower()
    finally:
        os.chdir(cwd)


def test_lint_accepts_configured_citation_scheme(tmp_path: Path):
    """A note citing a user-configured scheme (jira) must pass the citation gate."""
    _init(tmp_path)
    (tmp_path / ".lattice" / "config.toml").write_text(
        (tmp_path / ".lattice" / "config.toml").read_text()
        + '\n[citations]\nextra = ["jira"]\n'
    )
    note = tmp_path / "flows" / "billing.md"
    note.write_text(
        "---\ntype: flow\nlast_verified: 2026-06-01\nrelated: []\n---\n\n"
        "# Billing\n\n"
        "The Worker reads from the ledger [jira:PROJ-12].\n\n"
        "## Open questions\n- none\n\n"
        "## Referenced by\n_none_\n"
    )
    import os
    cwd = os.getcwd()
    try:
        os.chdir(tmp_path)
        res = CliRunner().invoke(main, ["lint"])
        assert "un-cited" not in res.output, res.output
    finally:
        os.chdir(cwd)


def test_lint_flags_uncited_when_scheme_not_configured(tmp_path: Path):
    """Same note, but jira not configured -> the [jira:..] token is not a
    recognized citation, so the factual line is flagged."""
    _init(tmp_path)
    note = tmp_path / "flows" / "billing.md"
    note.write_text(
        "---\ntype: flow\nlast_verified: 2026-06-01\nrelated: []\n---\n\n"
        "# Billing\n\n"
        "The Worker reads from the Ledger [jira:PROJ-12].\n\n"
        "## Open questions\n- none\n\n"
        "## Referenced by\n_none_\n"
    )
    import os
    cwd = os.getcwd()
    try:
        os.chdir(tmp_path)
        res = CliRunner().invoke(main, ["lint"])
        assert "un-cited" in res.output, res.output
    finally:
        os.chdir(cwd)
