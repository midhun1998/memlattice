"""Cost circuit-breaker — a pure-local, per-day USD ledger.

memgram's most important lesson: unattended spend needs a hard cap, and silence
is never green. lattice has no live billing API, so the breaker projects spend
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


def _today() -> str:
    """Today's date as ISO yyyy-mm-dd. Wrapped so tests can monkeypatch it."""
    return dt.date.today().isoformat()


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


def spent_today(vault: Path) -> float:
    """USD already spent today per the local ledger (0.0 if none/unknown)."""
    return _load(vault).get(_today(), 0.0)


def record(vault: Path, amount: float) -> float:
    """Add `amount` USD to today's ledger entry; return the new daily total.

    Read-modify-write tolerant of a corrupt file (treated as empty). Negative
    or non-finite amounts are ignored (defensive — estimates are always >= 0).
    """
    try:
        amt = float(amount)
    except (TypeError, ValueError):
        return spent_today(vault)
    if amt <= 0 or amt != amt:  # skip zero/negative/NaN
        return spent_today(vault)
    ledger = _load(vault)
    today = _today()
    ledger[today] = round(ledger.get(today, 0.0) + amt, 6)
    _save(vault, ledger)
    return ledger[today]


@dataclass
class Decision:
    allow: bool
    reason: str
    spent: float
    ceiling: float
    est_cost: float


def check(vault: Path, est_cost: float, max_usd_per_day: float, force: bool = False) -> Decision:
    """Decide whether a spend of `est_cost` USD is permitted today.

    Rules:
    - `force=True` always allows (explicit per-invocation override).
    - ceiling 0 means "never spend" -> blocked unless forced.
    - otherwise allowed iff spent_today + est_cost <= ceiling.

    Returns a Decision carrying a clear, ceiling-naming reason string for the
    blocked case so callers can surface it verbatim.
    """
    spent = spent_today(vault)
    if force:
        return Decision(True, "forced override (--force-spend)", spent, max_usd_per_day, est_cost)
    if max_usd_per_day <= 0:
        return Decision(
            False,
            (f"cost ceiling ${max_usd_per_day:.2f}/day reached (no budget set) — "
             "raise [budget] max_usd_per_day or pass --force-spend"),
            spent, max_usd_per_day, est_cost,
        )
    projected = spent + est_cost
    if projected > max_usd_per_day:
        return Decision(
            False,
            (f"cost ceiling ${max_usd_per_day:.2f}/day reached "
             f"(spent ${spent:.4f}, next call ~${est_cost:.4f}) — "
             "raise [budget] max_usd_per_day or pass --force-spend"),
            spent, max_usd_per_day, est_cost,
        )
    return Decision(True, "under ceiling", spent, max_usd_per_day, est_cost)
