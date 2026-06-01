"""lattice CLI."""
from __future__ import annotations

import datetime as dt
import re
import sys
from pathlib import Path

import click

from . import __version__
from . import templates as T
from .config import citation_regex, load_config, note_types, run_hook
from .vault import (
    HEADING_RE,
    find_vault,
    load_vault,
)

PROPER_NOUN_LINE = re.compile(r"\b([A-Z][A-Za-z0-9+]{2,}(?:[- ][A-Z][A-Za-z0-9+]+)*)\b")


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
    """Scaffold a new vault. Idempotent — won't clobber existing files."""
    path.mkdir(parents=True, exist_ok=True)
    for sub in ("components", "flows", "api", ".lattice/cache/queries", ".lattice/history/full"):
        (path / sub).mkdir(parents=True, exist_ok=True)
    today = _today()
    files = {
        "_protocol.md": T.PROTOCOL_MD.format(today=today),
        "_template.md": T.TEMPLATE_MD.format(today=today),
        "README.md": T.README_MD.format(name=path.name, path=path.resolve()),
        ".lattice/config.toml": T.CONFIG_TOML,
    }
    created, kept = [], []
    for rel, content in files.items():
        target = path / rel
        if target.exists():
            kept.append(rel)
        else:
            target.write_text(content)
            created.append(rel)
    gi = path / ".gitignore"
    gi_line = ".lattice/cache/\n"
    if gi.exists():
        if gi_line.strip() not in gi.read_text():
            gi.write_text(gi.read_text().rstrip() + "\n" + gi_line)
    else:
        gi.write_text(gi_line)
    _ok(f"vault initialised at {path}")
    if created:
        click.echo("  created: " + ", ".join(created))
    if kept:
        click.echo("  kept (unchanged): " + ", ".join(kept))
    click.echo("\nAdd to your CLAUDE.md / AGENTS.md / .cursorrules:")
    click.echo(f'  Long-term memory at {path.resolve()}. Read _protocol.md before editing.')
    run_hook(path.resolve(), "init")


@main.command()
@click.argument("kind")
@click.argument("slug")
def new(kind: str, slug: str) -> None:
    """Create a new note from the template.

    KIND is any type configured in `[types]` (defaults: flow, component, api).
    """
    root = find_vault(Path.cwd())
    if root is None:
        _err("not in a lattice vault (no _protocol.md found)")
        sys.exit(2)
    types = note_types(root)
    if kind not in types:
        _err(f"unknown type {kind!r}; configured types: {', '.join(sorted(types))}")
        _err("add it under [types] in .lattice/config.toml to use a new one")
        sys.exit(2)
    target = root / types[kind] / f"{slug}.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        _err(f"{target} already exists")
        sys.exit(1)
    body = T.TEMPLATE_MD.format(today=_today()).replace(
        "type: flow", f"type: {kind}"
    ).replace("<Flow name>", slug)
    target.write_text(body)
    _ok(f"created {target.relative_to(root)}")
    run_hook(root, "new", args=f"{kind}:{slug}")


@main.command()
@click.option("--fix", is_flag=True, help="Write back updated Referenced-by sections.")
def link(fix: bool) -> None:
    """Recompute backlinks (## Referenced by sections)."""
    root = find_vault(Path.cwd()) or _abort_no_vault()
    notes = load_vault(root)
    by_slug = {n.slug: n for n in notes}
    backrefs: dict[str, set[str]] = {n.slug: set() for n in notes}
    for n in notes:
        # Only count GENUINE outgoing links — exclude the auto-maintained
        # `Referenced by` section, else its backlinks get re-counted as
        # outgoing on the next run, oscillating and destroying backrefs.
        for target in _outgoing_links(n.body):
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
    if fix:
        run_hook(root, "link", args=str(changed))


