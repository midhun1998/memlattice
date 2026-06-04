# memlattice v0.2 — Trust-Gate Milestone (design)

**Scope:** one milestone, vault-first. Repositions lattice toward "the
verification gate for agent memory" while keeping the existing engine
load-bearing.

The market context: agent memory *capture* is now solved by the platforms
(native session memory) and by tools like claude-mem/mem0. The unmet need is
*trust* — agent memory fills with speculation later cited as fact, goes stale,
and lacks provenance. This milestone makes "verified" real and enforceable.

## Goals
1. Make "verified" TRUE — real source-checking, not just citation-token presence.
2. Make the agent use lattice automatically — an MCP server.
3. Make memory governable in CI — a fail-the-build gate + audit artifact.
4. Generalize the cost breaker to hourly/daily/weekly/monthly reset periods.
5. Reposition messaging; fix the "verified by construction" overclaim.

## Non-goals
- Not replacing the vault with "gate over native memory" (deferred; would make us
  a guest of another tool's format).
- No new CORE dependencies. `mcp` SDK and any entailment libs are optional extras.
- Entailment never runs unattended or by default (budget-gated, default $0).

## Architecture — one engine, three faces

```
   human ── CLI ───────────▶ ┌──────────────────────────────┐
   agent ── MCP server ─────▶ │  lattice core (existing)     │
   CI ──── lattice lint ────▶ │  vault · lint · context ·    │
           --ci + verify      │  verify · citations · budget │
                              └──────────────────────────────┘
```
The MCP server and CI gate call existing functions IN-PROCESS (no subprocess).
Nothing existing is replaced.

## Component 1 — `lattice verify` (keystone)

New module `lattice/verify.py`; new command `lattice verify [paths] [--changed]
[--entail] [--format text|json|sarif] [--max-usd N]`.

**Approach A — tiered, per citation:**

**Layer 1 — existence/freshness (free, always on, deterministic, no LLM, no net
except doc/url/pr which are opt-in fetch):**
- `[file:path]` / `[file:path:line]` → path (and line) exists; content hash of
  the cited line/region compared to a stored hash → `present | drifted | missing`
- `[commit:sha]` → reachable in the repo (`git cat-file -e`) → `present | missing`
- `[pr:owner/repo#n]`, `[url:…]`, `[doc:url]` → opt-in fetch (`--fetch`), hash +
  flag drift since `last_verified`; offline default = `unfetched`
- `[conv:…]`, `[chat:…]`, `[jira:…]`(no adapter) → `human-attested` (can't auto-check)

**Layer 2 — entailment (opt-in `--entail`, budget-gated via existing breaker):**
for `present`/`fetched` sources, LLM-as-judge over (claim, source span) →
`supported | contradicted | unsupported | unverifiable`. Reuses `agentic.py`
Claude path; **off when budget ≤ 0** → silently skips, reports Layer-1 only.

**Status model (per citation), worst-status-wins per claim/note:**
`supported` > `present`/`fetched`/`human-attested` (pass) ›
`drifted` (warn) › `missing`/`contradicted`/`unsupported` (FAIL).

Exit non-zero if any claim is at a FAIL status. Pure logic (status reduction,
citation parsing) separated from IO (git/fetch/LLM) behind seams for testing.

## Component 2 — MCP server (`lattice/mcp/`, `[mcp]` extra)

- `pip install "memlattice[mcp]"`; entry point `lattice-mcp` (stdio server).
- Tools (thin wrappers importing core functions): `lattice_context(query,budget)`,
  `lattice_search(query)`, `lattice_lint()`, `lattice_verify(path?)`.
- Guarded import: core works with zero extras; `lattice-mcp` errors with a clear
  "pip install memlattice[mcp]" if SDK absent.
- A `lattice install claude-code` helper writes a project `.mcp.json` stub + a
  5-line `CLAUDE.md`/rules pointer so the agent uses it automatically (no
  "remember to run" instruction). Idempotent; writes nothing without consent.

## Component 3 — CI audit gate

- `lattice lint --ci [--format json|sarif]` + `lattice verify --changed --ci`.
- `--changed` limits to memory files changed vs a base ref (git diff).
- Emits a machine-readable report: per-claim {file, line, claim, citation,
  layer1-status, entail-status, promoted-by}. SARIF for GitHub code-scanning.
- Exits non-zero on FAIL statuses → fails the PR build.
- **Use case (honest):** teams committing shared agent memory to a repo; catches
  uncited/unsupported/stale facts before they merge and propagate to every
  agent. Enterprise/team-scoped; not a solo-dev need (documented as such).

## Component 4 — budget reset periods

Generalize `lattice/budget.py` from daily-only to `[budget] reset = hourly |
daily | weekly | monthly` (default `daily`; `max_usd_per_day` kept as a
backward-compatible alias mapping to daily). Ledger keys become period-bucket
keys (`2026-06-03T14` hourly, `2026-06-03` daily, `2026-W23` weekly,
`2026-06` monthly) via a `_period_key(reset)` helper (monkeypatchable like
`_today`). `spent_today` kept + a generalized `spent_in_period`. `check`/`record`
take the configured period. Backward compatible: existing daily ledgers + the
`max_usd_per_day` key keep working.

## Component 5 — repositioning (copy only, no behavior)
- Fix "verified by construction" → accurate ("cited by construction; verifiable
  on demand with `lattice verify`").
- Landing + README lean into the gate framing.
- **Architecture diagram** (the one above, polished) added to README + the
  GitHub Pages landing page — DONE AT THE END of the milestone.

## Testing (TDD, per component)
- verify: unit tests for each citation type × status (present/drifted/missing/
  human-attested); entailment behind a mock (no real LLM in tests); budget-off
  skips entailment; worst-status reduction; exit codes.
- MCP: import-guard test (works without SDK); each tool returns core output;
  in-process call (no subprocess).
- CI: `--changed` diff scoping; JSON + SARIF shape; non-zero on FAIL.
- budget: each reset period's bucket key + rollover (monkeypatch clock);
  backward-compat with daily + `max_usd_per_day`.
- Full suite green; embeddings + no-extra envs both pass (CI matrix already covers).

## Build order (each step: test-first, full suite green, one focused commit)
1. budget reset periods (self-contained, no deps)
2. `lattice verify` Layer 1 (deterministic) + status model + CLI
3. verify Layer 2 (entailment, budget-gated)
4. CI flags + JSON/SARIF audit artifact
5. MCP server + `[mcp]` extra + `install claude-code`
6. repositioning copy + architecture diagram (README + Pages) — LAST

## Open questions
- [ ] (2026-06-03) Stored hashes for file-citation drift detection: where do they
  live — frontmatter, or a `.lattice/cache/verify-hashes.json`? Leaning cache.
- [ ] (2026-06-03) SARIF mapping fidelity for "uncited claim" (no real source
  location) — may emit at the claim's own line. Confirm GitHub renders it.
- [ ] (2026-06-03) `install claude-code` — do we also offer a generic
  `install --print` that just prints the `.mcp.json` for other agents?
