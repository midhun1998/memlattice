"""Inline lint directives — conscious exceptions and hard-fail markers.

Two directives, modeled on pylint's `# noqa`:

- `<!-- lattice-ignore -->` on (or trailing) a line exempts THAT line from the
  citation check — a consciously-acknowledged exception.
- `<!-- lattice: needs-citation -->` anywhere in a note HARD-FAILS lint for that
  note, regardless of the trigger-word heuristic. `promote` inserts this so an
  unverified promoted note can never pass the gate.
"""
from __future__ import annotations

import os
from pathlib import Path

from click.testing import CliRunner

from lattice.cli import main


def _note(root: Path, body: str) -> None:
    CliRunner().invoke(main, ["init", str(root)])
    (root / "flows" / "n.md").write_text(
        "---\ntype: flow\nlast_verified: 2026-06-01\nrelated: []\n---\n\n"
        f"# N\n\n{body}\n\n## Open questions\n- none\n\n## Referenced by\n_none_\n"
    )


def _lint(root: Path):
    cwd = os.getcwd()
    try:
        os.chdir(root)
        return CliRunner().invoke(main, ["lint"])
    finally:
        os.chdir(cwd)


# ---------- lattice-ignore: the conscious-exception escape hatch ----------

def test_ignore_directive_trailing_exempts_line(tmp_path: Path):
    """A trailing `<!-- lattice-ignore -->` exempts that one factual line."""
    _note(tmp_path, "The Worker calls the PaymentGateway. <!-- lattice-ignore -->")
    res = _lint(tmp_path)
    assert "un-cited" not in res.output, res.output
    assert res.exit_code == 0, res.output


def test_ignore_directive_is_line_scoped(tmp_path: Path):
    """lattice-ignore exempts only its own line — a later uncited claim still fails."""
    _note(
        tmp_path,
        "The Worker calls the PaymentGateway. <!-- lattice-ignore -->\n\n"
        "The Ledger reads from the Cache directly.",
    )
    res = _lint(tmp_path)
    assert "un-cited" in res.output, res.output


# ---------- needs-citation: the hard-fail marker promote relies on ----------

def test_needs_citation_directive_hard_fails(tmp_path: Path):
    """A note carrying the needs-citation marker fails lint even with NO
    trigger-word claim present (the heuristic would otherwise pass it)."""
    _note(
        tmp_path,
        "<!-- lattice: needs-citation -->\n\n"
        "Some prose with no trigger words at all about settlement timing.",
    )
    res = _lint(tmp_path)
    assert res.exit_code != 0, res.output
    assert "needs-citation" in res.output or "needs citation" in res.output.lower()


def test_clean_note_without_directives_passes(tmp_path: Path):
    """Guard: a normal cited note still passes."""
    _note(tmp_path, "The Worker calls the PaymentGateway [doc:runbook].")
    res = _lint(tmp_path)
    assert res.exit_code == 0, res.output
    assert "un-cited" not in res.output
