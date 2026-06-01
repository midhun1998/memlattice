"""Lint must not flag captions or content inside fenced code blocks.

Regression tests from dogfooding (2026-06-01): a caption line ending in
':' that introduces a code block was wrongly flagged as an un-cited
factual claim, because the code block below is the actual evidence.
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


def _lint(root: Path) -> str:
    cwd = os.getcwd()
    try:
        os.chdir(root)
        return CliRunner().invoke(main, ["lint"]).output
    finally:
        os.chdir(cwd)


def test_caption_introducing_code_block_not_flagged(tmp_path: Path):
    """A line ending in ':' that leads into a fenced block is a caption."""
    _note(
        tmp_path,
        "The Scheduler runs on the executor (no extra cost):\n"
        "```\nsearch foo bar\n```",
    )
    assert "un-cited" not in _lint(tmp_path)


def test_factual_line_inside_code_block_not_flagged(tmp_path: Path):
    """Prose-looking lines inside a ``` fence are code, never claims."""
    _note(
        tmp_path,
        "```\n"
        "The Worker calls the PaymentGateway and writes to Redis\n"
        "```",
    )
    assert "un-cited" not in _lint(tmp_path)


def test_real_uncited_claim_still_flagged(tmp_path: Path):
    """Guard: the fix must NOT silence genuine un-cited factual claims."""
    _note(tmp_path, "The Worker calls the PaymentGateway directly.")
    assert "un-cited" in _lint(tmp_path)
