# lattice — design spec (v0.1)

## Goals

1. Make AI agent long-term memory **structured, verified, and tool-agnostic**.
2. Reduce tokens spent on memory load by serving **only relevant subgraphs**.
3. Keep the system **file-native, offline, and dependency-light** — no DB,
   no embeddings server. Just markdown + a CLI.
4. Be opinionated where it prevents drift, permissive where it would
   block adoption.

## Non-goals

- Replace Obsidian / Logseq / Foam. lattice files live happily inside any
  of them.
- Be a vector store / RAG runtime. That's downstream of lattice's job.
- Be a wiki for humans. Humans can read it, but the audience is the
  agent.

## Directory layout

```
<vault>/
  README.md         # human-facing index (auto-maintained)
  _protocol.md      # update rules
  _template.md      # 8-section flow skeleton
  components/       # per-service notes
  flows/            # end-to-end product paths
  api/              # validated endpoints / payloads
  .lattice/
    config.toml     # vault config (token budgets, lint rules)
    cache/          # link graph, citation index, token counts
    history/        # compressed .CLAUDE.HISTORY digests, by repo
```

## File contract

Every `.md` under `components/`, `flows/`, `api/` has frontmatter:

```yaml
---
type: flow | component | api
last_verified: YYYY-MM-DD
related: [other-file-slug, ...]
tokens: <auto-maintained int>          # rough char/4 estimate
---
```

Body sections are governed by `_template.md`. Two are mandatory:

- `## Open questions` — speculation goes here, dated. Lint blocks
  un-cited claims in the body but accepts them here.
- `## Referenced by` — auto-maintained backlinks (`lattice link`).

Citation format: any factual claim about a named service / repo /
endpoint must end with a citation token. Accepted forms:

- `[file:path/to/file.py:42]`
- `[doc:https://...]`
- `[url:https://...]`
- `[commit:<sha>]`
- `[pr:<owner>/<repo>#<number>]`
- `[conv:<person>:YYYY-MM-DD]`

The default schemes are vendor-neutral. Add your own (e.g. `jira`,
`linear`, `notion`, `confluence`) via `[citations] extra = [...]` in
`config.toml` — they then become valid citation tokens.

Lint flags claims that name a Proper-Noun-Service without a trailing
citation in the same paragraph.

## CLI surface

```
lattice init [<dir>]                 # scaffold
lattice new <type> <slug>            # from _template.md
lattice link [--fix]                 # rebuild Referenced-by sections
lattice lint                         # citations + structure
lattice stale [--days N]             # last_verified older than N
lattice context <query> [--budget N] # subgraph relevant to query
lattice digest <history-file>        # compress .CLAUDE.HISTORY
lattice graph [--mermaid]            # emit graph for README
lattice verify <file>                # agentic re-check of citations (v0.2)
```

### `lattice context` — token-aware retrieval

The expensive part of agent memory is loading a 50K-token vault into a
session that needs 2K of it. `context` uses cheap, deterministic
retrieval over the link graph:

1. BM25 over filenames + headings (no embeddings needed for v0.1).
2. Expand the top hits one hop along `[[wikilinks]]`.
3. Trim to `--budget` tokens (default 4000), preferring whole sections
   over partial files.
4. Emit a manifest the agent can paste / `Read` directly:

   ```
   # lattice context for: "how does checkout settle a payment?"
   files: 3   tokens: 2140 / 4000
   - flows/checkout.md#phase-c-settlement              (1180 tokens)
   - components/payment-gateway.md#1-endpoint          (520 tokens)
   - components/payment-gateway.md#3-apis-we-use       (440 tokens)
   ```

   v0.2: optional embedding backend (sentence-transformers, or an MCP
   call to whatever embedding server is around). v0.1 stays
   embedding-free so install is one `pipx`.

### `lattice digest` — taming `.CLAUDE.HISTORY`

`.CLAUDE.HISTORY` files grow unboundedly. The user dumps the compacted
session summary on every compaction; over weeks a repo's history file
hits 30K tokens and silently dominates every new session's context.

`digest` does:

1. Reads the existing `.CLAUDE.HISTORY`.
2. Splits by session marker (default: top-level `# Session ...` heading
   or `--- DATE ---` separator).
3. For each session older than `--keep-recent` (default: last 3),
   compresses to a 5-line bullet stub:
   - what was done
   - what files changed
   - what was learned (citation-worthy)
   - what's still open
   - link to full session (kept in `.lattice/history/full/<slug>.md`)
4. Writes a new `.CLAUDE.HISTORY` containing: header pointer to
   `.lattice/history/`, last N sessions verbatim, then the stub list.
5. Surfaces a diff so the user reviews before overwriting.

Compression target: ~80% reduction with all citation-worthy facts
preserved. Stubs link to the full version, so the agent can opt-in to
the long form when needed.

## Token-budget enforcement

`config.toml`:

```toml
[budgets]
file_warn = 6000      # token count above which lint warns
file_max = 12000      # above which lint errors
context_default = 4000

[lint]
require_citations = true
require_open_questions = true
require_referenced_by = true
```

Files that grow past `file_warn` get a lint warning recommending atomic
split.

## Tool-integration stubs

`lattice init` writes (idempotently) into the user's chosen agent
config files:

- `CLAUDE.md` (or `~/.claude/CLAUDE.md`):
  > Long-term memory at `<vault>`. Read `_protocol.md` before editing.
  > Use `lattice context "<query>"` to load only relevant subset.
- `AGENTS.md` — same.
- `.cursorrules` — same.

Each is *additive* and clearly fenced (`<!-- lattice:start -->` /
`<!-- lattice:end -->`) so users can update the snippet without
clobbering their custom rules.

## Verification protocol (v0.2)

`lattice verify <file>`:

1. Parses citations.
2. For each `[file:...]`, checks the file/line still exists and matches
   the snippet.
3. For each `[doc:...]`, fetches the URL, diffs against last-known hash.
4. For each `[chat:...]` / `[conv:...]`, marks as user-attestation
   (can't auto-verify).
5. Updates `last_verified` for items that pass.

This is the "your memory might be lying to you" feature. Optional —
disabled by default.

## Roadmap

- **v0.1 (this milestone):** init, new, link, lint, stale, context,
  digest. No external deps beyond `click` + `pyyaml`.
- **v0.2:** verify (agentic), embeddings backend for context, MCP
  server, graph mermaid renderer.
- **v0.3:** multi-vault federation (work + personal), conflict
  resolution, sync to git with verification gates in pre-commit.

## What success looks like

- A user installs `lattice`, runs `init`, and within 15 minutes has a
  populated `flows/auth.md` that their Claude session reads selectively.
- A team adopts it; their `CLAUDE.md` shrinks from 1800 lines to 30
  lines + a vault.
- `lattice lint` becomes a pre-commit hook in their repo.
- The README's first sentence makes a maintainer say "oh god, yes"
  out loud.
