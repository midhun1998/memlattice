"""lattice CLI."""
from __future__ import annotations

import datetime as dt
import json
import re
import sys
from pathlib import Path

import click

from . import __version__
from . import templates as T
from . import outcomes as _outcomes
from .config import budgets, citation_regex, context_config, learn_config, load_config, note_types, run_hook, sources
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
@click.pass_context
def main(ctx: click.Context) -> None:
    """lattice — AI agent long-term memory in plain markdown."""
    # Best-effort local usage log: one row per real subcommand invocation.
    # Never logs `stats` itself (avoids self-inflation) or when outside a vault.
    sub = ctx.invoked_subcommand
    # `stats` is excluded (avoid self-inflation); `context` self-logs with token
    # detail in its own handler, so skip it here to avoid a double row.
    if sub and sub not in ("stats", "context"):
        try:
            from . import usage
            root = find_vault(Path.cwd())
            if root is not None:
                usage.record(root, sub)
        except Exception:
            pass


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
    # Ignore machine state + review scratch: the local caches/ledgers under
    # .lattice/cache/ and the uncited `_inbox/` drafts (never belong in a repo).
    gi = path / ".gitignore"
    want = [".lattice/cache/", "_inbox/"]
    existing = gi.read_text() if gi.exists() else ""
    have = set(existing.splitlines())
    missing = [ln for ln in want if ln not in have]
    if missing:
        body = (existing.rstrip() + "\n") if existing.strip() else ""
        gi.write_text(body + "\n".join(missing) + "\n")
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
    b = budgets(root)
    errors = 0
    for n in notes:
        problems = _lint_note(n, cite_re, b["file_warn"], b["file_max"])
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


@main.command()
@click.option("--days", default=90, type=int, help="Stale threshold (same as `lattice stale`).")
@click.option("--strict", is_flag=True, help="Treat warn-level breaches and orphans as hard problems too.")
def doctor(days: int, strict: bool) -> None:
    """Read-only vault health summary. Exits non-zero on hard problems.

    Hard problems (always exit 1): lint errors, files over the max token
    budget. Staleness and orphans are advisory; --strict escalates orphans
    and warn-level token breaches to hard problems too. No network, no writes.
    """
    root = find_vault(Path.cwd()) or _abort_no_vault()
    notes = load_vault(root)
    cite_re = citation_regex(root)
    b = budgets(root)
    file_warn, file_max = b["file_warn"], b["file_max"]
    today = dt.date.today()

    total_tokens = sum(n.token_estimate for n in notes)

    # stale: missing last_verified OR age > days (counted ONCE per note)
    stale = 0
    for n in notes:
        if not n.last_verified:
            stale += 1
            continue
        try:
            d = dt.date.fromisoformat(n.last_verified)
        except ValueError:
            continue
        if (today - d).days > days:
            stale += 1

    orphans = _orphans(notes)

    over_max = [n for n in notes if n.token_estimate > file_max]
    over_warn = [n for n in notes if file_warn < n.token_estimate <= file_max]

    lint_problems = {n.slug: _lint_note(n, cite_re, file_warn, file_max) for n in notes}
    lint_bad = sum(1 for p in lint_problems.values() if p)
    lint_ok = len(notes) - lint_bad

    def _orphan_paths() -> str:
        if not orphans:
            return ""
        names = ", ".join(str(n.path.relative_to(root)) for n in orphans)
        return f"   ({names})"

    def _row(label: str, value: str) -> str:
        return f"  {label:<17} {value}"

    click.echo(f"lattice doctor — {root}")
    click.echo(_row("notes:", str(len(notes))))
    click.echo(_row("total tokens:", f"~{total_tokens}"))
    click.echo(_row(f"stale (>{days}d):", str(stale)))
    click.echo(_row("orphans:", f"{len(orphans)}{_orphan_paths()}"))
    click.echo(
        _row(
            "over budget:",
            f"{len(over_max)} over max ({file_max}), {len(over_warn)} over warn ({file_warn})",
        )
    )
    click.echo(_row("lint:", f"{lint_ok} ok, {lint_bad} with problems"))

    # hard vs. advisory problem accounting
    hard: list[str] = []
    if lint_bad:
        hard.append(f"{lint_bad} lint failure(s)")
    if over_max:
        hard.append(f"{len(over_max)} file(s) over max")
    if strict:
        if over_warn:
            hard.append(f"{len(over_warn)} file(s) over warn")
        if orphans:
            hard.append(f"{len(orphans)} orphan(s)")

    if hard:
        summary = "PROBLEMS: " + ", ".join(hard)
        _err(f"\n{summary}  -> exit 1")
        run_hook(root, "doctor", args=summary)
        sys.exit(1)
    _ok("\nall checks passed")
    run_hook(root, "doctor", args="ok")


