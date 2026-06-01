"""Vault config loader (.lattice/config.toml)."""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

try:
    import tomllib  # py311+
except ImportError:  # pragma: no cover
    import tomli as tomllib  # type: ignore


# Vendor-neutral citation schemes shipped by default. NOTHING internal or
# product-specific belongs here — users add their own (jira, linear, ...)
# via `[citations] extra = [...]` in config.toml.
DEFAULT_CITATION_SCHEMES = ("file", "doc", "url", "commit", "pr", "conv", "chat")

# Default note types -> their directory. Users extend/remap via `[types]`.
DEFAULT_TYPES: dict[str, str] = {
    "flow": "flows",
    "component": "components",
    "api": "api",
}


def load_config(vault: Path | None) -> dict[str, Any]:
    if vault is None:
        return {}
    cfg_path = vault / ".lattice" / "config.toml"
    if not cfg_path.exists():
        return {}
    with cfg_path.open("rb") as f:
        return tomllib.load(f)


def citation_schemes(vault: Path | None) -> list[str]:
    """Return the citation scheme names valid for this vault.

    Defaults ∪ user-declared `[citations] extra`. Order-stable, de-duped.
    """
    cfg = load_config(vault)
    extra = (cfg.get("citations") or {}).get("extra") or []
    schemes: list[str] = list(DEFAULT_CITATION_SCHEMES)
    for s in extra:
        if isinstance(s, str) and s and s not in schemes:
            schemes.append(s)
    return schemes


def citation_regex(vault: Path | None) -> re.Pattern[str]:
    """Compile the citation matcher from the vault's configured schemes."""
    alternation = "|".join(re.escape(s) for s in citation_schemes(vault))
    return re.compile(rf"\[(?:{alternation}):[^\]]+\]")


# Per-file token-budget defaults. Mirrors the [budgets] table scaffolded in
# CONFIG_TOML. lint + doctor both route through this so they never disagree.
DEFAULT_BUDGETS: dict[str, int] = {"file_warn": 6000, "file_max": 12000}


def budgets(vault: Path | None) -> dict[str, int]:
    """Return per-file token budgets. Defaults, overridden by `[budgets]`
    (config wins per-key; unspecified keys keep their default)."""
    cfg = load_config(vault)
    out = dict(DEFAULT_BUDGETS)
    for key in out:
        val = (cfg.get("budgets") or {}).get(key)
        if isinstance(val, int) and not isinstance(val, bool):
            out[key] = val
    return out


# Defaults for the `[learn]` outcome rank boost. Deliberately CONSERVATIVE:
# a fully-fresh positive outcome only lifts BM25 by `boost`; recency decay
# fades old outcomes toward no effect. If outcomes.jsonl is absent/empty every
# multiplier is 1.0 (pure BM25), so behavior matches a vault that never used
# `lattice used`.
DEFAULT_LEARN: dict[str, Any] = {
    "enabled": True,
    "boost": 0.15,
    "penalty": 0.30,
    "half_life_days": 30.0,
}


def learn_config(vault: Path | None) -> dict[str, Any]:
    """Return the `[learn]` config. Defaults, overridden per-key by `[learn]`
    (config wins; unspecified keys keep their default)."""
    cfg = load_config(vault)
    out = dict(DEFAULT_LEARN)
    table = cfg.get("learn") or {}
    for key in out:
        if key not in table:
            continue
        val = table[key]
        if key == "enabled":
            if isinstance(val, bool):
                out[key] = val
        elif isinstance(val, (int, float)) and not isinstance(val, bool):
            out[key] = float(val)
    return out


def note_types(vault: Path | None) -> dict[str, str]:
    """Return type -> directory map. Defaults ∪ user `[types]` (config wins)."""
    cfg = load_config(vault)
    types = dict(DEFAULT_TYPES)
    for name, directory in (cfg.get("types") or {}).items():
        if isinstance(name, str) and isinstance(directory, str) and directory:
            types[name] = directory
    return types


def run_hook(vault: Path, event: str, args: str = "", output_file: Path | None = None) -> None:
    """Fire the post-<event> hook if configured. Failures are warnings, not errors."""
    cfg = load_config(vault)
    cmd = (cfg.get("hooks") or {}).get(f"post-{event}")
    if not cmd:
        return
    env = os.environ.copy()
    env.update({
        "LATTICE_VAULT": str(vault),
        "LATTICE_EVENT": event,
        "LATTICE_ARGS": args,
    })
    if output_file is not None:
        env["LATTICE_OUTPUT_FILE"] = str(output_file)
    try:
        subprocess.run(cmd, shell=True, cwd=vault, env=env, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        print(f"[lattice] post-{event} hook failed (rc={e.returncode}): {e.stderr.strip()}", file=sys.stderr)


def hook_summary(vault: Path) -> list[str]:
    cfg = load_config(vault)
    return [f"{k}: {v}" for k, v in (cfg.get("hooks") or {}).items()]
