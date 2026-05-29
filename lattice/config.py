"""Vault config loader (.lattice/config.toml)."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

try:
    import tomllib  # py311+
except ImportError:  # pragma: no cover
    import tomli as tomllib  # type: ignore


def load_config(vault: Path) -> dict[str, Any]:
    cfg_path = vault / ".lattice" / "config.toml"
    if not cfg_path.exists():
        return {}
    with cfg_path.open("rb") as f:
        return tomllib.load(f)


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