@main.command()
@click.argument("paths", nargs=-1, type=click.Path())
@click.option("--fetch", is_flag=True, help="Resolve doc:/url: citations over the network (off by default).")
@click.option("--entail", "do_entail", is_flag=True, help="Layer 2: LLM-judge whether each present source SUPPORTS the claim (budget-gated; off at $0).")
@click.option("--changed", is_flag=True, help="Only scan memory files changed vs --base (for CI on a PR).")
@click.option("--base", default="HEAD", help="Git base ref for --changed (default HEAD).")
@click.option("--format", "fmt", type=click.Choice(["text", "json", "sarif"]), default="text", help="Output format. json/sarif emit a machine-readable audit artifact for CI.")
def verify(paths: tuple[str, ...], fetch: bool, do_entail: bool, changed: bool, base: str, fmt: str) -> None:
    """Check that cited sources back their claims (the verification gate).

    Layer 1 (always): file:/commit: checked on disk/in-repo; conv:/chat: are
    human-attested; doc:/url:/pr: unfetched unless --fetch. Layer 2 (--entail):
    an LLM judges whether each present source SUPPORTS the claim — gated by the
    `[budget]` breaker, so it never spends at the default $0 ceiling.

    CI: `--changed --base <ref>` scopes to changed files; `--format json|sarif`
    emits an audit artifact. Exits non-zero on missing/contradicted/unsupported.
    """
    from . import verify as _verify
    root = find_vault(Path.cwd()) or _abort_no_vault()
    cite_re = citation_regex(root)
    notes = load_vault(root)
    if changed:
        changed_set = _changed_files(root, base)
        notes = [n for n in notes if str(n.path.resolve()) in changed_set]

    from . import budget as _budget
    from .config import budget_config, budget_reset
    bcfg = budget_config(root)
    reset = budget_reset(root)
    ceiling = bcfg["max_usd_per_day"]
    est = bcfg["estimated_usd_per_digest"]

    def entail_ok() -> bool:
        return do_entail and _budget.check(root, est_cost=est, max_usd=ceiling, reset=reset).allow

    report = []  # structured per-note result, rendered per --format
    for n in notes:
        tokens = _verify.citations_in(n.body, cite_re)
        if not tokens:
            continue
        cites = []  # {token, status, detail, line}
        resolved = {}
        line_of = _citation_line_map(n.body, cite_re)
        for tok in tokens:
            st = _verify.resolve_citation(tok, root=root, fetch=fetch)
            resolved[tok] = st
            cites.append({"token": tok, "status": st.status, "detail": st.detail,
                          "line": line_of.get(tok, 1)})
        if do_entail:
            from . import agentic
            for claim, toks in _verify.lines_with_citations(n.body, cite_re):
                for tok in toks:
                    st = resolved.get(tok)
                    if not st or st.status not in ("present", "fetched"):
                        continue
                    src = _verify.source_text(tok, root)
                    if src is None or not entail_ok():
                        continue
                    verdict = agentic.entail(claim, src)
                    if verdict in ("supported", "contradicted", "unsupported"):
                        _budget.record(root, est, reset=reset)
                    cites.append({"token": tok, "status": verdict,
                                  "detail": "claim not backed by source" if _verify.is_fail(verdict) else "",
                                  "line": line_of.get(tok, 1)})
        note_status = _verify.worst([c["status"] for c in cites])
        report.append({"path": str(n.path.relative_to(root)), "status": note_status,
                       "citations": cites})

    failed = sum(1 for r in report if _verify.is_fail(r["status"]))
    summary = {"notes": len(report), "failed": failed,
               "warned": sum(1 for r in report if r["status"] in ("drifted", "unresolvable"))}

    if fmt == "json":
        click.echo(json.dumps({"summary": summary, "notes": report}, indent=2))
    elif fmt == "sarif":
        click.echo(json.dumps(_verify.to_sarif(report), indent=2))
    else:
        for r in report:
            s = r["status"]
            if _verify.is_fail(s):
                click.echo(click.style(f"{r['path']}  ✗ {s}", fg="red"))
            elif s in ("drifted", "unresolvable"):
                click.echo(click.style(f"{r['path']}  ⚠ {s}", fg="yellow"))
            else:
                click.echo(f"{r['path']}  ✓ {s}")
            for c in r["citations"]:
                if _verify.is_fail(c["status"]) or c["status"] in ("drifted", "unresolvable"):
                    click.echo(f"    {c['status']}: [{c['token']}]" + (f" — {c['detail']}" if c["detail"] else ""))
        if failed:
            _err(f"\n{failed} note(s) with unresolved citations")
    run_hook(root, "verify", args=str(failed))
    if failed:
        sys.exit(1)
    if fmt == "text":
        _ok(f"\nall {len(report)} note(s) verified" + (" (Layer 1+2)" if do_entail else " (Layer 1)"))


def _changed_files(root: Path, base: str) -> set[str]:
    """Absolute paths of files changed vs `base` (committed diff + working tree)."""
    out: set[str] = set()
    try:
        import subprocess
        for args in (["diff", "--name-only", base], ["diff", "--name-only"], ["ls-files", "--others", "--exclude-standard"]):
            r = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True)
            if r.returncode == 0:
                for line in r.stdout.splitlines():
                    if line.strip():
                        out.add(str((root / line.strip()).resolve()))
    except (OSError, ImportError):
        pass
    return out


