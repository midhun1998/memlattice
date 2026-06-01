"""Local outcome store + conservative rank boost.

`lattice used` appends one JSONL record per invocation to
`.lattice/cache/outcomes.jsonl` (local only — gitignored via `.lattice/cache/`,
never sent over the network, no telemetry). `slug_multipliers` folds those
records into a per-slug multiplier that `lattice context` applies on top of
BM25 so recently/positively-used notes rank slightly higher and `--bad`-marked
notes are slightly penalized.

Borrows only the SHAPE of an outcome record (good flag + a list of ids) — none
of the constants. All knobs live in `[learn]` (see config.learn_config). Pure
local math over slugs: no vendor names, no source systems.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any


def _outcomes_path(vault: Path) -> Path:
    return vault / ".lattice" / "cache" / "outcomes.jsonl"


def record(vault: Path, slugs: list[str], good: bool) -> None:
    """Append one JSONL outcome record. Creates the cache dir if needed.

    Record shape: {"ts": <iso8601 UTC>, "slugs": [...], "good": <bool>}.
    """
    path = _outcomes_path(vault)
    path.parent.mkdir(parents=True, exist_ok=True)
    rec = {
        "ts": dt.datetime.now(dt.timezone.utc).isoformat(),
        "slugs": list(slugs),
        "good": bool(good),
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")


def load_outcomes(vault: Path) -> list[dict[str, Any]]:
    """Read + parse the JSONL store, skipping malformed/non-conforming lines.

    Robust to a locally-edited file: a corrupt or non-JSON line is ignored
    rather than crashing the read-only `context` path.
    """
    path = _outcomes_path(vault)
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except (ValueError, TypeError):
            continue
        if not isinstance(rec, dict):
            continue
        if not isinstance(rec.get("slugs"), list):
            continue
        out.append(rec)
    return out


def _decay_weight(ts: str, now: dt.datetime, half_life_days: float) -> float:
    """Exponential recency weight in [0, 1]; 0.5 ** (age_days / half_life)."""
    try:
        when = dt.datetime.fromisoformat(ts)
    except (ValueError, TypeError):
        return 0.0
    if when.tzinfo is None:
        when = when.replace(tzinfo=dt.timezone.utc)
    age_days = (now - when).total_seconds() / 86400.0
    if age_days < 0:
        age_days = 0.0
    if half_life_days <= 0:
        return 1.0
    return 0.5 ** (age_days / half_life_days)


def slug_multipliers(
    vault: Path, cfg: dict[str, Any], now: dt.datetime | None = None
) -> dict[str, float]:
    """Fold outcomes into a per-slug BM25 multiplier.

    Each outcome contributes a recency-decayed signal in [-1, +1] per slug
    (positive for good, negative for --bad). The summed signal is clamped to
    [-1, 1], then mapped to a multiplier in `[epsilon, 1 + boost]`:
      signal >= 0 -> 1 + signal * boost      (max uplift = 1 + boost)
      signal <  0 -> 1 + signal * penalty     (floored at epsilon > 0)

    Unseen slugs are absent from the dict (callers treat that as 1.0). The
    penalty floor keeps a note from ever being zeroed out, preserving the
    relevance gate. `now` is injectable for deterministic recency tests.
    """
    boost = float(cfg.get("boost", 0.15))
    penalty = float(cfg.get("penalty", 0.30))
    half_life = float(cfg.get("half_life_days", 30.0))
    epsilon = 0.05
    if now is None:
        now = dt.datetime.now(dt.timezone.utc)

    signal: dict[str, float] = {}
    for rec in load_outcomes(vault):
        w = _decay_weight(str(rec.get("ts", "")), now, half_life)
        if w <= 0:
            continue
        sign = 1.0 if rec.get("good", True) else -1.0
        for slug in rec.get("slugs", []):
            if not isinstance(slug, str) or not slug:
                continue
            signal[slug] = signal.get(slug, 0.0) + sign * w

    mults: dict[str, float] = {}
    for slug, s in signal.items():
        s = max(-1.0, min(1.0, s))
        if s >= 0:
            mults[slug] = 1.0 + s * boost
        else:
            mults[slug] = max(epsilon, 1.0 + s * penalty)
    return mults
