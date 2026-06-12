"""Local usage tracking for `lattice stats`.

Records one JSONL row per command invocation to `.lattice/cache/usage.jsonl`
(local only — gitignored via `.lattice/cache/`, never sent over the network, no
telemetry). `context` rows also carry tokens_served/tokens_vault so stats can
report real token savings. `summarize` folds the log into honest metrics.

Pure-local: stdlib json + datetime only. No network, no vendor names.
"""
from __future__ import annotations

import datetime as dt
import json
from collections import Counter
from pathlib import Path
from typing import Any


def _path(vault: Path) -> Path:
    return vault / ".lattice" / "cache" / "usage.jsonl"


def record(vault: Path, cmd: str, *, tokens_served: int | None = None,
           tokens_vault: int | None = None) -> None:
    """Append one invocation row. Best-effort: never raises into the caller
    (a usage-log failure must not break the actual command)."""
    try:
        p = _path(vault)
        p.parent.mkdir(parents=True, exist_ok=True)
        rec: dict[str, Any] = {
            "ts": dt.datetime.now(dt.timezone.utc).isoformat(),
            "cmd": cmd,
        }
        if tokens_served is not None:
            rec["tokens_served"] = int(tokens_served)
        if tokens_vault is not None:
            rec["tokens_vault"] = int(tokens_vault)
        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")
    except OSError:
        pass


def load(vault: Path) -> list[dict[str, Any]]:
    """Load usage rows. Missing/corrupt lines are skipped (never raises)."""
    p = _path(vault)
    if not p.exists():
        return []
    rows = []
    try:
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    except OSError:
        return []
    return rows


def summarize(vault: Path) -> dict[str, Any]:
    """Fold the usage log into honest metrics. Per-command counts, plus for
    `context` calls: total/avg tokens served and avg vault size, with a served-
    ratio (avg served / avg vault). We deliberately do NOT report a summed
    'tokens_saved' across calls — that overcounts (each call's vault total is
    only ever served once, and the sum can exceed the vault when it grows
    between calls). The honest comparison is per-call: how much got served vs.
    the vault we're serving from."""
    rows = load(vault)
    counts = Counter(r.get("cmd", "?") for r in rows)
    served = [r["tokens_served"] for r in rows
              if r.get("cmd") == "context" and "tokens_served" in r and "tokens_vault" in r]
    vault_sizes = [r["tokens_vault"] for r in rows
                   if r.get("cmd") == "context" and "tokens_served" in r and "tokens_vault" in r]
    n_ctx = len(served)
    served_total = sum(served)
    served_avg = (served_total // n_ctx) if n_ctx else 0
    vault_avg = (sum(vault_sizes) // n_ctx) if n_ctx else 0
    ratio = (served_avg / vault_avg) if vault_avg else 0.0
    ratio = min(ratio, 1.0)  # cap: served can't honestly exceed vault
    ts = [r["ts"] for r in rows if "ts" in r]
    return {
        "total": len(rows),
        "counts": dict(counts),
        "context_calls": n_ctx,
        "context_tokens_served_total": served_total,
        "context_tokens_served_avg": served_avg,
        "context_tokens_vault_avg": vault_avg,
        "context_served_ratio": ratio,
        "first_seen": min(ts) if ts else None,
        "last_seen": max(ts) if ts else None,
    }