def _citation_line_map(body: str, cite_re) -> dict[str, int]:
    """First 1-based line number each citation token appears on."""
    m: dict[str, int] = {}
    for i, line in enumerate(body.splitlines(), start=1):
        for mt in cite_re.finditer(line):
            tok = mt.group(0)[1:-1]
            m.setdefault(tok, i)
    return m


@main.command()
@click.argument("target", type=click.Choice(["claude-code", "print"]))
@click.option("--yes", is_flag=True, help="Write without prompting.")
def install(target: str, yes: bool) -> None:
    """Wire lattice's MCP server into an agent so it's used automatically.

    `claude-code` writes a project `.mcp.json` advertising the `lattice` server
    (run via `lattice-mcp`), so the agent can call lattice_context/lint/verify
    natively — no "remember to run the CLI". `print` just emits the snippet.
    Idempotent; needs the [mcp] extra installed to actually run the server.
    """
    root = find_vault(Path.cwd()) or _abort_no_vault()
    server_entry = {
        "lattice": {
            "command": "lattice-mcp",
            "args": [],
            "env": {},
        }
    }
    snippet = {"mcpServers": server_entry}
    if target == "print":
        click.echo(json.dumps(snippet, indent=2))
        click.echo("\n# add the above to .mcp.json; install the server with: pip install \"memlattice[mcp]\"", err=True)
        return
    # claude-code: merge into (or create) .mcp.json at the vault root
    mcp_path = root / ".mcp.json"
    existing = {}
    if mcp_path.exists():
        try:
            existing = json.loads(mcp_path.read_text())
        except json.JSONDecodeError:
            existing = {}
    servers = existing.setdefault("mcpServers", {})
    if servers.get("lattice") == server_entry["lattice"]:
        _ok(f".mcp.json already wired ({mcp_path.relative_to(root)})")
        return
    if not yes and mcp_path.exists():
        click.confirm(f"merge a 'lattice' MCP server into {mcp_path.relative_to(root)}?", abort=True)
    servers["lattice"] = server_entry["lattice"]
    mcp_path.write_text(json.dumps(existing, indent=2) + "\n")
    _ok(f"wired lattice MCP server into {mcp_path.relative_to(root)}")
    click.echo("install the server runtime with: pip install \"memlattice[mcp]\", then restart your agent.")
    run_hook(root, "install", args=target)


def _resolve_ranker(root: Path, requested: str) -> tuple[str, str]:
    """Decide which ranker actually runs and why.

    Returns (effective, reason) where effective is "embeddings" or "bm25" and
    reason is a short human note for `--explain-ranker`. `requested` is one of
    auto|bm25|embeddings (the CLI default is auto). The default-off posture:
      - bm25       -> always the legacy path (regression-safe).
      - auto       -> embeddings iff the extra imports AND `[context] ranker`
                      is not "bm25"; else bm25.
      - embeddings -> force; if the backend is unavailable, degrade to bm25
                      with a one-line notice (never hard-errors).
    The default-model literal is owned by embeddings.py; we only surface a
    config-resolved id (which may be empty -> "default") for the note.
    """
    from . import embeddings as _emb

    ccfg = context_config(root)
    cfg_ranker = ccfg.get("ranker", "auto")
    model_disp = ccfg.get("embedding_model") or "default"
    available = _emb.backend_available()

    if requested == "bm25":
        return "bm25", "forced bm25"
    if requested == "embeddings":
        if available:
            return "embeddings", f"forced embeddings (model={model_disp})"
        return "bm25", "embeddings forced but extra not installed — falling back to bm25"
    # auto
    if cfg_ranker == "bm25":
        return "bm25", "bm25 ([context] ranker = bm25)"
    if available:
        return "embeddings", f"embeddings (model={model_disp})"
    return "bm25", "bm25 (embeddings extra not installed)"