@main.command()
def lint() -> None:
    """Check citations, structure, token budgets."""
    root = find_vault(Path.cwd()) or _abort_no_vault()
    notes = load_vault(root)
    cite_re = citation_regex(root)
    errors = 0
    for n in notes:
        problems: list[str] = []
        if not n.type:
            problems.append("missing frontmatter `type`")
        if not n.last_verified:
            problems.append("missing frontmatter `last_verified`")
        if not re.search(r"##\s*(?:\d+\.\s*)?Open questions", n.body):
            problems.append("missing `## Open questions` section")
        if "Referenced by" not in n.body:
            problems.append("missing `## Referenced by` section (run `lattice link --fix`)")
        # token budget
        toks = n.token_estimate
        if toks > 12000:
            problems.append(f"file too large ({toks} tokens > 12000)")
        elif toks > 6000:
            problems.append(f"file getting large ({toks} tokens > 6000) — consider splitting")
        # citation check: skip ONLY the Open questions section itself, not
        # everything after it (e.g. Referenced by + any later additions).
        body_for_check = re.sub(
            r"##\s*(?:\d+\.\s*)?Open questions.*?(?=^##\s|\Z)",
            "",
            n.body,
            flags=re.DOTALL | re.MULTILINE,
        )
        in_code_fence = False
        for line in body_for_check.splitlines():
            stripped = line.lstrip()
            # track fenced code blocks (``` or ~~~) — everything inside is
            # code/output, never a prose claim. The fence lines toggle state.
            if stripped.startswith(("```", "~~~")):
                in_code_fence = not in_code_fence
                continue
            if in_code_fence:
                continue
            if stripped.startswith(("|", "#", "-", "*", ">", "_", "`")):
                continue
            # skip numbered list items (procedural steps, not standalone claims)
            if re.match(r"\d+\.\s", stripped):
                continue
            if not stripped:
                continue
            # skip caption lines that introduce a block/list (end in ':') —
            # the code block / list below carries the evidence.
            if stripped.rstrip().endswith(":"):
                continue
            # skip wrapped continuation lines (start lowercase / mid-sentence
            # punctuation) — a soft-wrapped sentence carries its citation on
            # another line; flagging the fragment is a false positive.
            if stripped[0].islower() or stripped[0] in "([":
                continue
            if PROPER_NOUN_LINE.search(line) and not cite_re.search(line):
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
    run_hook(root, "lint", args=str(errors))
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
    run_hook(root, "stale", args=str(found))


def _build_context(root: Path, query: str, budget: int) -> tuple[str, int, int]:
    """Return (manifest_text, tokens_used, files_count)."""
    notes = load_vault(root)
    try:
        from rank_bm25 import BM25Okapi
    except ImportError:
        raise click.ClickException("install `rank-bm25` for context retrieval")
    docs = []
    for n in notes:
        text = n.slug + " " + " ".join(t for _, t in n.headings) + " " + n.body[:2000]
        docs.append(_tokenize(text))
    if not docs:
        return f"# lattice context for: {query!r}\n# (vault empty)\n", 0, 0
    bm25 = BM25Okapi(docs)
    scores = bm25.get_scores(_tokenize(query))
    ranked = sorted(zip(scores, notes), key=lambda x: -x[0])
    out: list[str] = [f"# lattice context for: {query!r}", ""]
    used = 0
    files = 0
    seen: set[str] = set()
    for sc, n in ranked:
        if sc <= 0:
            break
        if n.slug in seen:
            continue
        seen.add(n.slug)
        snippet = _best_section(n, query)
        toks = len(snippet) // 4
        if used + toks > budget and files:
            break
        used += toks
        files += 1
        out.append(f"--- {n.path.relative_to(root)}  (~{toks} tok, score={sc:.2f}) ---")
        out.append(snippet.strip())
        out.append("")
        for slug in n.links:
            target = next((m for m in notes if m.slug == slug), None)
            if target and target.slug not in seen and used < budget:
                seen.add(target.slug)
                snip = _best_section(target, query)
                stoks = len(snip) // 4
                if used + stoks > budget:
                    continue
                used += stoks
                files += 1
                out.append(f"--- {target.path.relative_to(root)}  (~{stoks} tok, link-hop) ---")
                out.append(snip.strip())
                out.append("")
    out.append(f"# total: ~{used} / {budget} tokens, {files} files")
    return "\n".join(out), used, files


@main.command()
@click.argument("query")
@click.option("--budget", default=4000, type=int, help="Max output tokens.")
@click.option("--out", type=click.Path(dir_okay=False, path_type=Path), help="Write manifest to file (also passed to post-context hook).")
def context(query: str, budget: int, out: Path | None) -> None:
    """Return the smallest relevant subgraph for a query."""
    root = find_vault(Path.cwd()) or _abort_no_vault()
    text, used, files = _build_context(root, query, budget)
    click.echo(text)
    if out:
        out.write_text(text)
    run_hook(root, "context", args=query, output_file=out)


