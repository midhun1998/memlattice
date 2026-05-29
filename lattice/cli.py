"""lattice CLI."""
from __future__ import annotations

import datetime as dt
import re
import sys
from pathlib import Path

import click

from . import __version__
from . import templates as T
from .vault import (
    CITATION_RE,
    HEADING_RE,
    WIKILINK_RE,
    find_vault,
    load_vault,
    parse_note,
)

PROPER_NOUN_LINE = re.compile(r"\b([A-Z][A-Za-z0-9+]{2,}(?:[- ][A-Z][A-Za-z0-9+]+)*)\b")
ALLOWED_TYPES = {"flow", "component", "api"}
TYPE_DIRS = {"flow": "flows", "component": "components", "api": "api"}


def _today() -> str:
    return dt.date.today().isoformat()


def _err(msg: str) -> None:
    click.echo(click.style(msg, fg="red"), err=True)


def _ok(msg: str) -> None:
    click.echo(click.style(msg, fg="green"))


@click.group()
@click.version_option(__version__)
def main() -> None:
    """lattice — AI agent long-term memory in plain markdown."""


@main.command()
@click.argument("path", type=click.Path(file_okay=False, path_type=Path), default=".")
def init(path: Path) -> None:
    """Scaffold a new vault."""
    path.mkdir(parents=True, exist_ok=True)
    for sub in ("components", "flows", "api", ".lattice/cache", ".lattice/history/full"):
        (path / sub).mkdir(parents=True, exist_ok=True)
    today = _today()
    (path / "_protocol.md").write_text(T.PROTOCOL_MD.format(today=today))
    (path / "_template.md").write_text(T.TEMPLATE_MD.format(today=today))
    (path / "README.md").write_text(T.README_MD.format(name=path.name, path=path.resolve()))
    (path / ".lattice/config.toml").write_text(T.CONFIG_TOML)
    gi = path / ".gitignore"
    if not gi.exists():
        gi.write_text(".lattice/cache/\n")
    _ok(f"vault initialised at {path}")
    click.echo("Add to your CLAUDE.md / AGENTS.md / .cursorrules:")
    click.echo(f'  Long-term memory at {path.resolve()}. Read _protocol.md before editing.')


@main.command()
@click.argument("kind", type=click.Choice(sorted(ALLOWED_TYPES)))
@click.argument("slug")
def new(kind: str, slug: str) -> None:
    """Create a new note from the template."""
    root = find_vault(Path.cwd())
    if root is None:
        _err("not in a lattice vault (no _protocol.md found)")
        sys.exit(2)
    target = root / TYPE_DIRS[kind] / f"{slug}.md"
    if target.exists():
        _err(f"{target} already exists")
        sys.exit(1)
    body = T.TEMPLATE_MD.format(today=_today()).replace(
        "type: flow", f"type: {kind}"
    ).replace("<Flow name>", slug)
    target.write_text(body)
    _ok(f"created {target.relative_to(root)}")


@main.command()
@click.option("--fix", is_flag=True, help="Write back updated Referenced-by sections.")
def link(fix: bool) -> None:
    """Recompute backlinks (## Referenced by sections)."""
    root = find_vault(Path.cwd()) or _abort_no_vault()
    notes = load_vault(root)
    by_slug = {n.slug: n for n in notes}
    backrefs: dict[str, set[str]] = {n.slug: set() for n in notes}
    for n in notes:
        for target in n.links:
            if target in by_slug:
                backrefs[target].add(n.slug)
    changed = 0
    for n in notes:
        wanted = sorted(backrefs[n.slug])
        new_section = "## 8. Referenced by\n" + (
            "\n".join(f"- [[{s}]]" for s in wanted) if wanted else "_none_"
        ) + "\n"
        body, replaced = _replace_section(n.body, "Referenced by", new_section)
        if not replaced:
            body = body.rstrip() + "\n\n" + new_section
            replaced = True
        if body != n.body:
            changed += 1
            if fix:
                _rewrite_body(n.path, body)
    msg = f"{changed} file(s) {'updated' if fix else 'would be updated (run with --fix)'}"
    _ok(msg) if fix or changed == 0 else click.echo(msg)