def _build_context(
    root: Path,
    query: str,
    budget: int,
    learn: bool = True,
    ranker: str = "auto",
) -> tuple[str, int, int, str]:
    """Return (manifest_text, tokens_used, files_count, ranker_reason).

    Ranking is BM25 by default. When the optional embeddings backend is chosen
    (see `_resolve_ranker`) and succeeds, per-note BM25 scores are REPLACED by
    cosine similarity over the SAME text BM25 indexes (slug + headings +
    body[:2000]); if the backend returns None (missing extra, model failure) we
    silently keep the BM25 scores. The manifest is byte-identical to the legacy
    path for the bm25 / auto-without-extra cases — only the numeric value in the
    unchanged `score=%.2f` column changes (cosine vs BM25) when embeddings run.

    When `learn` and `[learn].enabled`, a small, conservative, recency-decayed
    multiplier from `.lattice/cache/outcomes.jsonl` scales each note's score
    BEFORE ranking. It only scales notes that already matched (score > 0), so it
    never resurrects a zero-score note — the relevance gate is preserved.
    """
    notes = load_vault(root)
    try:
        from rank_bm25 import BM25Okapi
    except ImportError:
        raise click.ClickException("install `rank-bm25` for context retrieval")
    docs = []
    doc_texts = []
    for n in notes:
        text = n.slug + " " + " ".join(t for _, t in n.headings) + " " + n.body[:2000]
        doc_texts.append(text)
        docs.append(_tokenize(text))
    effective, reason = _resolve_ranker(root, ranker)
    if not docs:
        return f"# lattice context for: {query!r}\n# (vault empty)\n", 0, 0, reason
    bm25 = BM25Okapi(docs)
    scores = list(bm25.get_scores(_tokenize(query)))
    if effective == "embeddings":
        from . import embeddings as _emb

        ccfg = context_config(root)
        sims = _emb.embedding_scores(
            query,
            doc_texts,
            ccfg.get("embedding_model") or None,
            vault=root,
            use_cache=bool(ccfg.get("embedding_cache", True)),
        )
        if sims is not None and len(sims) == len(notes):
            scores = sims
        else:
            # backend unavailable / failed mid-run -> silent BM25 fallback
            effective = "bm25"
            reason = reason + " (backend unavailable — fell back to bm25)" \
                if "fall" not in reason else reason
    lcfg = learn_config(root)
    if learn and lcfg.get("enabled", True):
        mult = _outcomes.slug_multipliers(root, lcfg)
        scores = [s * mult.get(n.slug, 1.0) for s, n in zip(scores, notes)]
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
    return "\n".join(out), used, files, reason


@main.command()
@click.argument("query")
@click.option("--budget", default=4000, type=int, help="Max output tokens.")
@click.option("--out", type=click.Path(dir_okay=False, path_type=Path), help="Write manifest to file (also passed to post-context hook).")
@click.option("--no-learn", is_flag=True, help="Disable the outcome/recency rank boost (use pure BM25).")
@click.option(
    "--ranker",
    type=click.Choice(["auto", "bm25", "embeddings"]),
    default="auto",
    show_default=True,
    help="Ranking backend. auto = local embeddings iff the optional extra is "
    "installed and not disabled in config, else BM25. bm25 = force legacy. "
    "embeddings = force; degrades to BM25 with a notice if the extra is absent.",
)
@click.option(
    "--explain-ranker",
    is_flag=True,
    help="Print which ranker actually ran to stderr (stdout manifest unchanged).",
)
def context(query: str, budget: int, out: Path | None, no_learn: bool, ranker: str, explain_ranker: bool) -> None:
    """Return the smallest relevant subgraph for a query."""
    root = find_vault(Path.cwd()) or _abort_no_vault()
    text, used, files, reason = _build_context(root, query, budget, learn=not no_learn, ranker=ranker)
    click.echo(text)
    if explain_ranker:
        _err(f"# ranker: {reason}")
    if out:
        out.write_text(text)
    # record real token savings: vault total vs what context actually served
    try:
        from . import usage
        vault_tokens = sum(n.token_estimate for n in load_vault(root))
        usage.record(root, "context", tokens_served=used, tokens_vault=vault_tokens)
    except Exception:
        pass
    run_hook(root, "context", args=query, output_file=out)


