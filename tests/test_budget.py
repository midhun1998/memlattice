"""Cost circuit-breaker (`[budget] max_usd_per_day`, default 0).

Guiding principle: unattended spend needs a hard cap, and silence is never
green. The breaker is a pure-local, per-day USD ledger consulted BEFORE any
spend on the only LLM-spending path (`digest` via the Claude/agentic route).
Default ceiling 0 means the Claude path is off-by-default; `digest` silently
uses its existing heuristic fallback unless the user raises the cap or passes
an explicit per-run override.

All examples are fabricated (checkout, payment-gateway, jira).
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import os
from pathlib import Path

import pytest
from click.testing import CliRunner

from lattice.cli import main

# The Claude path (and these tests that spy on it) only exist when the optional
# `agentic` extra is installed. Without it, lattice degrades to the heuristic —
# so skip the SDK-dependent budget tests rather than fail.
HAS_ANTHROPIC = importlib.util.find_spec("anthropic") is not None
requires_anthropic = pytest.mark.skipif(
    not HAS_ANTHROPIC, reason="requires the optional `agentic` extra (anthropic)"
)


# ---------- shared helpers ----------

def _init(root: Path) -> None:
    CliRunner().invoke(main, ["init", str(root)])


def _set_config(root: Path, body: str) -> None:
    (root / ".lattice" / "config.toml").write_text(body)


def _run(root: Path, *args: str):
    cwd = os.getcwd()
    try:
        os.chdir(root)
        return CliRunner().invoke(main, list(args))
    finally:
        os.chdir(cwd)


HISTORY = """\
# Session 2026-05-01
- did the checkout flow refactor
- touched payment-gateway adapter
- learned the ledger settles asynchronously

# Session 2026-05-02
- wired up the jira citation scheme
- fixed a lint false positive

# Session 2026-05-03
- shipped the digest command
- still owe docs

# Session 2026-05-04
- recent session kept verbatim
"""


def _write_history(root: Path) -> Path:
    p = root / ".CLAUDE.HISTORY"
    p.write_text(HISTORY)
    return p


def _spy_anthropic(monkeypatch):
    """Install a spy Anthropic client; returns a dict whose 'count' counts
    constructions. Patches both the agentic module ref and the SDK so neither
    lazy-import path can slip a real construction through.

    Crucially, the constructor RAISES after counting — agentic_stub's try/except
    would otherwise silently swallow a real construction and still fall back to
    the heuristic, hiding the bug. The count survives the except, so the test
    asserts the *construction attempt* never happened, not just the output shape.
    """
    seen = {"count": 0}

    class _Spy:
        def __init__(self, *a, **k):
            seen["count"] += 1
            raise RuntimeError("spy: must not be constructed under budget gate")

    import lattice.agentic as ag
    monkeypatch.setattr(ag, "Anthropic", _Spy, raising=False)
    import anthropic
    monkeypatch.setattr(anthropic, "Anthropic", _Spy, raising=False)
    return seen


# ============ FAILING-FIRST integration test ============

@requires_anthropic
def test_digest_with_zero_ceiling_does_not_call_claude(tmp_path: Path, monkeypatch):
    """Default ceiling 0 = never spend. Even with a key set and the SDK present,
    `digest` must NOT construct the Claude client; it degrades to the heuristic.

    This is the failing-first test: today agentic_stub calls Claude whenever the
    key is present, with no budget gate, so the Anthropic client IS constructed.
    """
    monkeypatch.setenv("ANTHROPIC_API_KEY", "dummy-key-not-real")
    _init(tmp_path)
    # ceiling 0 is the default; be explicit to document intent
    _set_config(tmp_path, "[budget]\nmax_usd_per_day = 0\n")
    hist = _write_history(tmp_path)

    seen = _spy_anthropic(monkeypatch)

    res = _run(tmp_path, "digest", str(hist), "--write")
    assert res.exit_code == 0, res.output
    assert seen["count"] == 0, "Anthropic client constructed despite zero budget ceiling"
    # heuristic stub still produced a digest (the archived sessions are stubbed)
    digested = hist.read_text()
    assert "digested by lattice" in digested


# ============ breaker unit tests ============

def test_breaker_allows_when_under_ceiling(tmp_path: Path):
    from lattice import budget

    _init(tmp_path)
    decision = budget.check(tmp_path, est_cost=0.002, max_usd_per_day=1.00)
    assert decision.allow is True


def test_breaker_blocks_when_next_call_exceeds(tmp_path: Path):
    from lattice import budget

    _init(tmp_path)
    budget.record(tmp_path, 0.999)
    decision = budget.check(tmp_path, est_cost=0.002, max_usd_per_day=1.00)
    assert decision.allow is False
    assert "1.00" in decision.reason or "1.0" in decision.reason
    assert "ceiling" in decision.reason.lower() or "cap" in decision.reason.lower()


def test_ledger_resets_across_days(tmp_path: Path, monkeypatch):
    from lattice import budget

    _init(tmp_path)
    # _today now derives from _now (period keys do too), so patch _now
    monkeypatch.setattr(budget, "_now", lambda: "2026-05-01T09:00:00")
    budget.record(tmp_path, 0.50)
    assert budget.spent_today(tmp_path) == 0.50
    # next day: fresh ledger window
    monkeypatch.setattr(budget, "_now", lambda: "2026-05-02T09:00:00")
    assert budget.spent_today(tmp_path) == 0.0


def test_record_spend_is_local_only(tmp_path: Path):
    from lattice import budget

    _init(tmp_path)
    budget.record(tmp_path, 0.01)
    ledger = tmp_path / ".lattice" / "cache" / "budget-ledger.json"
    assert ledger.exists(), "ledger must live under .lattice/cache/ (gitignored)"
    data = json.loads(ledger.read_text())
    assert isinstance(data, dict)
    # no network/no-daemon primitives in the budget module source
    import inspect
    import lattice.budget as b
    src = inspect.getsource(b)
    for bad in ("import sched", "import threading", "crontab", "APScheduler",
                "Timer(", "requests", "urllib.request", "socket"):
        assert bad not in src, f"network/unattended primitive {bad!r} must not appear"


@requires_anthropic
def test_force_spend_overrides_zero_ceiling(tmp_path: Path, monkeypatch):
    """max_usd_per_day=0 but `digest --force-spend` DOES construct the client."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "dummy-key-not-real")
    _init(tmp_path)
    _set_config(tmp_path, "[budget]\nmax_usd_per_day = 0\n")
    hist = _write_history(tmp_path)

    constructed = {"count": 0}

    class _FakeMsg:
        def __init__(self):
            self.content = [type("B", (), {"text": (
                "- **Done**: shipped checkout refactor\n"
                "- **Files**: cli.py, agentic.py\n"
                "- **Learned**: ledger settles asynchronously\n"
                "- **Open**: docs pending\n"
                "- **Next**: write the docs"
            )})()]

    class _FakeClient:
        def __init__(self, *a, **k):
            constructed["count"] += 1
            self.messages = self

        def create(self, *a, **k):
            return _FakeMsg()

    import lattice.agentic as ag
    monkeypatch.setattr(ag, "Anthropic", _FakeClient, raising=False)
    import anthropic
    monkeypatch.setattr(anthropic, "Anthropic", _FakeClient, raising=False)

    res = _run(tmp_path, "digest", str(hist), "--write", "--force-spend", "--no-cache")
    assert res.exit_code == 0, res.output
    assert constructed["count"] >= 1, "force-spend must bypass the zero ceiling"
    # spend recorded in the ledger
    from lattice import budget
    assert budget.spent_today(tmp_path) > 0


