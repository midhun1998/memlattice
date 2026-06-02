"""P3-G — `lattice schedule` prints a ready-to-paste cron/launchd snippet.

lattice ships NO daemon. `schedule` only PRINTS a snippet to stdout; the user
installs it themselves. Nothing runs unattended by us. The scheduled command is
config-driven (no vendor/tool name hardcoded in core), and the snippet reminds
the user that the job still obeys `[budget] max_usd_per_day`.

All examples are fabricated (checkout, payment-gateway, jira).
"""
from __future__ import annotations

import os
from pathlib import Path

from click.testing import CliRunner

from lattice.cli import main


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


def test_schedule_cron_snippet_contains_lattice_and_vault(tmp_path: Path):
    _init(tmp_path)
    res = _run(tmp_path, "schedule", "--cron")
    assert res.exit_code == 0, res.output
    out = res.output
    # a crontab time spec: five fields then the command
    assert "lattice" in out
    assert str(tmp_path) in out  # references the vault path
    # default scheduled command is `refresh` (config default)
    assert "refresh" in out
    # cron line has the canonical 5-field minute-hour-dom-month-dow shape
    assert any(line.strip() and line.split()[0].isdigit() for line in out.splitlines())


def test_schedule_launchd_snippet_is_valid_plist(tmp_path: Path):
    _init(tmp_path)
    res = _run(tmp_path, "schedule", "--launchd", "--at", "04:30")
    assert res.exit_code == 0, res.output
    out = res.output
    assert "<?xml" in out and "<plist" in out
    assert "StartCalendarInterval" in out
    assert "<key>Hour</key>" in out and "<integer>4</integer>" in out
    assert "<key>Minute</key>" in out and "<integer>30</integer>" in out
    assert "ProgramArguments" in out


def test_schedule_command_is_config_driven(tmp_path: Path):
    """[schedule] command='digest' makes the snippet schedule digest, not a
    hardcoded default. No vendor/tool literal in core."""
    _init(tmp_path)
    _set_config(tmp_path, '[schedule]\ncommand = "digest"\n')
    res = _run(tmp_path, "schedule", "--cron")
    assert res.exit_code == 0, res.output
    assert "digest" in res.output
    # core schedule module must not hardcode a vendor/tool name
    import inspect
    import lattice.schedule as s
    src = inspect.getsource(s).lower()
    for bad in ("salesforce", "soma", "dpc", "sfmp", "llmg", "splunk", "slack"):
        assert bad not in src, f"vendor/tool literal {bad!r} must not appear in core"


def test_schedule_prints_does_not_install(tmp_path: Path, monkeypatch):
    """Schedule only writes to stdout — it never installs a crontab or writes a
    launchd plist file."""
    _init(tmp_path)

    import subprocess
    called = {"run": 0}
    real_run = subprocess.run

    def _guard(*a, **k):  # any crontab/launchctl install attempt is a failure
        cmd = a[0] if a else k.get("args")
        flat = " ".join(cmd) if isinstance(cmd, (list, tuple)) else str(cmd)
        assert "crontab" not in flat and "launchctl" not in flat, f"must not install: {flat}"
        called["run"] += 1
        return real_run(*a, **k)

    monkeypatch.setattr(subprocess, "run", _guard)
    res = _run(tmp_path, "schedule", "--cron")
    assert res.exit_code == 0, res.output
    # no plist file written anywhere under the vault
    assert not list(tmp_path.rglob("*.plist"))


def test_schedule_snippet_reminds_of_budget_cap(tmp_path: Path):
    """An unattended job must not silently spend — the snippet comment mentions
    the budget ceiling so the installer knows the cap still applies."""
    _init(tmp_path)
    res = _run(tmp_path, "schedule", "--cron")
    assert res.exit_code == 0, res.output
    lower = res.output.lower()
    assert "budget" in lower or "max_usd_per_day" in lower


def test_schedule_every_hours(tmp_path: Path):
    """--every Nh emits an interval-based cron spec instead of a daily time."""
    _init(tmp_path)
    res = _run(tmp_path, "schedule", "--cron", "--every", "6h")
    assert res.exit_code == 0, res.output
    assert "*/6" in res.output or "/6" in res.output
