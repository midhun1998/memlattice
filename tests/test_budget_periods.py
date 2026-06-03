"""Cost-breaker reset periods: hourly / daily / weekly / monthly.

Generalizes the daily-only ledger. `[budget] reset` selects the bucket; the
ledger keys on a period bucket so spend resets when the bucket rolls over.
Backward compatible: default is daily and the legacy `max_usd_per_day` key and
existing daily ledgers keep working.
"""
from __future__ import annotations

from pathlib import Path

from lattice import budget


def test_period_key_shapes():
    """Each reset maps a fixed instant to its expected bucket key."""
    # a fixed datetime: 2026-06-03T14:25, which is ISO week 23
    stamp = "2026-06-03T14:25:00"
    assert budget._period_key("hourly", stamp) == "2026-06-03T14"
    assert budget._period_key("daily", stamp) == "2026-06-03"
    assert budget._period_key("weekly", stamp) == "2026-W23"
    assert budget._period_key("monthly", stamp) == "2026-06"


def test_unknown_reset_falls_back_to_daily():
    stamp = "2026-06-03T14:25:00"
    assert budget._period_key("bogus", stamp) == budget._period_key("daily", stamp)


def test_spent_in_period_isolates_buckets(tmp_path: Path, monkeypatch):
    _init(tmp_path)
    # record in hour 14, then roll to hour 15 -> fresh bucket
    monkeypatch.setattr(budget, "_now", lambda: "2026-06-03T14:00:00")
    budget.record(tmp_path, 0.30, reset="hourly")
    assert budget.spent_in_period(tmp_path, "hourly") == 0.30
    monkeypatch.setattr(budget, "_now", lambda: "2026-06-03T15:00:00")
    assert budget.spent_in_period(tmp_path, "hourly") == 0.0


def test_monthly_accumulates_across_days(tmp_path: Path, monkeypatch):
    _init(tmp_path)
    monkeypatch.setattr(budget, "_now", lambda: "2026-06-03T10:00:00")
    budget.record(tmp_path, 0.20, reset="monthly")
    monkeypatch.setattr(budget, "_now", lambda: "2026-06-20T10:00:00")
    budget.record(tmp_path, 0.30, reset="monthly")
    assert round(budget.spent_in_period(tmp_path, "monthly"), 4) == 0.50
    # next month resets
    monkeypatch.setattr(budget, "_now", lambda: "2026-07-01T10:00:00")
    assert budget.spent_in_period(tmp_path, "monthly") == 0.0


def test_check_uses_configured_period(tmp_path: Path, monkeypatch):
    _init(tmp_path)
    monkeypatch.setattr(budget, "_now", lambda: "2026-06-03T14:00:00")
    budget.record(tmp_path, 0.90, reset="weekly")
    # within the same week, ceiling 1.00 leaves 0.10 -> a 0.20 call is blocked
    d = budget.check(tmp_path, est_cost=0.20, max_usd=1.00, reset="weekly")
    assert d.allow is False
    # a 0.05 call fits
    assert budget.check(tmp_path, est_cost=0.05, max_usd=1.00, reset="weekly").allow is True


def test_backward_compat_daily_default(tmp_path: Path, monkeypatch):
    """No reset specified == daily; legacy spent_today still works."""
    _init(tmp_path)
    monkeypatch.setattr(budget, "_now", lambda: "2026-06-03T14:00:00")
    budget.record(tmp_path, 0.10)  # default daily
    assert budget.spent_today(tmp_path) == 0.10
    assert budget.spent_in_period(tmp_path, "daily") == 0.10


def _init(root: Path) -> None:
    (root / ".lattice" / "cache").mkdir(parents=True, exist_ok=True)
