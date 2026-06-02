"""Pluggable source adapters for `lattice refresh`.

An adapter is any object exposing `discover() -> list[RawItem]`. Adapters are
declared per-instance in `[sources]` of `.lattice/config.toml` and resolved by
*name* against a registry. The registry merges:

  1. a built-in registry (always includes the network-free `git` adapter), and
  2. third-party adapters advertised under the `lattice.adapters` entry-point
     group (stdlib `importlib.metadata`), so proprietary/internal adapters live
     OUTSIDE this OSS tree as separate packages that bring their own deps.

The built-in `git` adapter is universal: no auth, no network. It shells out to
the local `git` binary (stdlib `subprocess`, same posture as config.run_hook)
to read commits since a stored watermark under `.lattice/cache/refresh/`.

Public contract (third parties depend on it — widen, never narrow):
  RawItem(id, title, body, source, suggested_citation: str | None, ref)
  Adapter.discover() -> list[RawItem]
"""
from __future__ import annotations

import datetime as dt
import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol, runtime_checkable


@dataclass
class RawItem:
    """A candidate discovered by an adapter — pre-distillation, UNCITED.

    Fields are pinned conservatively as a stable public contract:
      id     stable identifier within the source (e.g. a commit sha)
      title  one-line human summary (e.g. a commit subject)
      body   the raw text (e.g. commit subject + body)
      source the configured source name this item came from
      suggested_citation a citation token the adapter believes applies, or None
                         (the git adapter leaves this None — drafts stay uncited)
      ref    opaque machine reference back to the origin (e.g. the full sha)
    """

    id: str
    title: str
    body: str
    source: str
    suggested_citation: str | None = None
    ref: str = ""


@runtime_checkable
class Adapter(Protocol):
    """Minimal adapter contract. Anything with `discover()` qualifies."""

    def discover(self) -> list[RawItem]:  # pragma: no cover - protocol
        ...


# Factory signature: (source_name, options_dict, vault_root) -> Adapter.
AdapterFactory = Callable[[str, dict[str, Any], Path], "Adapter"]

ENTRY_POINT_GROUP = "lattice.adapters"


# ---------- watermark I/O (under already-gitignored .lattice/cache/) ----------

def _watermark_path(vault: Path, source: str) -> Path:
    return vault / ".lattice" / "cache" / "refresh" / f"{source}.json"


def read_watermark(vault: Path, source: str) -> str | None:
    p = _watermark_path(vault, source)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text())
    except (ValueError, OSError):
        return None
    wm = data.get("watermark")
    return wm if isinstance(wm, str) and wm else None


def write_watermark(vault: Path, source: str, adapter: str, watermark: str) -> None:
    p = _watermark_path(vault, source)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(
            {
                "adapter": adapter,
                "watermark": watermark,
                "updated": dt.datetime.now(dt.timezone.utc).isoformat(),
            },
            indent=2,
        )
    )


# ---------- built-in git adapter (local-only, no network, no auth) ----------

# NUL byte delimits fields, NUL-NUL between records via `-z`. Stable across
# git versions/locales (we also pin LC_ALL=C), unlike scraping human output.
_GIT_FORMAT = "%H%x00%s%x00%b"
# First-run safety: with no watermark, bound to this many most-recent commits
# instead of the whole history. --limit further caps the drafted subset.
DEFAULT_FIRST_RUN_WINDOW = 50