@main.command()
@click.argument("slugs", nargs=-1, required=True)
@click.option("--bad", is_flag=True, help="Mark the listed notes as a bad/negative outcome (penalty) instead of positive.")
def used(slugs: tuple[str, ...], bad: bool) -> None:
    """Record an outcome for notes you just used (local only, no telemetry).

    Appends one record to `.lattice/cache/outcomes.jsonl`. `lattice context`
    applies a small, conservative, recency-decayed boost to recently/positively
    used notes (penalty for `--bad`). Nothing leaves the machine.
    """
    root = find_vault(Path.cwd()) or _abort_no_vault()
    known = {n.slug for n in load_vault(root)}
    unknown = [s for s in slugs if s not in known]
    if unknown:
        _err(f"unknown note(s): {', '.join(unknown)}")
        _err("nothing recorded; pass slugs that exist in the vault")
        sys.exit(1)
    _outcomes.record(root, list(slugs), good=not bad)
    label = "bad" if bad else "good"
    _ok(f"recorded {label} outcome for {len(slugs)} note(s)")
    run_hook(root, "used", args=",".join(slugs))


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
        # ranker defaults to "auto", which resolves through `[context] ranker`
        # so cached manifests use the same path as a live `context` run.
        text, used, files, _reason = _build_context(root, query, budget)
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
@click.option("--max-usd", default=None, type=float, help="One-shot daily cost ceiling for THIS run (overrides [budget] max_usd_per_day). Default 0 = never spend.")
@click.option("--force-spend", is_flag=True, help="Bypass the cost ceiling for this run only (logged loudly). Use sparingly.")
def digest(history_file: Path, keep_recent: int, write: bool, no_cache: bool, max_usd: float | None, force_spend: bool) -> None:
    """Compress a .CLAUDE.HISTORY file. Sessions older than --keep-recent become 5-line stubs.

    When ANTHROPIC_API_KEY is set, stubs can be drafted via Claude — but that
    spend is gated by the cost circuit-breaker (`[budget] max_usd_per_day`,
    default 0 = never spend). If the ceiling blocks the call, digest degrades to
    its local heuristic (no error, no spend). Raise the cap, pass `--max-usd`,
    or `--force-spend` to enable the Claude path.
    """
    from . import budget as _budget
    from .config import budget_config, budget_reset

    root = find_vault(Path.cwd())
    reset = budget_reset(root)
    archive_dir = (root / ".lattice/history/full") if root else (history_file.parent / ".lattice-history")
    archive_dir.mkdir(parents=True, exist_ok=True)
    text = history_file.read_text()
    sessions = _split_sessions(text)
    if not sessions:
        _err("could not detect session markers (expecting `# Session ...` or `--- DATE ---`)")
        sys.exit(1)
    keep = sessions[-keep_recent:] if keep_recent > 0 else []
    archive = sessions[: -keep_recent] if keep_recent > 0 else sessions

    # Cost circuit-breaker wiring. The ledger lives under the vault's cache; with
    # no vault there is nowhere to account spend, so the Claude path is gated
    # off (heuristic only). `pre_spend` is consulted BEFORE each Claude call.
    bcfg = budget_config(root)
    ceiling = max_usd if max_usd is not None else bcfg["max_usd_per_day"]
    est = bcfg["estimated_usd_per_digest"]
    blocked_notice_shown = {"v": False}

    def _pre_spend() -> bool:
        if root is None:
            return False
        decision = _budget.check(root, est_cost=est, max_usd=ceiling, reset=reset, force=force_spend)
        if not decision.allow:
            if not blocked_notice_shown["v"]:
                click.echo(click.style(decision.reason, fg="yellow"), err=True)
                click.echo(click.style("using local heuristic for digest stubs (no spend).", fg="yellow"), err=True)
                blocked_notice_shown["v"] = True
            return False
        if force_spend:
            click.echo(click.style(f"--force-spend: bypassing cost ceiling (~${est:.4f}/call)", fg="yellow"), err=True)
        return True

    def _record() -> None:
        if root is not None:
            _budget.record(root, est, reset=reset)

    pre = _pre_spend if root is not None else None
    post = _record if root is not None else None

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
        out_lines.append(_stub(body, vault=root, use_cache=not no_cache, pre_spend=pre, post_spend=post))
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


@main.command()
@click.option("--cron", "flavor_cron", is_flag=True, help="Emit a crontab snippet (default off platforms).")
@click.option("--launchd", "flavor_launchd", is_flag=True, help="Emit a launchd plist snippet (default on macOS).")
@click.option("--command", "subcommand", default=None, help="Subcommand to schedule (default from [schedule] command, else 'refresh').")
@click.option("--at", default=None, help="Daily run time HH:MM (default from [schedule] at, else 03:00).")
@click.option("--every", "every", default=None, help="Run every N hours instead of a fixed time, e.g. 6h.")
def schedule(flavor_cron: bool, flavor_launchd: bool, subcommand: str | None, at: str | None, every: str | None) -> None:
    """Print a ready-to-paste cron/launchd snippet for periodic lattice runs.

    lattice ships NO daemon and NEVER installs anything: this only prints a
    snippet to stdout. You copy it and install it yourself. The scheduled
    command is config-driven (`[schedule] command`), and the snippet reminds you
    that the job still obeys `[budget] max_usd_per_day` — so an unattended job
    can never silently spend (default ceiling 0 = no spend).
    """
    import sys as _sys

    from . import schedule as _sched
    from .config import schedule_config

    root = find_vault(Path.cwd()) or _abort_no_vault()
    scfg = schedule_config(root)

    cmd = subcommand or scfg["command"]
    run_at = at or scfg["at"]

    # parse --every (accepts "6h" or "6")
    every_hours: int | None = scfg["every_hours"] or None
    if every is not None:
        try:
            every_hours = int(every.rstrip("hH"))
        except ValueError:
            _err(f"invalid --every value: {every!r} (expected e.g. 6h)")
            _sys.exit(2)

    # flavor: explicit flags win; else config; else auto by platform.
    if flavor_cron and flavor_launchd:
        _err("--cron and --launchd are mutually exclusive")
        _sys.exit(2)
    if flavor_cron:
        flavor = "cron"
    elif flavor_launchd:
        flavor = "launchd"
    elif scfg["flavor"]:
        flavor = scfg["flavor"]
    else:
        flavor = "launchd" if _sys.platform == "darwin" else "cron"

    if flavor == "launchd":
        snippet = _sched.render_launchd(root, cmd, at=run_at, every_hours=every_hours)
    else:
        snippet = _sched.render_cron(root, cmd, at=run_at, every_hours=every_hours)

    click.echo(snippet)
    run_hook(root, "schedule", args=flavor)