def test_digest_without_api_key_ignores_budget(tmp_path: Path, monkeypatch):
    """No key -> no spend would occur, so the breaker is irrelevant; digest works."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    _init(tmp_path)
    _set_config(tmp_path, "[budget]\nmax_usd_per_day = 0\n")
    hist = _write_history(tmp_path)

    res = _run(tmp_path, "digest", str(hist), "--write")
    assert res.exit_code == 0, res.output
    assert "digested by lattice" in hist.read_text()
    from lattice import budget
    assert budget.spent_today(tmp_path) == 0.0


def test_concurrent_safe_ledger_read_write(tmp_path: Path):
    """A missing/corrupt ledger returns empty (like agentic _load_cache)."""
    from lattice import budget

    _init(tmp_path)
    ledger = tmp_path / ".lattice" / "cache" / "budget-ledger.json"
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text("{ this is not valid json ")
    # must not raise
    assert budget.spent_today(tmp_path) == 0.0
    # and a subsequent record heals the file
    budget.record(tmp_path, 0.005)
    assert budget.spent_today(tmp_path) == 0.005


@requires_anthropic
def test_max_usd_override_flag_raises_ceiling(tmp_path: Path, monkeypatch):
    """`digest --max-usd` overrides the config ceiling for one run."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "dummy-key-not-real")
    _init(tmp_path)
    _set_config(tmp_path, "[budget]\nmax_usd_per_day = 0\nestimated_usd_per_digest = 0.002\n")
    hist = _write_history(tmp_path)

    constructed = {"count": 0}

    class _FakeMsg:
        def __init__(self):
            self.content = [type("B", (), {"text": (
                "- **Done**: d\n- **Files**: f\n- **Learned**: -\n"
                "- **Open**: o\n- **Next**: n"
            )})()]

    class _FakeClient:
        def __init__(self, *a, **k):
            constructed["count"] += 1
            self.messages = self

        def create(self, *a, **k):
            return _FakeMsg()

    import lattice.agentic as ag
    monkeypatch.setattr(ag, "Anthropic", _FakeClient, raising=False)
    import anthropic
    monkeypatch.setattr(anthropic, "Anthropic", _FakeClient, raising=False)

    res = _run(tmp_path, "digest", str(hist), "--write", "--max-usd", "1.0", "--no-cache")
    assert res.exit_code == 0, res.output
    assert constructed["count"] >= 1, "--max-usd should permit the spend"