class GitAdapter:
    """Yield candidate items for new commits since a stored watermark.

    Universal and side-effect-free at discovery time: it only runs `git log`
    in the configured repo path. No network, no token, no auth. Honors an
    optional `branch` and a `paths` path-filter from the source options.
    """

    def __init__(self, source: str, opts: dict[str, Any], vault: Path):
        self.source = source
        self.vault = vault
        self.repo = (vault / str(opts.get("path", "."))).resolve()
        self.branch = opts.get("branch") or None
        self.paths = [str(p) for p in (opts.get("paths") or []) if isinstance(p, str)]
        # Per-run watermark override (set by the orchestrator from --since);
        # falls back to the stored watermark when None.
        self.since_override: str | None = None
        self.first_run_window = int(opts.get("first_run_window", DEFAULT_FIRST_RUN_WINDOW))
        # Captured at discover() time so the orchestrator can advance only after
        # a successful write.
        self.head: str | None = None

    def _run_git(self, *args: str) -> str:
        env = {
            "LC_ALL": "C",
            "GIT_TERMINAL_PROMPT": "0",  # never block on credential prompts
            "PATH": "/usr/bin:/bin:/usr/local/bin",
        }
        proc = subprocess.run(
            ["git", "-C", str(self.repo), *args],
            env=env,
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.strip() or f"git {' '.join(args)} failed")
        return proc.stdout

    def _head(self) -> str:
        ref = self.branch or "HEAD"
        return self._run_git("rev-parse", ref).strip()

    def discover(self) -> list[RawItem]:
        try:
            self.head = self._head()
        except RuntimeError:
            # not a git repo / detached / empty — degrade to no candidates
            self.head = None
            return []

        watermark = self.since_override or read_watermark(self.vault, self.source)

        log_args = ["log", "-z", f"--format={_GIT_FORMAT}"]
        target = self.branch or "HEAD"
        if watermark:
            rev = f"{watermark}..{target}"
        else:
            # first-ever run: bound to a window, never the whole history
            log_args += ["-n", str(self.first_run_window)]
            rev = target
        log_args.append(rev)
        if self.paths:
            log_args.append("--")
            log_args.extend(self.paths)

        try:
            out = self._run_git(*log_args)
        except RuntimeError:
            # bad watermark range (e.g. rewritten history) — fall back to window
            out = self._run_git(
                "log", "-z", f"--format={_GIT_FORMAT}", "-n", str(self.first_run_window), target,
                *(["--", *self.paths] if self.paths else []),
            )

        items: list[RawItem] = []
        for record in out.split("\x00\x00"):
            record = record.strip("\n")
            if not record:
                continue
            parts = record.split("\x00")
            if len(parts) < 2:
                continue
            sha, subject = parts[0].strip(), parts[1].strip()
            body = parts[2].strip() if len(parts) > 2 else ""
            if not sha:
                continue
            full = subject if not body else f"{subject}\n\n{body}"
            items.append(
                RawItem(
                    id=sha[:12],
                    title=subject,
                    body=full,
                    source=self.source,
                    suggested_citation=None,  # uncited by construction
                    ref=sha,
                )
            )
        return items

    def watermark(self) -> str | None:
        """The value to persist after a successful write (current HEAD)."""
        return self.head


# ---------- registry / discovery ----------

# Built-in registry, keyed by adapter name. The built-in `git` adapter is
# ALWAYS present regardless of install/entry-point state. Never hardcode a
# vendor/tool here beyond the universal `git` primitive.
_BUILTIN: dict[str, AdapterFactory] = {
    "git": GitAdapter,
}


def _entry_point_adapters() -> dict[str, AdapterFactory]:
    """Third-party adapters advertised under the `lattice.adapters` group.

    Each broken/slow entry point is isolated: a load failure is a warning, not
    an abort (mirrors run_hook's failure-as-warning posture). Installing a
    third-party adapter runs its code — documented as a trust boundary.
    """
    found: dict[str, AdapterFactory] = {}
    try:
        import importlib.metadata as md
    except ImportError:  # pragma: no cover
        return found
    try:
        eps = md.entry_points()
        try:
            selected = eps.select(group=ENTRY_POINT_GROUP)
        except AttributeError:  # pragma: no cover - py<3.10 mapping API
            selected = eps.get(ENTRY_POINT_GROUP, [])
    except Exception:  # pragma: no cover - defensive
        return found
    for ep in selected:
        try:
            found[ep.name] = ep.load()
        except Exception as e:  # noqa: BLE001 - never let a bad adapter abort
            print(
                f"[lattice] adapter {ep.name!r} failed to load: {e}; skipping",
                file=sys.stderr,
            )
    return found


def available_adapters() -> dict[str, AdapterFactory]:
    """All resolvable adapter factories by name (built-ins + entry points).

    Built-ins win on name collision so a third party cannot shadow the
    network-free `git` adapter.
    """
    out: dict[str, AdapterFactory] = {}
    out.update(_entry_point_adapters())
    out.update(_BUILTIN)
    return out


def build_adapter(name: str, source: str, opts: dict[str, Any], vault: Path) -> "Adapter":
    """Instantiate the adapter named `name` for source `source`.

    Raises KeyError with a clear message when the adapter is unknown.
    """
    registry = available_adapters()
    if name not in registry:
        known = ", ".join(sorted(registry))
        raise KeyError(f"unknown adapter {name!r}; available: {known}")
    return registry[name](source, opts, vault)