@main.command(name="budget")
def budget_status() -> None:
    """Show today's local spend vs the configured cost ceiling (read-only).

    Reads the pure-local ledger under .lattice/cache/; spends nothing, calls no
    API. With the default ceiling 0 this confirms the Claude path is gated off.
    """
    from . import budget as _budget
    from .config import budget_config, budget_reset

    root = find_vault(Path.cwd()) or _abort_no_vault()
    bcfg = budget_config(root)
    ceiling = bcfg["max_usd_per_day"]
    reset = budget_reset(root)
    spent = _budget.spent_in_period(root, reset)
    est = bcfg["estimated_usd_per_digest"]
    label = {"hourly": "hour", "daily": "day", "weekly": "week", "monthly": "month"}.get(reset, reset)
    bucket = _budget._period_key(reset)
    if ceiling <= 0:
        click.echo(f"budget {bucket}: spent ${spent:.4f} — ceiling $0.00/{label} (never spend; Claude path OFF)")
        click.echo("raise [budget] max_usd_per_day to enable spending.")
    else:
        remaining = max(ceiling - spent, 0.0)
        click.echo(f"budget {bucket}: spent ${spent:.4f} / ${ceiling:.2f}/{label}  (remaining ${remaining:.4f})")
        click.echo(f"estimated cost per digest call: ${est:.4f}")
    run_hook(root, "budget", args=f"{spent:.4f}/{ceiling:.2f}")


@main.command()
def stats() -> None:
    """Local usage + health summary — how much you're actually using lattice.

    All local (reads .lattice/cache/, no telemetry). Reports command usage,
    real token savings from `context`, outcome signal, a live vault health
    snapshot, and citation coverage — and is explicit about what it can't
    measure (whether the agent used the context, or real time saved).
    """
    from . import usage as _usage, outcomes as _outcomes, verify as _verify
    root = find_vault(Path.cwd()) or _abort_no_vault()
    s = _usage.summarize(root)
    notes = load_vault(root)
    cite_re = citation_regex(root)

    click.echo(click.style("lattice stats", bold=True) + f"  —  {root}")

    # --- usage ---
    click.echo("\nUsage (local invocation log):")
    if s["total"] == 0:
        click.echo("  no usage recorded yet — run some commands, then re-check.")
    else:
        click.echo(f"  {s['total']} invocation(s)  ·  first {(s['first_seen'] or '')[:10]} → last {(s['last_seen'] or '')[:10]}")
        for cmd, n in sorted(s["counts"].items(), key=lambda kv: -kv[1]):
            click.echo(f"    {cmd:<10} {n}")

    # --- the advantage metric: token savings ---
    if s["context_calls"]:
        served_avg = s["context_tokens_served_avg"]
        vault_avg = s["context_tokens_vault_avg"]
        pct = int(round(s["context_served_ratio"] * 100))
        click.echo("\nContext (what was actually loaded vs. the vault):")
        click.echo(f"  {s['context_calls']} context call(s)  ·  {s['context_tokens_served_total']:,} tokens served total")
        click.echo(f"  per-call: ~{served_avg:,} served vs. ~{vault_avg:,}-token vault  →  ~{pct}% of the vault per call")

    # --- outcome signal ---
    orows = _outcomes.load(root) if hasattr(_outcomes, "load") else []
    if orows:
        good = sum(1 for r in orows if r.get("good"))
        click.echo(f"\nOutcomes (`lattice used`): {len(orows)} recorded — {good} good, {len(orows)-good} bad")

    # --- live vault snapshot + citation coverage ---
    total_tokens = sum(n.token_estimate for n in notes)
    per_note = [len(_verify.citations_in(n.body, cite_re)) for n in notes]
    cited = sum(per_note)
    uncited = sum(1 for c in per_note if c == 0)
    click.echo(f"\nVault snapshot: {len(notes)} notes · ~{total_tokens:,} tokens · {cited} citations · {uncited} note(s) with no citation")

    # --- honesty: what this CANNOT measure ---
    click.echo(click.style("\nNot measured (can't, honestly):", dim=True))
    click.echo("  - whether the agent actually USED the context it was served")
    click.echo("  - real time/ROI saved (needs a counterfactual lattice can't see)")
    click.echo("  - usage outside this machine (no telemetry, by design)")
    run_hook(root, "stats", args=str(s["total"]))