@main.command()
def lint() -> None:
    """Check citations, structure, token budgets."""
    root = find_vault(Path.cwd()) or _abort_no_vault()
    notes = load_vault(root)
    errors = 0
    for n in notes:
        problems: list[str] = []
        if not n.type:
            problems.append("missing frontmatter `type`")
        if not n.last_verified:
            problems.append("missing frontmatter `last_verified`")
        if "## 7. Open questions" not in n.body and "## Open questions" not in n.body:
            problems.append("missing `## Open questions` section")
        if "Referenced by" not in n.body:
            problems.append("missing `## Referenced by` section (run `lattice link --fix`)")
        # token budget
        toks = n.token_estimate
        if toks > 12000:
            problems.append(f"file too large ({toks} tokens > 12000)")
        elif toks > 6000:
            problems.append(f"file getting large ({toks} tokens > 6000) — consider splitting")
        # citation check (skip Open questions section)
        body_for_check = re.split(r"##\s*(?:7\.\s*)?Open questions", n.body)[0]
        for line in body_for_check.splitlines():
            if line.lstrip().startswith(("|", "#", "-", "*", ">")):
                continue
            if not line.strip():
                continue
            if PROPER_NOUN_LINE.search(line) and not CITATION_RE.search(line):
                # heuristic: only flag lines that look like factual claims
                if any(w in line.lower() for w in (" runs ", " uses ", " calls ", " talks to ", " stores ", " writes to ", " reads from ", " endpoint ")):
                    problems.append(f"un-cited factual line: {line.strip()[:80]}")
        if problems:
            errors += 1
            click.echo(click.style(f"\n{n.path.relative_to(root)}", bold=True))
            for p in problems:
                click.echo(f"  ✗ {p}")
        else:
            click.echo(f"{n.path.relative_to(root)}  ✓ ok")
    if errors:
        _err(f"\n{errors} file(s) with problems")
        sys.exit(1)
    _ok(f"\nall {len(notes)} note(s) clean")


@main.command()
@click.option("--days", default=90, type=int)
def stale(days: int) -> None:
    """List notes whose last_verified is older than --days."""
    root = find_vault(Path.cwd()) or _abort_no_vault()
    today = dt.date.today()
    found = 0
    for n in load_vault(root):
        if not n.last_verified:
            click.echo(f"{n.path.relative_to(root)}   (no last_verified)")
            found += 1
            continue
        try:
            d = dt.date.fromisoformat(n.last_verified)
        except ValueError:
            continue
        age = (today - d).days
        if age > days:
            click.echo(f"{n.path.relative_to(root)}   age={age}d (verified {n.last_verified})")
            found += 1
    if not found:
        _ok(f"nothing older than {days}d")


@main.command()
@click.argument("query")
@click.option("--budget", default=4000, type=int, help="Max output tokens.")
def context(query: str, budget: int) -> None:
    """Return the smallest relevant subgraph for a query."""
    root = find_vault(Path.cwd()) or _abort_no_vault()
    notes = load_vault(root)
    try:
        from rank_bm25 import BM25Okapi
    except ImportError:
        _err("install `rank-bm25` for context retrieval")
        sys.exit(2)
    docs = []
    for n in notes:
        text = n.slug + " " + " ".join(t for _, t in n.headings) + " " + n.body[:2000]
        docs.append(_tokenize(text))
    bm25 = BM25Okapi(docs)
    scores = bm25.get_scores(_tokenize(query))
    ranked = sorted(zip(scores, notes), key=lambda x: -x[0])
    chosen: list[tuple[float, str, int]] = []  # (score, snippet, tokens)
    used = 0
    seen_slugs: set[str] = set()
    for sc, n in ranked:
        if sc <= 0:
            break
        if n.slug in seen_slugs:
            continue
        seen_slugs.add(n.slug)
        snippet = _best_section(n, query)
        toks = len(snippet) // 4
        if used + toks > budget and chosen:
            break
        chosen.append((sc, f"{n.path.relative_to(root)}", toks))
        used += toks
        click.echo(f"--- {n.path.relative_to(root)}  (~{toks} tok, score={sc:.2f}) ---")
        click.echo(snippet.strip())
        # one-hop expansion
        for slug in n.links:
            target = next((m for m in notes if m.slug == slug), None)
            if target and target.slug not in seen_slugs and used < budget:
                seen_slugs.add(target.slug)
                snip = _best_section(target, query)
                stoks = len(snip) // 4
                if used + stoks > budget:
                    continue
                used += stoks
                click.echo(f"--- {target.path.relative_to(root)}  (~{stoks} tok, link-hop) ---")
                click.echo(snip.strip())
    click.echo(f"\n# total: ~{used} / {budget} tokens, {len(chosen)} files")


