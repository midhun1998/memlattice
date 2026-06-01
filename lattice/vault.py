"""Vault discovery, frontmatter parsing, link graph."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .config import citation_regex as _citation_regex

FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)
WIKILINK_RE = re.compile(r"\[\[([^\]\|#]+)(?:#[^\]\|]+)?(?:\|[^\]]+)?\]\]")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)
# Backward-compat: a citation matcher over the vendor-neutral DEFAULT schemes.
# Vault-aware checks should use config.citation_regex(vault) so user-declared
# `[citations] extra` schemes are honored; this constant covers defaults only.
CITATION_RE = _citation_regex(None)


@dataclass
class Note:
    path: Path
    slug: str
    type: str | None
    last_verified: str | None
    related: list[str]
    body: str
    headings: list[tuple[int, str]] = field(default_factory=list)
    links: list[str] = field(default_factory=list)

    @property
    def token_estimate(self) -> int:
        return len(self.body) // 4


def find_vault(start: Path) -> Path | None:
    cur = start.resolve()
    for p in [cur, *cur.parents]:
        if (p / "_protocol.md").exists() or (p / ".lattice").exists():
            return p
    return None


def parse_note(path: Path) -> Note:
    text = path.read_text()
    fm: dict = {}
    body = text
    m = FRONTMATTER_RE.match(text)
    if m:
        try:
            fm = yaml.safe_load(m.group(1)) or {}
        except yaml.YAMLError:
            fm = {}
        body = text[m.end():]
    headings = [(len(h.group(1)), h.group(2)) for h in HEADING_RE.finditer(body)]
    links = list({m.group(1).strip() for m in WIKILINK_RE.finditer(body)})
    return Note(
        path=path,
        slug=path.stem,
        type=fm.get("type"),
        last_verified=str(fm.get("last_verified")) if fm.get("last_verified") else None,
        related=fm.get("related") or [],
        body=body,
        headings=headings,
        links=links,
    )


# Directories never scanned for notes (machine state, not knowledge).
_SKIP_DIRS = {".lattice", ".git", ".obsidian", "node_modules"}


def load_vault(root: Path) -> list[Note]:
    """Load every markdown note in any non-hidden subdirectory.

    Auto-discovers category dirs (components/, flows/, api/, queries/,
    ideas/, ...) so adding a new category needs no code change. Files and
    dirs starting with `_` or `.` are skipped, as are _SKIP_DIRS.
    """
    notes = []
    for d in sorted(p for p in root.iterdir() if p.is_dir()):
        if d.name in _SKIP_DIRS or d.name.startswith((".", "_")):
            continue
        for p in sorted(d.glob("*.md")):
            if p.name.startswith("_"):
                continue
            notes.append(parse_note(p))
    return notes


def section_text(note: Note, heading: str) -> str:
    """Return the raw text of a section by heading match (substring, case-insensitive)."""
    h_lower = heading.lower()
    starts = []
    for m in HEADING_RE.finditer(note.body):
        starts.append((m.start(), m.end(), len(m.group(1)), m.group(2)))
    for i, (s, _e, _lvl, title) in enumerate(starts):
        if h_lower in title.lower():
            end = starts[i + 1][0] if i + 1 < len(starts) else len(note.body)
            return note.body[s:end]
    return ""
