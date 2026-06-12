"""Local usage tracking + `lattice stats`.

usage.py records command invocations (and context token-savings) to a local
JSONL — gitignored, no telemetry. `lattice stats` summarizes it honestly,
including what it CANNOT measure.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from click.testing import CliRunner

from lattice import usage
from lattice.cli import main


def _vault(root: Path) -> None:
    CliRunner().invoke(main, ["init", str(root)])


def _run(root: Path, *args: str):
    cwd = os.getcwd()
    try:
        os.chdir(root)
        return CliRunner().invoke(main, list(args))
    finally:
        os.chdir(cwd)


# ---------- usage log ----------

def test_record_invocation_appends(tmp_path: Path):
    _vault(tmp_path)
    usage.record(tmp_path, "lint")
    usage.record(tmp_path, "context", tokens_served=140, tokens_vault=47000)
    rows = usage.load(tmp_path)
    assert [r["cmd"] for r in rows] == ["lint", "context"]
    assert rows[1]["tokens_served"] == 140 and rows[1]["tokens_vault"] == 47000


def test_load_missing_is_empty(tmp_path: Path):
    assert usage.load(tmp_path) == []


def test_summarize_counts_and_context_metrics(tmp_path: Path):
    """The honest metric: per-call served + avg served + avg vault size.
    NO summed 'tokens_saved' across calls (that overcounts and can exceed the
    vault when the vault grows between calls)."""
    _vault(tmp_path)
    usage.record(tmp_path, "lint")
    usage.record(tmp_path, "lint")
    usage.record(tmp_path, "context", tokens_served=200, tokens_vault=5000)
    usage.record(tmp_path, "context", tokens_served=400, tokens_vault=6000)
    s = usage.summarize(tmp_path)
    assert s["counts"]["lint"] == 2
    assert s["counts"]["context"] == 2
    assert s["context_calls"] == 2
    assert s["context_tokens_served_total"] == 600
    assert s["context_tokens_served_avg"] == 300        # 600/2
    assert s["context_tokens_vault_avg"] == 5500        # (5000+6000)/2
    # ratio = avg served / avg vault, capped at 1.0 (a context call can never
    # legitimately serve more than the vault)
    assert abs(s["context_served_ratio"] - (300 / 5500)) < 1e-9
    # the misleading summed-saved field is gone
    assert "tokens_saved" not in s


# ---------- the command ----------

def test_stats_command_runs_and_reports(tmp_path: Path):
    _vault(tmp_path)
    # a couple of invocations + an outcome
    _run(tmp_path, "lint")
    _run(tmp_path, "doctor")
    res = _run(tmp_path, "stats")
    assert res.exit_code == 0, res.output
    out = res.output.lower()
    # surfaces command usage and the honesty section
    assert "lint" in out
    assert "cannot" in out or "not measured" in out  # explicit limits section


def test_stats_empty_vault_is_graceful(tmp_path: Path):
    _vault(tmp_path)
    res = _run(tmp_path, "stats")
    assert res.exit_code == 0, res.output
    assert "no usage" in res.output.lower() or "0" in res.output


def test_invocations_are_logged_by_running_commands(tmp_path: Path):
    """Running a real command writes a usage row (via the group callback)."""
    _vault(tmp_path)
    _run(tmp_path, "lint")
    rows = usage.load(tmp_path)
    assert any(r["cmd"] == "lint" for r in rows)


def test_usage_log_is_local_only(tmp_path: Path):
    """Log lives under .lattice/cache/ (gitignored); no network primitives."""
    _vault(tmp_path)
    usage.record(tmp_path, "lint")
    p = tmp_path / ".lattice" / "cache" / "usage.jsonl"
    assert p.exists()
    import inspect
    src = inspect.getsource(usage)
    for bad in ("requests", "urllib.request", "socket", "http"):
        assert bad not in src, f"usage must not have network primitive {bad!r}"