@main.command()
@click.argument("history_file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--keep-recent", default=3, type=int)
@click.option("--write", is_flag=True, help="Overwrite the input file with the digest.")
def digest(history_file: Path, keep_recent: int, write: bool) -> None:
    """Compress a .CLAUDE.HISTORY file. Sessions older than --keep-recent become 5-line stubs."""
    root = find_vault(Path.cwd())
    archive_dir = (root / ".lattice/history/full") if root else (history_file.parent / ".lattice-history")
    archive_dir.mkdir(parents=True, exist_ok=True)
    text = history_file.read_text()
    sessions = _split_sessions(text)
    if not sessions:
        _err("could not detect session markers (expecting `# Session ...` or `--- DATE ---`)")
        sys.exit(1)
    keep = sessions[-keep_recent:] if keep_recent > 0 else []
    archive = sessions[: -keep_recent] if keep_recent > 0 else sessions
    out_lines = [
        "# .CLAUDE.HISTORY (digested by lattice)",
        f"# kept verbatim: last {len(keep)} session(s)",
        f"# archived: {len(archive)} session(s) at {archive_dir}",
        "",
    ]
    for header, body in archive:
        slug = re.sub(r"[^A-Za-z0-9]+", "-", header).strip("-").lower()[:60] or "session"
        full_path = archive_dir / f"{slug}.md"
        full_path.write_text(f"# {header}\n\n{body}")
        out_lines.append(f"- **{header}** -> [full]({full_path}) — _stub_:")
        out_lines.append(_stub(body))
        out_lines.append("")
    out_lines.append("\n---\n")
    for header, body in keep:
        out_lines.append(f"# {header}\n{body}\n")
    digested = "\n".join(out_lines)
    orig_tok = len(text) // 4
    new_tok = len(digested) // 4
    pct = 100 * (1 - new_tok / max(orig_tok, 1))
    click.echo(f"digest: {orig_tok} -> {new_tok} tokens ({pct:.0f}% reduction)")
    if write:
        backup = history_file.with_suffix(history_file.suffix + ".bak")
        backup.write_text(text)
        history_file.write_text(digested)
        _ok(f"wrote {history_file}; backup at {backup}")
    else:
        click.echo("\n--- preview (first 60 lines) ---")
        click.echo("\n".join(digested.splitlines()[:60]))
        click.echo("\nrun with --write to persist")


# ---------- helpers ----------

def _abort_no_vault() -> Path:
    _err("not in a lattice vault (no _protocol.md found)")
    sys.exit(2)


def _tokenize(s: str) -> list[str]:
    return [w for w in re.findall(r"[A-Za-z0-9_]+", s.lower()) if len(w) > 2]


def _best_section(note, query: str) -> str:
    """Return the section whose heading best matches the query, else first 600 chars."""
    if not note.headings:
        return note.body[:600]
    qtoks = set(_tokenize(query))
    best_h = None
    best_score = 0
    for level, title in note.headings:
        score = len(qtoks & set(_tokenize(title)))
        if score > best_score:
            best_score = score
            best_h = title
    if best_h is None:
        return note.body[:600]
    from .vault import section_text
    sec = section_text(note, best_h) or note.body[:600]
    return sec[:2400]


def _replace_section(body: str, heading_match: str, new_section: str) -> tuple[str, bool]:
    """Replace a section by heading substring; return (new_body, replaced?)."""
    starts = list(HEADING_RE.finditer(body))
    for i, m in enumerate(starts):
        if heading_match.lower() in m.group(2).lower():
            start = m.start()
            end = starts[i + 1].start() if i + 1 < len(starts) else len(body)
            return body[:start] + new_section + body[end:], True
    return body, False


def _rewrite_body(path: Path, new_body: str) -> None:
    text = path.read_text()
    fm_match = re.match(r"^---\n.*?\n---\n", text, re.DOTALL)
    if fm_match:
        path.write_text(text[: fm_match.end()] + new_body)
    else:
        path.write_text(new_body)


SESSION_HEADER_RE = re.compile(r"^(#\s+Session\b.*|---\s*\d{4}-\d{2}-\d{2}.*)$", re.MULTILINE)


def _split_sessions(text: str) -> list[tuple[str, str]]:
    matches = list(SESSION_HEADER_RE.finditer(text))
    if not matches:
        return []
    out = []
    for i, m in enumerate(matches):
        header = m.group(1).lstrip("# ").strip(" -")
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        out.append((header, text[start:end].strip()))
    return out


def _stub(body: str) -> str:
    """Compress a session body to 5 bullets. Cheap heuristic — agent-driven version comes in v0.2."""
    lines = [l.strip() for l in body.splitlines() if l.strip()]
    bullets = [l for l in lines if l.startswith(("-", "*"))][:5]
    if len(bullets) < 5:
        bullets += [f"- {l[:120]}" for l in lines if not l.startswith(("-", "*", "#"))][: 5 - len(bullets)]
    return "\n".join(f"  {b}" for b in bullets[:5]) or "  (empty)"


if __name__ == "__main__":
    main()