@main.command()
@click.option("--source", "-s", "src_names", multiple=True, help="Run only the named source(s); default = all configured in [sources].")
@click.option("--since", default=None, help="Override the git adapter watermark for this run (a SHA/rev); persists only after a successful run.")
@click.option("--limit", default=None, type=int, help="Cap candidate items per source (default from [refresh] limit, else 50).")
@click.option("--no-distill", is_flag=True, help="Skip the Claude path; force cost-free deterministic heuristic stubs.")
@click.option("--dry-run", is_flag=True, help="Discover + print what WOULD be drafted; write nothing, do not advance watermark.")
@click.option("--no-cache", is_flag=True, help="Bypass the agentic distill cache (mirrors `digest --no-cache`).")
def refresh(src_names: tuple[str, ...], since: str | None, limit: int | None, no_distill: bool, dry_run: bool, no_cache: bool) -> None:
    """Run configured source adapters and draft UNCITED candidate stubs.

    Explicit / opt-in: nothing runs unless you invoke this, and nothing is
    configured by default. Drafts go to `_inbox/` (a review area excluded from
    the note graph) — NEVER into a note body, so the citation invariant holds.
    Promote a draft by hand: verify it, add a citation, move it into a note.
    """
    from .refresh import run_refresh

    root = find_vault(Path.cwd()) or _abort_no_vault()
    configured = sources(root)
    if not configured:
        _ok("no sources configured — add a [sources.<name>] block to .lattice/config.toml to enable `lattice refresh`")
        return

    selected = list(src_names) or None
    if selected:
        unknown = [s for s in selected if s not in configured]
        if unknown:
            _err(f"unknown source(s): {', '.join(unknown)}; configured: {', '.join(sorted(configured))}")
            sys.exit(2)

    try:
        result = run_refresh(
            root,
            selected,
            distill=not no_distill,
            dry_run=dry_run,
            limit=limit,
            since=since,
            use_cache=not no_cache,
        )
    except KeyError as e:
        # unknown adapter name in [sources] — clear error, no traceback
        _err(str(e).strip("\"'"))
        sys.exit(2)

    arrow = "would draft" if dry_run else "drafts"
    for s in result.sources:
        wm = s.watermark or read_watermark_display(root, s.name)
        click.echo(f"{s.name:<14} {s.discovered} new since {wm} -> {s.drafted} {arrow} -> _inbox/")
        if dry_run:
            for p in s.paths:
                click.echo(f"    {p.name}")
    total = result.total_drafts
    if dry_run:
        click.echo(f"\ndry run — nothing written ({total} draft(s) previewed)")
    else:
        _ok(f"\nrefresh complete — {total} draft(s) in _inbox/ (uncited; review and promote by hand)")
        run_hook(root, "refresh", args=str(total))


def read_watermark_display(root: Path, source: str) -> str:
    """Watermark short-sha for the summary line, or '(first run)'."""
    from .adapters import read_watermark
    wm = read_watermark(root, source)
    return wm[:12] if wm else "(first run)"


@main.command()
def inbox() -> None:
    """List pending uncited drafts in the review-gate inbox dir.

    Read-only: never writes, safe to run anywhere in a vault. Drafts from
    `lattice refresh` land here (excluded from the verified corpus) for a human
    to review and `promote`. Empty inbox is not an error (exit 0).
    """
    from . import inbox as _inbox

    root = find_vault(Path.cwd()) or _abort_no_vault()
    drafts = _inbox.list_drafts(root)
    rel = _inbox.inbox_path(root).relative_to(root)
    if not drafts:
        click.echo(f"({rel}/ empty — drafts from `lattice refresh` land here)")
        run_hook(root, "inbox", args="0")
        return
    click.echo(click.style(f"{len(drafts)} pending draft(s) in {rel}/:", bold=True))
    for d in drafts:
        typ = d.type or "?"
        click.echo(f"  {d.slug:<28} ~{d.token_estimate:>4}t  [{typ}]  {d.title[:54]}")
    click.echo("\npromote one with: lattice promote <draft> [--type TYPE]")
    run_hook(root, "inbox", args=str(len(drafts)))


