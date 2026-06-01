# Changelog

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
