# Changelog

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