@main.command()
@click.argument("draft")
@click.option("--type", "kind", default=None, help="Destination note type (must be configured in [types]). If omitted, inferred from the draft's frontmatter `type:`.")
@click.option("--slug", default=None, help="Override the destination filename stem (default: the draft stem).")
@click.option("--keep", is_flag=True, help="Leave the original draft in the inbox (default: move it out).")
@click.option("--force", is_flag=True, help="Overwrite an existing target note.")
def promote(draft: str, kind: str | None, slug: str | None, keep: bool, force: bool) -> None:
    """Promote an inbox DRAFT into a real category dir as a templated note.

    The promoted note carries the draft material as clearly-UNCITED scratch, so
    it STILL fails `lattice lint` until a human cites the claims and moves them
    into the body — promotion can never launder an uncited claim into the
    verified corpus. Deterministic file/template op: no network, no LLM, no
    spend. DRAFT is resolved within the configured inbox dir only.
    """
    from . import inbox as _inbox

    root = find_vault(Path.cwd()) or _abort_no_vault()
    d = _inbox.resolve_draft(root, draft)
    if d is None:
        _err(f"no draft {draft!r} in {_inbox.inbox_path(root).relative_to(root)}/")
        _err("list pending drafts with `lattice inbox` (drafts are resolved inside the inbox only)")
        sys.exit(1)

    types = note_types(root)
    chosen = kind or d.type
    if chosen is None or chosen not in types:
        if kind is not None:
            _err(f"unknown type {kind!r}; configured types: {', '.join(sorted(types))}")
            _err("add it under [types] in .lattice/config.toml to use a new one")
        else:
            inferred = f" (draft `type: {d.type}` is not a configured note type)" if d.type else ""
            _err(f"could not infer destination type{inferred}; pass --type")
            _err(f"configured types: {', '.join(sorted(types))}")
        sys.exit(2)

    dest_slug = slug or d.slug
    target = root / types[chosen] / f"{dest_slug}.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and not force:
        _err(f"{target.relative_to(root)} already exists (use --force to overwrite)")
        sys.exit(1)

    note_text = _inbox.build_promoted_note(d, chosen, dest_slug, _today())
    # Write target FIRST, verify it, only THEN remove the source — never lose a
    # draft on a half-failed move.
    target.write_text(note_text)
    if not keep and target.exists():
        d.path.unlink()

    rel = target.relative_to(root)
    _ok(f"promoted to {rel}; add citations then run `lattice lint`")
    run_hook(root, "promote", args=f"{chosen}:{dest_slug}")


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


def _lint_note(note, cite_re: re.Pattern[str], file_warn: int, file_max: int) -> list[str]:
    """Return the list of lint problems for one note. Shared by `lint` and
    `doctor` so the heuristic never diverges between them. Behavior-preserving
    extraction of the original inline loop; budgets are now config-driven.
    """
    problems: list[str] = []
    # hard-fail directive: an explicit `<!-- lattice: needs-citation -->` marks
    # the note as carrying unverified material (e.g. a promoted inbox draft).
    # It fails the gate regardless of the trigger-word heuristic, until a human
    # verifies + cites the claims and removes the marker.
    if re.search(r"<!--\s*lattice:\s*needs-citation\s*-->", note.body):
        problems.append("marked `needs-citation` — verify, cite, and remove the marker")
    if not note.type:
        problems.append("missing frontmatter `type`")
    if not note.last_verified:
        problems.append("missing frontmatter `last_verified`")
    if not re.search(r"##\s*(?:\d+\.\s*)?Open questions", note.body):
        problems.append("missing `## Open questions` section")
    if "Referenced by" not in note.body:
        problems.append("missing `## Referenced by` section (run `lattice link --fix`)")
    # token budget
    toks = note.token_estimate
    if toks > file_max:
        problems.append(f"file too large ({toks} tokens > {file_max})")
    elif toks > file_warn:
        problems.append(f"file getting large ({toks} tokens > {file_warn}) — consider splitting")
    # citation check: skip ONLY the Open questions section itself, not
    # everything after it (e.g. Referenced by + any later additions).
    body_for_check = re.sub(
        r"##\s*(?:\d+\.\s*)?Open questions.*?(?=^##\s|\Z)",
        "",
        note.body,
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
        # conscious-exception escape hatch (pylint `# noqa` style): a
        # `<!-- lattice-ignore -->` on the line exempts it from the citation check.
        if "<!-- lattice-ignore -->" in line or "<!--lattice-ignore-->" in line:
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
    return problems


def _orphans(notes: list) -> list:
    """Notes with no inbound AND no outbound body-wikilinks. Uses the same
    body-link graph as `link` (frontmatter `related` is NOT a link)."""
    by_slug = {n.slug: n for n in notes}
    outbound: dict[str, set[str]] = {}
    inbound: dict[str, set[str]] = {n.slug: set() for n in notes}
    for n in notes:
        targets = {t for t in _outgoing_links(n.body) if t in by_slug and t != n.slug}
        outbound[n.slug] = targets
        for t in targets:
            inbound[t].add(n.slug)
    return [n for n in notes if not outbound[n.slug] and not inbound[n.slug]]


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


def _stub(
    body: str,
    vault: Path | None = None,
    use_cache: bool = True,
    pre_spend=None,
    post_spend=None,
) -> str:
    """Compress a session body to 5 bullets.

    Tries Claude API first (set ANTHROPIC_API_KEY); falls back to a cheap
    heuristic when the API is unavailable OR when the cost circuit-breaker
    (`pre_spend`) blocks the call.
    """
    from .agentic import agentic_stub
    out = agentic_stub(body, vault=vault, use_cache=use_cache, pre_spend=pre_spend, post_spend=post_spend)
    if out:
        return out
    lines = [l.strip() for l in body.splitlines() if l.strip()]
    bullets = [l for l in lines if l.startswith(("-", "*"))][:5]
    if len(bullets) < 5:
        bullets += [f"- {l[:120]}" for l in lines if not l.startswith(("-", "*", "#"))][: 5 - len(bullets)]
    return "\n".join(f"  {b}" for b in bullets[:5]) or "  (empty)"


if __name__ == "__main__":
    main()
