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


# Defaults for the `[context]` table (retrieval-time ranking). `ranker` is the
# THREE-WAY switch shared by the CLI: "auto" uses the optional local-embedding
# ranker iff its extra is installed and ranker is not forced to "bm25"; "bm25"
# forces the legacy path; "embeddings" forces the optional ranker (degrading to
# BM25 with a notice if its backend is unavailable). `embedding_model` is left
# empty here on purpose — the default model id is resolved inside
# lattice/embeddings.py, never as a literal in core. `embedding_cache` persists
# per-note vectors under .lattice/cache/ (mirrors agentic.py's cache).
DEFAULT_CONTEXT: dict[str, Any] = {
    "ranker": "auto",
    "embedding_model": "",
    "embedding_cache": True,
}

_VALID_RANKERS = ("auto", "bm25", "embeddings")


def context_config(vault: Path | None) -> dict[str, Any]:
    """Return the `[context]` config. Defaults overridden per-key by `[context]`
    (config wins; unspecified keys keep their default). An unrecognised `ranker`
    string falls back to the default so a typo can never error the read-only
    `context` path."""
    cfg = load_config(vault)
    out = dict(DEFAULT_CONTEXT)
    table = cfg.get("context") or {}
    rk = table.get("ranker")
    if isinstance(rk, str) and rk in _VALID_RANKERS:
        out["ranker"] = rk
    em = table.get("embedding_model")
    if isinstance(em, str) and em:
        out["embedding_model"] = em
    ec = table.get("embedding_cache")
    if isinstance(ec, bool):
        out["embedding_cache"] = ec
    return out


def note_types(vault: Path | None) -> dict[str, str]:
    """Return type -> directory map. Defaults ∪ user `[types]` (config wins)."""
    cfg = load_config(vault)
    types = dict(DEFAULT_TYPES)
    for name, directory in (cfg.get("types") or {}).items():
        if isinstance(name, str) and isinstance(directory, str) and directory:
            types[name] = directory
    return types


# Defaults for the `[refresh]` table (the `lattice refresh` adapter run).
# `distill` no-ops without ANTHROPIC_API_KEY regardless of this flag; it's a
# global off-switch for the Claude path. `limit` caps drafted items per source.
DEFAULT_REFRESH: dict[str, Any] = {
    "distill": True,
    "inbox_dir": "_inbox",
    "limit": 50,
}


def refresh_config(vault: Path | None) -> dict[str, Any]:
    """Return the `[refresh]` config. Defaults overridden per-key by `[refresh]`
    (config wins; unspecified keys keep their default)."""
    cfg = load_config(vault)
    out = dict(DEFAULT_REFRESH)
    table = cfg.get("refresh") or {}
    for key in out:
        if key not in table:
            continue
        val = table[key]
        if key == "distill":
            if isinstance(val, bool):
                out[key] = val
        elif key == "inbox_dir":
            if isinstance(val, str) and val:
                out[key] = val
        elif key == "limit":
            if isinstance(val, int) and not isinstance(val, bool):
                out[key] = val
    return out


def inbox_dir(vault: Path | None) -> str:
    """Return the inbox directory NAME (single source of truth).

    The inbox is the review-gate quarantine between adapter output
    (`lattice refresh`) and the verified corpus. Its name is config-driven so
    it is never a hardcoded literal scattered across modules. Resolution order:
    `[inbox] dir`, then `[refresh] inbox_dir` (back-compat with the refresh
    table that predates the explicit `[inbox]` block), else the default
    "_inbox". `vault.load_vault` consults this so a renamed inbox stays
    excluded from the scan even without an underscore prefix.
    """
    cfg = load_config(vault)
    inbox_tbl = cfg.get("inbox") or {}
    val = inbox_tbl.get("dir")
    if isinstance(val, str) and val:
        return val
    # back-compat: a user who set [refresh] inbox_dir keeps that name.
    rval = (cfg.get("refresh") or {}).get("inbox_dir")
    if isinstance(rval, str) and rval:
        return rval
    return DEFAULT_REFRESH["inbox_dir"]


def sources(vault: Path | None) -> dict[str, dict[str, Any]]:
    """Return the `[sources]` table: source-name -> options dict.

    NOTHING is enabled unless this table has entries (default-off). Each entry
    must carry an `adapter` name; entries without one are skipped. Adapter
    resolution / validation happens at refresh time (see adapters.build_adapter)
    so an unknown adapter surfaces as a clear CLI error, not a silent drop.
    """
    cfg = load_config(vault)
    table = cfg.get("sources") or {}
    out: dict[str, dict[str, Any]] = {}
    for name, spec in table.items():
        if isinstance(name, str) and isinstance(spec, dict) and spec.get("adapter"):
            out[name] = dict(spec)
    return out


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
