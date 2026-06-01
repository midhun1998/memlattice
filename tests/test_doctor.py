"""`lattice doctor` — read-only vault health summary.

A plain-text dashboard over the load_vault scan: note count, total tokens,
stale count, orphan notes, token-budget breaches, lint pass/fail. Exits
non-zero only on HARD problems (lint errors or over-max files); staleness
and orphans are advisory unless --strict.
"""
from __future__ import annotations

import os
from pathlib import Path

from click.testing import CliRunner

from lattice.cli import main
from lattice.config import budgets


def _init(root: Path) -> None:
    CliRunner().invoke(main, ["init", str(root)])


def _valid_note(root: Path, rel: str, body: str = "", *, last_verified: str = "2026-06-01") -> Path:
    """Write a fully-valid note (passes lint): type, last_verified, the two
    required sections, and a clean body."""
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        f"---\ntype: flow\nlast_verified: {last_verified}\nrelated: []\n---\n\n"
        f"# {p.stem}\n\n{body}\n\n## Open questions\n- none\n\n## Referenced by\n_none_\n"
    )
    return p


def _doctor(root: Path, *args: str):
    cwd = os.getcwd()
    try:
        os.chdir(root)
        return CliRunner().invoke(main, ["doctor", *args])
    finally:
        os.chdir(cwd)


def test_doctor_command_exists_and_reports_counts(tmp_path: Path):
    _init(tmp_path)
    _valid_note(tmp_path, "flows/a.md")
    _valid_note(tmp_path, "flows/b.md")
    res = _doctor(tmp_path)
    assert res.exit_code == 0, res.output
    assert "notes:" in res.output
    assert "2" in res.output
    assert "lint:" in res.output


def test_doctor_exit_nonzero_on_lint_error(tmp_path: Path):
    """A genuine un-cited factual claim is a HARD problem -> exit 1."""
    _init(tmp_path)
    _valid_note(tmp_path, "flows/a.md", body="The Worker calls the PaymentGateway directly.")
    res = _doctor(tmp_path)
    assert res.exit_code == 1, res.output
    assert "lint" in res.output.lower()


def test_doctor_exit_nonzero_on_over_max_file(tmp_path: Path):
    """A file over file_max tokens is a HARD problem -> exit 1."""
    _init(tmp_path)
    # cheap over-max: set file_max=10 tokens
    (tmp_path / ".lattice" / "config.toml").write_text("[budgets]\nfile_max = 10\nfile_warn = 5\n")
    _valid_note(tmp_path, "flows/a.md", body="word " * 400)  # ~ many tokens
    res = _doctor(tmp_path)
    assert res.exit_code == 1, res.output
    assert "over max" in res.output.lower()


def test_doctor_counts_orphans(tmp_path: Path):
    """A links to B (body wikilink); C is isolated. Only C is an orphan."""
    _init(tmp_path)
    _valid_note(tmp_path, "flows/a.md", body="See [[b]] for downstream.")
    _valid_note(tmp_path, "flows/b.md")
    _valid_note(tmp_path, "flows/c.md")
    res = _doctor(tmp_path)
    assert res.exit_code == 0, res.output
    # exactly one orphan, and it is c
    assert "orphans:          1" in res.output or "orphans" in res.output
    assert "c.md" in res.output
    assert "a.md" not in res.output  # a is linked-out, not orphan
    assert "b.md" not in res.output  # b has an inbound link, not orphan


def test_doctor_stale_respects_days(tmp_path: Path):
    """Far-past note + missing-last_verified note both count as stale at default
    --days; a large --days excludes the dated one, leaving only the missing one."""
    _init(tmp_path)
    _valid_note(tmp_path, "flows/old.md", last_verified="2000-01-01")
    # missing last_verified
    (tmp_path / "flows" / "nofield.md").write_text(
        "---\ntype: flow\nrelated: []\n---\n\n# nofield\n\nbody\n\n"
        "## Open questions\n- none\n\n## Referenced by\n_none_\n"
    )
    res_default = _doctor(tmp_path)  # default 90d
    assert "stale (>90d):     2" in res_default.output, res_default.output
    # huge threshold: the 2000-dated note is younger than that, only missing one counts
    res_large = _doctor(tmp_path, "--days", "1000000")
    assert "stale (>1000000d): 1" in res_large.output, res_large.output


def test_doctor_total_tokens_reported(tmp_path: Path):
    _init(tmp_path)
    from lattice.vault import load_vault
    a = _valid_note(tmp_path, "flows/a.md", body="some clean prose here")
    b = _valid_note(tmp_path, "flows/b.md", body="other clean prose")
    expected = sum(n.token_estimate for n in load_vault(tmp_path))
    res = _doctor(tmp_path)
    assert f"~{expected}" in res.output, res.output


def test_doctor_clean_vault_passes(tmp_path: Path):
    _init(tmp_path)
    _valid_note(tmp_path, "flows/a.md")
    res = _doctor(tmp_path)
    assert res.exit_code == 0, res.output
    assert "all checks passed" in res.output.lower()


def test_doctor_not_in_vault_exits_2(tmp_path: Path):
    # tmp_path has no _protocol.md and no .lattice -> not a vault
    res = _doctor(tmp_path)
    assert res.exit_code == 2, res.output


def test_doctor_empty_vault_reports_zero(tmp_path: Path):
    _init(tmp_path)
    res = _doctor(tmp_path)
    assert res.exit_code == 0, res.output
    assert "notes:" in res.output
    assert "all checks passed" in res.output.lower()


def test_doctor_strict_escalates_orphans_and_warn(tmp_path: Path):
    """--strict treats orphans (and warn-level breaches) as hard problems."""
    _init(tmp_path)
    _valid_note(tmp_path, "flows/lonely.md")  # orphan, otherwise clean
    res = _doctor(tmp_path)
    assert res.exit_code == 0, res.output  # advisory by default
    res_strict = _doctor(tmp_path, "--strict")
    assert res_strict.exit_code == 1, res_strict.output


# ---------- config.budgets reader ----------

def test_budgets_defaults_when_no_vault():
    assert budgets(None) == {"file_warn": 6000, "file_max": 12000}


def test_budgets_override_is_additive(tmp_path: Path):
    """A [budgets] table overriding file_max wins; unspecified keys keep defaults."""
    (tmp_path / ".lattice").mkdir(parents=True)
    (tmp_path / ".lattice" / "config.toml").write_text("[budgets]\nfile_max = 99\n")
    (tmp_path / "_protocol.md").write_text("---\ntype: protocol\n---\n")
    b = budgets(tmp_path)
    assert b["file_max"] == 99       # override wins
    assert b["file_warn"] == 6000    # default survives
