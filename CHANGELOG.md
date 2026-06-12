# Changelog

## Unreleased

- **`lattice stats`** — local usage + health summary. Reports command-usage
  frequency, per-call `context` metrics (avg tokens served vs. avg vault size,
  shown as a served-ratio so the comparison stays honest — no summed
  "saved" delta that can exceed the vault), `lattice used` outcome signal, a
  live vault snapshot (notes, tokens, citation coverage), and is explicit
  about what it *can't* measure (whether the agent used the context, real
  ROI). A best-effort invocation log (`.lattice/cache/usage.jsonl`, gitignored,
  no telemetry) records one row per command; `context` rows also carry served
  + vault sizes. Pure-local; a log-write failure never breaks the underlying
  command.
- **Fixes (from dogfooding):** git source-adapter and MCP vault resolution now
  expand `~`/absolute paths; `lattice init` gitignores `_inbox/` drafts.

## v0.2.0 (2026-06-03) — the verification gate

Repositions lattice as the trust/verification layer for agent memory.

- **`lattice verify`** — does the cited source still back the claim? Layer 1
  (always, no LLM): file:/commit: existence + freshness; conv:/chat:
  human-attested; doc:/url:/pr: unfetched unless `--fetch`; cross-repo paths are
  `unresolvable` (warn), distinct from `missing` (fail). Layer 2 (`--entail`):
  an LLM judges supported/contradicted/unsupported, **gated by the cost breaker
  and off at the default $0** (never spends silently).
- **CI audit gate** — `verify --changed --base REF` scopes to changed memory
  files; `--format json|sarif` emits a machine-readable artifact (SARIF for
  GitHub code-scanning); exits non-zero on missing/contradicted/unsupported.
- **MCP server** (`lattice/mcp`, `pip install "memlattice[mcp]"`,
  `lattice-mcp`) exposes context/search/lint/verify in-process; `lattice
  install claude-code` wires it into a project `.mcp.json` so the agent queries
  lattice natively. Core still imports without the SDK.
- **Budget reset periods** — `[budget] reset = hourly|daily|weekly|monthly`
  (daily default; `max_usd_per_day` kept as a backward-compatible alias).
- Honest framing: "verified by construction" → "cited by construction,
  verifiable on demand" (lint enforces citations; `verify` checks sources).

## Unreleased

- **`lattice used <slug> [<slug>...] [--bad]`** — record an outcome for notes
  you just used. Appends one local-only JSONL record to
  `.lattice/cache/outcomes.jsonl` (gitignored, no telemetry, nothing leaves the
  machine). Unknown slugs are rejected so no garbage is recorded.
- **Outcome rank boost in `lattice context`.** A small, conservative,
  recency-decayed multiplier from those outcomes is applied on top of BM25 so
  recently/positively-used notes rank slightly higher; `--bad` penalizes.
  Configurable under `[learn]` (`enabled`, `boost`, `penalty`,
  `half_life_days`). On by default but capped so it can only nudge, never flip
  strong BM25 signal; the penalty is floored above zero so a relevant note is
  never hidden. Disable per-invocation with `lattice context --no-learn` or
  globally with `[learn] enabled = false`. With no outcomes file, behavior is
  identical to pure BM25. New `post-used` hook event.
- **Lint directives (`# noqa`-style).** `<!-- lattice-ignore -->` exempts a
  single line from the citation check (a conscious exception); `<!-- lattice:
  needs-citation -->` hard-fails a note until removed, regardless of the
  trigger-word heuristic.
- **Fix: `lattice promote` no longer launders uncited claims.** Promoted draft
  material now lands in a scanned body section with a `needs-citation` marker,
  so an unverified promotion fails `lint` (previously it was parked under
  `## Open questions`, which lint excludes, and silently passed). Found by
  dogfooding the real `refresh → promote` flow.

## v0.1.0 (2026-06-01) — config-driven, public

- **Config-driven citation schemes.** Citation prefixes now come from
  vendor-neutral defaults (`file`, `doc`, `url`, `commit`, `pr`, `conv`,
  `chat`) plus `[citations] extra = [...]` in `config.toml`. No source tool is
  hardcoded into core.
- **User-defined note types.** `[types]` in `config.toml` maps any type name to
  a directory; `lattice new` accepts it and creates the directory on demand.
  `flow` / `component` / `api` remain the zero-config defaults.
- **`lattice lint` fixes.** No longer flags caption lines (ending in `:`) or
  content inside fenced code blocks as un-cited claims.
- **`lattice link` is now idempotent** and no longer destroys backlinks on
  repeated runs (links inside the `Referenced by` section are no longer counted
  as outbound edges).
- Test suite (pytest) and CI across Python 3.10–3.12; community health files;
  design doc with diagrams; landing page.

## v0.0.1 (2026-05-29) — bootstrap

First working set. Eat-our-own-dogfood phase.

- `lattice init` — scaffold a vault (idempotent).
- `lattice new <type> <slug>` — create a note from `_template.md`.
- `lattice link [--fix]` — recompute `## Referenced by` from `[[wikilinks]]`.
- `lattice lint` — frontmatter, structure, citation heuristic, token budget.
- `lattice stale --days N` — list notes older than N.
- `lattice context <query> [--budget N] [--out FILE]` — BM25 + 1-hop graph
  walk; trims to budget; writes manifest.
- `lattice cache [--build]` — pre-rendered offline manifests for
  configured queries; readable with no Python / no live BM25.
- `lattice digest <history> [--keep-recent N] [--write]` — compress
  `.CLAUDE.HISTORY`; archives full sessions to `.lattice/history/full/`.
- Hooks system (`[hooks]` in `.lattice/config.toml`) — runs scripts after
  any command. Env: `LATTICE_VAULT`, `LATTICE_EVENT`, `LATTICE_ARGS`,
  `LATTICE_OUTPUT_FILE`.
