"""verify Layer 2 — entailment (opt-in, budget-gated).

For a `present`/`fetched` citation, an LLM-as-judge checks whether the cited
source text actually SUPPORTS the claim:
  supported | contradicted | unsupported | unverifiable
Off by default; runs only with --entail AND when the budget breaker allows.
The LLM is mocked here — no real network/spend in tests.
"""
from __future__ import annotations

import os
from pathlib import Path

from click.testing import CliRunner

from lattice import agentic, verify
from lattice.cli import main


def test_entail_judge_parses_supported(monkeypatch):
    """entail() maps a judge verdict to a status; LLM call is mocked."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "dummy")
    monkeypatch.setattr(agentic, "_entail_call", lambda claim, source, model=None: "SUPPORTED")
    assert agentic.entail("the gateway retries 3x", "Gateway retries three times.") == "supported"


def test_entail_judge_parses_contradicted(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "dummy")
    monkeypatch.setattr(agentic, "_entail_call", lambda claim, source, model=None: "CONTRADICTED")
    assert agentic.entail("retries 5x", "Gateway retries three times.") == "contradicted"


def test_entail_no_key_returns_unverifiable(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert agentic.entail("x", "y") == "unverifiable"


def test_entail_status_is_fail():
    assert verify.is_fail("contradicted")
    assert verify.is_fail("unsupported")
    assert not verify.is_fail("supported")
    assert not verify.is_fail("unverifiable")  # can't judge != wrong


# ---------- CLI: --entail gated by budget ----------

def _vault(tmp_path: Path) -> None:
    CliRunner().invoke(main, ["init", str(tmp_path)])


def _run(root: Path, *args: str):
    cwd = os.getcwd()
    try:
        os.chdir(root)
        return CliRunner().invoke(main, list(args))
    finally:
        os.chdir(cwd)


def _note_with_present_citation(tmp_path: Path) -> None:
    (tmp_path / "ref.txt").write_text("The gateway retries three times.\n")
    (tmp_path / "flows" / "f.md").write_text(
        "---\ntype: flow\nlast_verified: 2026-06-03\nrelated: []\n---\n\n"
        "# F\n\nThe gateway retries 5 times [file:ref.txt].\n\n"
        "## Open questions\n- none\n\n## Referenced by\n_none_\n"
    )


def test_entail_skipped_when_budget_zero(tmp_path: Path, monkeypatch):
    """--entail with default $0 budget must NOT call the judge (no spend)."""
    _vault(tmp_path)
    _note_with_present_citation(tmp_path)
    called = {"n": 0}
    monkeypatch.setattr(agentic, "_entail_call", lambda *a, **k: called.__setitem__("n", called["n"] + 1) or "CONTRADICTED")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "dummy")
    res = _run(tmp_path, "verify", "--entail")
    # budget defaults to 0 -> judge never called -> Layer-1 'present' stands
    assert called["n"] == 0, res.output
    assert res.exit_code == 0, res.output


def test_entail_runs_and_fails_on_contradiction(tmp_path: Path, monkeypatch):
    """With budget raised, --entail calls the judge; a contradiction FAILS."""
    _vault(tmp_path)
    _note_with_present_citation(tmp_path)
    (tmp_path / ".lattice" / "config.toml").write_text(
        "[budget]\nmax_usd_per_day = 5.0\n"
    )
    monkeypatch.setenv("ANTHROPIC_API_KEY", "dummy")
    monkeypatch.setattr(agentic, "_entail_call", lambda claim, source, model=None: "CONTRADICTED")
    res = _run(tmp_path, "verify", "--entail")
    assert res.exit_code != 0, res.output
    assert "contradicted" in res.output.lower()
