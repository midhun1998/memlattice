"""Review-gated draft inbox for `lattice inbox` / `lattice promote`.

The inbox dir (default `_inbox`, config-driven via `[inbox] dir`) is the review
gate between adapter output (`lattice refresh`) and the verified corpus. Drafts
sitting there are UNCITED stubs, excluded from `load_vault` (lint/context/link/
stale), so an unused inbox has zero effect on the verified corpus.

`promote` is a deterministic file + template transform — NO network, NO LLM, NO
spend. It rebuilds the standard note skeleton from `templates.TEMPLATE_MD` and
places the draft material as plainly-UNCITED scratch under `## Open questions`,
so a promoted-but-uncited note STILL fails `lattice lint`: promotion can never
launder an uncited claim into the verified body (lattice's core invariant).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from . import templates as T
from .config import inbox_dir as _inbox_dir
from .vault import FRONTMATTER_RE, HEADING_RE


@dataclass
class Draft:
    """A pending inbox draft (pre-promotion, UNCITED)."""

    path: Path
    slug: str
    type: str | None
    title: str
    body: str  # full file text including any frontmatter

    @property
    def token_estimate(self) -> int:
        return len(self.body) // 4


def inbox_path(root: Path) -> Path:
    """Absolute path to the configured inbox dir (may not exist yet)."""
    return root / _inbox_dir(root)


def _parse_draft(path: Path) -> Draft:
    text = path.read_text()
    fm: dict = {}
    body_after_fm = text
    m = FRONTMATTER_RE.match(text)
    if m:
        try:
            fm = yaml.safe_load(m.group(1)) or {}
        except yaml.YAMLError:
            fm = {}
        body_after_fm = text[m.end():]
    # title = first heading text (strip a leading "DRAFT (uncited):" marker),
    # else the first non-empty line, else the slug.
    title = ""
    h = HEADING_RE.search(body_after_fm)
    if h:
        title = h.group(2).strip()
    if not title:
        for line in body_after_fm.splitlines():
            if line.strip():
                title = line.strip()
                break
    title = re.sub(r"^DRAFT \(uncited\):\s*", "", title).strip() or path.stem
    return Draft(
        path=path,
        slug=path.stem,
        type=str(fm["type"]) if isinstance(fm, dict) and fm.get("type") else None,
        title=title,
        body=text,
    )


def list_drafts(root: Path) -> list[Draft]:
    """Pending drafts in the configured inbox dir, sorted by name. Read-only."""
    d = inbox_path(root)
    if not d.exists():
        return []
    return [_parse_draft(p) for p in sorted(d.glob("*.md"))]


def resolve_draft(root: Path, ident: str) -> Draft | None:
    """Resolve a draft identifier (stem or filename) WITHIN the inbox dir.

    Resolution is confined to the inbox: any identifier that would escape it
    (path separators, traversal, absolute paths) is rejected by returning None,
    so `promote` can never move a file from outside the review gate.
    """
    if not ident:
        return None
    # reject anything that is not a bare name (no traversal / no nesting)
    if "/" in ident or "\\" in ident or ident in (".", "..") or Path(ident).is_absolute():
        return None
    name = ident if ident.endswith(".md") else f"{ident}.md"
    if Path(name).name != name:  # defensive: still not a bare name
        return None
    inbox = inbox_path(root)
    target = inbox / name
    # the resolved path must live directly inside the inbox dir
    try:
        if target.resolve().parent != inbox.resolve():
            return None
    except OSError:
        return None
    if not target.exists() or not target.is_file():
        return None
    return _parse_draft(target)


def _draft_material(draft: Draft) -> str:
    """The draft's human-readable content with frontmatter stripped — carried
    into the promoted note as clearly-uncited scratch."""
    m = FRONTMATTER_RE.match(draft.body)
    text = draft.body[m.end():] if m else draft.body
    return text.strip()


def build_promoted_note(
    draft: Draft, kind: str, slug: str, today: str
) -> str:
    """Build a templated note from `TEMPLATE_MD` carrying the draft material as
    UNCITED scratch under `## Open questions`.

    The skeleton is identical to `lattice new` (type/title substituted) so the
    note is shaped like a real note and lint's structural checks apply. The
    draft prose is appended to the Open questions section — which lint EXCLUDES
    from the citation check — so the claims are visibly unverified and a human
    must cite them and move them into the body before `lint` passes. Promotion
    therefore never launders an uncited claim into the verified body.
    """
    body = (
        T.TEMPLATE_MD.format(today=today)
        .replace("type: flow", f"type: {kind}")
        .replace("<Flow name>", draft.title or slug)
    )
    material = _draft_material(draft)
    scratch = (
        "\n"
        "<!-- promoted from inbox draft "
        f"{draft.slug!r} — UNCITED. Verify each claim, add a citation token, "
        "then move it into the body above. Until then this note fails "
        "`lattice lint`. -->\n\n"
        "_Promoted draft material (uncited — needs verification + citations "
        "before moving into the body above):_\n\n"
        f"{material}\n"
    )
    # insert the scratch INTO the Open questions section (before the next
    # heading), so it rides the citation-check exclusion lint already applies
    # to Open questions — it must not silently satisfy the citation gate.
    return _append_to_open_questions(body, scratch)


def _append_to_open_questions(body: str, scratch: str) -> str:
    """Append `scratch` to the end of the `Open questions` section."""
    starts = list(HEADING_RE.finditer(body))
    for i, m in enumerate(starts):
        if re.search(r"open questions", m.group(2), re.IGNORECASE):
            end = starts[i + 1].start() if i + 1 < len(starts) else len(body)
            section = body[m.start():end].rstrip("\n")
            return body[: m.start()] + section + "\n" + scratch + "\n" + body[end:]
    # no Open questions section (shouldn't happen with TEMPLATE_MD) — append.
    return body.rstrip() + "\n\n## Open questions\n" + scratch + "\n"