@main.command()
@click.option("--build", is_flag=True, help="Render all queries in [cache.queries] to .lattice/cache/queries/.")
@click.option("--budget", default=4000, type=int)
def cache(build: bool, budget: int) -> None:
    """Offline pre-rendered context manifests. Read these with no Python required."""
    root = find_vault(Path.cwd()) or _abort_no_vault()
    cache_dir = root / ".lattice" / "cache" / "queries"
    if not build:
        # list existing
        if not cache_dir.exists():
            click.echo("(no cache yet — run `lattice cache --build`)")
            return
        for f in sorted(cache_dir.glob("*.md")):
            size = f.stat().st_size
            click.echo(f"{f.relative_to(root)}   {size}B")
        return
    cfg = load_config(root)
    queries: dict = (cfg.get("cache") or {}).get("queries") or {}
    if not queries:
        _err("no [cache.queries] entries in config.toml")
        sys.exit(1)
    cache_dir.mkdir(parents=True, exist_ok=True)
    index_lines = ["# lattice offline cache", "", "| slug | query | tokens | files |", "|---|---|---|---|"]
    for slug, query in queries.items():
        text, used, files = _build_context(root, query, budget)
        path = cache_dir / f"{slug}.md"
        path.write_text(text)
        index_lines.append(f"| [{slug}]({path.relative_to(root)}) | {query} | {used} | {files} |")
        click.echo(f"  {slug:30s} {used:5d}t  {files}f  -> {path.relative_to(root)}")
    (cache_dir / "INDEX.md").write_text("\n".join(index_lines) + "\n")
    _ok(f"\nbuilt {len(queries)} cached manifest(s); index at {cache_dir.relative_to(root)}/INDEX.md")
    run_hook(root, "cache", args=f"build:{len(queries)}")


@main.command()
@click.argument("history_file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--keep-recent", default=3, type=int)
@click.option("--write", is_flag=True, help="Overwrite the input file with the digest.")
@click.option("--no-cache", is_flag=True, help="Bypass agentic stub cache; force re-call.")
def digest(history_file: Path, keep_recent: int, write: bool, no_cache: bool) -> None:
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
        out_lines.append(_stub(body, vault=root, use_cache=not no_cache))
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
        if root:
            run_hook(root, "digest", args=str(history_file), output_file=history_file)
    else:
        click.echo("\n--- preview (first 60 lines) ---")
        click.echo("\n".join(digested.splitlines()[:60]))
        click.echo("\nrun with --write to persist")


# ---------- helpers ----------

def _abort_no_vault() -> Path:
    _err("not in a lattice vault (no _protocol.md found)")
    sys.exit(2)


def _outgoing_links(body: str) -> list[str]:
    """Wikilink targets in a note's body, EXCLUDING the auto-maintained
    `Referenced by` section (those are inbound backrefs, not outbound links).
    """
    from .vault import WIKILINK_RE
    # drop everything from the `Referenced by` heading to the next heading/EOF
    trimmed = re.sub(
        r"##\s*(?:\d+\.\s*)?Referenced by.*?(?=^##\s|\Z)",
        "",
        body,
        flags=re.DOTALL | re.MULTILINE,
    )
    return list({m.group(1).strip() for m in WIKILINK_RE.finditer(trimmed)})


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


def _stub(body: str, vault: Path | None = None, use_cache: bool = True) -> str:
    """Compress a session body to 5 bullets.

    Tries Claude API first (set ANTHROPIC_API_KEY); falls back to a cheap
    heuristic when the API is unavailable.
    """
    from .agentic import agentic_stub
    out = agentic_stub(body, vault=vault, use_cache=use_cache)
    if out:
        return out
    lines = [l.strip() for l in body.splitlines() if l.strip()]
    bullets = [l for l in lines if l.startswith(("-", "*"))][:5]
    if len(bullets) < 5:
        bullets += [f"- {l[:120]}" for l in lines if not l.startswith(("-", "*", "#"))][: 5 - len(bullets)]
    return "\n".join(f"  {b}" for b in bullets[:5]) or "  (empty)"


if __name__ == "__main__":
    main()
