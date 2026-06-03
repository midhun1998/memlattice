"""Cost circuit-breaker — a pure-local, per-day USD ledger.

The guiding principle: unattended spend needs a hard cap, and silence is never
green. lattice has no live billing API, so the breaker projects spend
from a config-driven per-call ESTIMATE (never a baked-in vendor price) and
consults a local JSON ledger BEFORE any spend on the only LLM-spending path
(`digest` via the Claude route; the future `refresh` will call the same seam).

Default ceiling 0 means "never spend without an explicit override" — so even
with an API key set, the costly path is gated off until the user raises
`[budget] max_usd_per_day` or passes a per-run override.

Pure stdlib (json + datetime + pathlib). No network, no daemon, no new deps.
The ledger read tolerates a missing/corrupt file (returns empty, mirroring
agentic._load_cache) so a racing cron job + interactive run can never crash.
"""
from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass
from pathlib import Path

LEDGER_FILE_NAME = "budget-ledger.json"


VALID_RESETS = ("hourly", "daily", "weekly", "monthly")


def _now() -> str:
    """Current local time as ISO 'yyyy-mm-ddThh:mm:ss'. Wrapped for tests."""
    return dt.datetime.now().isoformat(timespec="seconds")


def _today() -> str:
    """Today's date as ISO yyyy-mm-dd. Kept for backward compatibility; derived
    from `_now` so monkeypatching either works."""
    return _now()[:10]


def _period_key(reset: str, stamp: str | None = None) -> str:
    """Bucket key for a reset period given an ISO datetime stamp.

    hourly -> 2026-06-03T14 · daily -> 2026-06-03 ·
    weekly -> 2026-W23 (ISO week) · monthly -> 2026-06.
    Unknown reset falls back to daily.
    """
    s = stamp if stamp is not None else _now()
    d = dt.datetime.fromisoformat(s)
    if reset == "hourly":
        return d.strftime("%Y-%m-%dT%H")
    if reset == "weekly":
        iso = d.isocalendar()
        return f"{iso[0]}-W{iso[1]:02d}"
    if reset == "monthly":
        return d.strftime("%Y-%m")
    # daily (and any unknown value)
    return d.strftime("%Y-%m-%d")


def _ledger_path(vault: Path) -> Path:
    d = vault / ".lattice" / "cache"
    d.mkdir(parents=True, exist_ok=True)
    return d / LEDGER_FILE_NAME


def _load(vault: Path) -> dict[str, float]:
    """Load the date -> spend map. Missing/corrupt -> empty (never raises)."""
    p = _ledger_path(vault)
    if p.exists():
        try:
            data = json.loads(p.read_text())
        except (json.JSONDecodeError, OSError):
            return {}
        if isinstance(data, dict):
            # coerce values defensively; drop anything non-numeric
            out: dict[str, float] = {}
            for k, v in data.items():
                if isinstance(k, str) and isinstance(v, (int, float)) and not isinstance(v, bool):
                    out[k] = float(v)
            return out
    return {}


def _save(vault: Path, ledger: dict[str, float]) -> None:
    _ledger_path(vault).write_text(json.dumps(ledger, indent=2, sort_keys=True))


def spent_in_period(vault: Path, reset: str = "daily") -> float:
    """USD spent in the current bucket for `reset` (0.0 if none/unknown)."""
    return _load(vault).get(_period_key(reset), 0.0)


def spent_today(vault: Path) -> float:
    """USD already spent today (daily bucket). Backward-compatible alias."""
    return spent_in_period(vault, "daily")


def record(vault: Path, amount: float, reset: str = "daily") -> float:
    """Add `amount` USD to the current `reset` bucket; return the new bucket total.

    Read-modify-write tolerant of a corrupt file (treated as empty). Negative
    or non-finite amounts are ignored (defensive — estimates are always >= 0).
    """
    try:
        amt = float(amount)
    except (TypeError, ValueError):
        return spent_in_period(vault, reset)
    if amt <= 0 or amt != amt:  # skip zero/negative/NaN
        return spent_in_period(vault, reset)
    ledger = _load(vault)
    key = _period_key(reset)
    ledger[key] = round(ledger.get(key, 0.0) + amt, 6)
    _save(vault, ledger)
    return ledger[key]


@dataclass
class Decision:
    allow: bool
    reason: str
    spent: float
    ceiling: float
    est_cost: float


def check(vault: Path, est_cost: float, max_usd: float | None = None,
          reset: str = "daily", force: bool = False,
          *, max_usd_per_day: float | None = None) -> Decision:
    """Decide whether a spend of `est_cost` USD is permitted in the current
    `reset` bucket.

    `max_usd` is the ceiling for the configured period; `max_usd_per_day` is a
    backward-compatible alias (daily). Rules:
    - `force=True` always allows (explicit per-invocation override).
    - ceiling 0 means "never spend" -> blocked unless forced.
    - otherwise allowed iff spent_in_period + est_cost <= ceiling.
    """
    ceiling = max_usd if max_usd is not None else (max_usd_per_day or 0.0)
    label = {"hourly": "hour", "daily": "day", "weekly": "week", "monthly": "month"}.get(reset, reset)
    spent = spent_in_period(vault, reset)
    if force:
        return Decision(True, "forced override (--force-spend)", spent, ceiling, est_cost)
    if ceiling <= 0:
        return Decision(
            False,
            (f"cost ceiling ${ceiling:.2f}/{label} reached (no budget set) — "
             "raise [budget] max_usd_per_day or pass --force-spend"),
            spent, ceiling, est_cost,
        )
    if spent + est_cost > ceiling:
        return Decision(
            False,
            (f"cost ceiling ${ceiling:.2f}/{label} reached "
             f"(spent ${spent:.4f}, next call ~${est_cost:.4f}) — "
             "raise [budget] max_usd_per_day or pass --force-spend"),
            spent, ceiling, est_cost,
        )
    return Decision(True, "under ceiling", spent, ceiling, est_cost)
