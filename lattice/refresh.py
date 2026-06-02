"""Orchestration for `lattice refresh`.

Explicit, opt-in: this only runs when the user types `lattice refresh`. There
is NO scheduler, daemon, cron, or auto-invocation anywhere. With no `[sources]`
configured it is a no-op. It resolves configured sources to adapters, runs
`discover()`, distills each candidate (reusing the agentic.py Claude path, with
a heuristic fallback that needs no API key), and writes UNCITED stubs into
`_inbox/` — a review area `load_vault` already excludes. Nothing is ever
written into a note body, preserving lattice's core invariant.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from . import templates as T
from .adapters import RawItem, build_adapter, write_watermark
from .agentic import agentic_distill
from .config import refresh_config, sources as _sources


@dataclass
class SourceResult:
    name: str
    adapter: str
    watermark: str | None
    discovered: int
    drafted: int
    paths: list[Path] = field(default_factory=list)


@dataclass
class RefreshResult:
    sources: list[SourceResult] = field(default_factory=list)
    dry_run: bool = False

    @property
    def total_drafts(self) -> int:
        return sum(s.drafted for s in self.sources)


def _slugify(text: str, fallback: str = "item") -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-").lower()[:50]
    return s or fallback


def _heuristic_stub(item: RawItem) -> str:
    """Cost-free, deterministic distillation: the first non-empty line."""
    for line in item.body.splitlines():
        line = line.strip()
        if line:
            return line[:200]
    return item.title[:200]


def _draft_text(item: RawItem, distilled: str | None) -> str:
    """Render the UNCITED inbox stub. Carries a needs-citation marker and no
    citation token, so it can never satisfy the lint citation gate by accident
    and is plainly a review item a human must promote by hand."""
    summary = (distilled or _heuristic_stub(item)).strip()
    return T.INBOX_STUB.format(
        title=item.title,
        source=item.source,
        ref=item.ref or item.id,
        summary=summary,
        raw=item.body.strip(),
    )


def _draft_filename(item: RawItem) -> str:
    """Deterministic per-item filename so re-runs overwrite rather than
    multiply (dup-safety if a run crashes before advancing the watermark)."""
    return f"{item.source}-{item.id}-{_slugify(item.title)}.md"


def run_refresh(
    root: Path,
    selected: list[str] | None = None,
    *,
    distill: bool = True,
    dry_run: bool = False,
    limit: int | None = None,
    since: str | None = None,
    use_cache: bool = True,
) -> RefreshResult:
    """Run configured adapters and draft uncited stubs into `_inbox/`.

    `selected` filters to the named source(s) (None = all configured).
    Raises KeyError (clear message) if a configured source names an unknown
    adapter. Advances each source's watermark ONLY after a successful write,
    and never on `--dry-run`.
    """
    cfg = refresh_config(root)
    src_table = _sources(root)
    cap = limit if limit is not None else int(cfg.get("limit", 50))
    do_distill = distill and bool(cfg.get("distill", True))
    inbox = root / str(cfg.get("inbox_dir", "_inbox"))

    result = RefreshResult(dry_run=dry_run)

    names = list(src_table) if not selected else [s for s in selected if s in src_table]
    for name in names:
        spec = src_table[name]
        adapter_name = spec.get("adapter")
        opts = {k: v for k, v in spec.items() if k != "adapter"}
        adapter = build_adapter(str(adapter_name), name, opts, root)
        if since is not None and hasattr(adapter, "since_override"):
            adapter.since_override = since

        items = adapter.discover()
        discovered = len(items)
        if cap is not None and cap >= 0:
            items = items[:cap]

        drafted_paths: list[Path] = []
        if not dry_run and items:
            inbox.mkdir(parents=True, exist_ok=True)
        for item in items:
            distilled = (
                agentic_distill(item.body, vault=root, use_cache=use_cache)
                if do_distill
                else None
            )
            text = _draft_text(item, distilled)
            target = inbox / _draft_filename(item)
            if not dry_run:
                target.write_text(text)
            drafted_paths.append(target)

        new_wm = getattr(adapter, "watermark", lambda: None)()
        if not dry_run and new_wm:
            write_watermark(root, name, str(adapter_name), new_wm)

        result.sources.append(
            SourceResult(
                name=name,
                adapter=str(adapter_name),
                watermark=since or None,
                discovered=discovered,
                drafted=len(drafted_paths),
                paths=drafted_paths,
            )
        )
    return result
