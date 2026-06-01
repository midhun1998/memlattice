"""`link --fix` must be idempotent and never destroy backlinks.

Regression from dogfooding (2026-06-01): running `link --fix` repeatedly
reported "N files updated" every time and oscillated/deleted backlinks,
because wikilinks inside the auto-maintained `## Referenced by` section
were being counted as outgoing links — polluting backref computation.
"""
from __future__ import annotations

import os
from pathlib import Path

from click.testing import CliRunner

from lattice.cli import main


def _run(root: Path, *args: str) -> str:
    cwd = os.getcwd()
    try:
        os.chdir(root)
        return CliRunner().invoke(main, list(args)).output
    finally:
        os.chdir(cwd)


def _vault_with_link(root: Path) -> None:
    CliRunner().invoke(main, ["init", str(root)])
    cwd = os.getcwd()
    try:
        os.chdir(root)
        CliRunner().invoke(main, ["new", "flow", "a"])
        CliRunner().invoke(main, ["new", "flow", "b"])
    finally:
        os.chdir(cwd)
    # a links to b in its BODY (above the Referenced-by section, as in
    # real notes) — inserted into the scaffold's Scope section.
    p = root / "flows" / "a.md"
    p.write_text(
        p.read_text().replace(
            "What this covers. What it does NOT (and which file does).",
            "What this covers. See [[b]] for the downstream flow.",
        )
    )


def test_link_fix_is_idempotent(tmp_path: Path):
    _vault_with_link(tmp_path)
    first = _run(tmp_path, "link", "--fix")
    assert "2 file(s) updated" in first or "1 file(s) updated" in first
    # second run: nothing changed, so zero updates
    second = _run(tmp_path, "link", "--fix")
    assert "0 file(s) updated" in second, second


def test_link_does_not_destroy_backlinks(tmp_path: Path):
    _vault_with_link(tmp_path)
    _run(tmp_path, "link", "--fix")
    after_first = (tmp_path / "flows" / "b.md").read_text()
    assert "[[a]]" in after_first  # b is referenced by a
    # run several more times — the backlink must survive
    for _ in range(3):
        _run(tmp_path, "link", "--fix")
    after_repeat = (tmp_path / "flows" / "b.md").read_text()
    assert "[[a]]" in after_repeat, "backlink [[a]] was destroyed by re-runs"


def test_backlink_section_links_not_treated_as_outgoing(tmp_path: Path):
    """a links to b; a must NOT gain a backref to itself via b's Ref-by."""
    _vault_with_link(tmp_path)
    _run(tmp_path, "link", "--fix")
    a_body = (tmp_path / "flows" / "a.md").read_text()
    # a has no inbound links, so its Referenced-by stays empty
    ref_section = a_body.split("Referenced by", 1)[1]
    assert "[[b]]" not in ref_section, "a wrongly back-references b"
