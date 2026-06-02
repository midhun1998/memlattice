<p align="center">
  <img src="docs/assets/lattice-logo.png" width="150" alt="lattice logo"/>
</p>

<h1 align="center">lattice</h1>

<p align="center">
  <strong>Your AI agent's long-term memory, in plain markdown. Verified by construction.</strong>
</p>

<p align="center">
  <a href="https://github.com/midhun1998/memlattice/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/midhun1998/memlattice/actions/workflows/ci.yml/badge.svg"></a>
  <a href="LICENSE"><img alt="License: MIT" src="https://img.shields.io/badge/license-MIT-blue.svg"></a>
  <img alt="Python" src="https://img.shields.io/badge/python-3.10%2B-blue.svg">
  <img alt="Dependencies" src="https://img.shields.io/badge/deps-3-brightgreen.svg">
  <a href="https://midhun1998.github.io/memlattice/"><img alt="Landing page" src="https://img.shields.io/badge/site-lattice-22d3ee.svg"></a>
</p>

---

Every Claude Code / Cursor / Aider user ends up writing the same thing: a
sprawling `CLAUDE.md` / `AGENTS.md` / `.cursorrules` that grows into a
2,000-line wiki the model never fully reads — riddled with speculation it later
cites as fact. **lattice** is a tiny CLI + markdown convention that makes that
memory **structured, verified, multi-tool, and cheap on tokens** — without a
database, a server, or vendor lock-in.

```bash
pipx install memlattice
lattice init ~/knowledge
```

> **It's a `pre-commit` for agent memory** — convention + a small CLI, not a
> service. It stays out of your way until your facts drift, then yells.

## Why lattice

| | lattice | `CLAUDE.md` / `AGENTS.md` | Hosted memory runtimes | Obsidian + RAG plugin |
|---|:---:|:---:|:---:|:---:|
| File-native plain markdown | ✅ | ✅ | ❌ opaque store | ✅ |
| Citation / verification gate | ✅ **enforced** | ❌ | ❌ | ❌ |
| Token-bounded retrieval | ✅ built-in | ❌ loads all | ✅ | ✅ |
| No server / no database | ✅ | ✅ | ❌ hosted | ❌ plugin runtime |
| Multi-tool (CC / Cursor / Aider) | ✅ any | ❌ per-tool | ❌ single SDK | ❌ Obsidian only |
| Bounded file growth | ✅ lint budgets | ❌ unbounded | ✅ | ❌ manual |

## Install

```bash
# recommended
pipx install memlattice

# or into the current environment
pip install memlattice
```

Requires Python 3.10+. The optional Claude-backed `digest` is `pip install
"memlattice[agentic]"`. The optional local-embedding ranker for `context` is
`pip install "memlattice[embeddings]"` (heavy — it pulls in
sentence-transformers + torch + numpy, hundreds of MB; runs fully locally with
no hosted API, no server, no spend; first use downloads model weights). Core
stays dependency-light: without the extra, `context` silently uses BM25. From
source: `git clone … && pip install -e .`.

## Quickstart

```bash
$ lattice init ~/knowledge
vault initialised at ~/knowledge
  created: _protocol.md, _template.md, README.md, .lattice/config.toml

$ lattice new flow checkout
created flows/checkout.md

$ lattice lint
flows/checkout.md  ✗ un-cited factual line: PaymentGateway stores tokens in Redis
1 file(s) with problems

# add a citation → [doc:payments/runbook] → and it passes
$ lattice lint
flows/checkout.md  ✓ ok

$ lattice context "how does checkout settle a payment?"
# lattice context for: "how does checkout settle a payment?"
files: 3   tokens: ~2,140 / 4,000
- flows/checkout.md#phase-c-settlement              (1,180 tokens)
- components/payment-gateway.md#1-endpoint            (520 tokens)
- components/payment-gateway.md#3-apis-we-use         (440 tokens)
```

Then tell your agent, once:

> Long-term memory lives at `~/knowledge`. Read `_protocol.md` before editing.
> Run `lattice context "<query>"` to load only the relevant subset.

## Commands

| Command | What it does |
|---|---|
| `lattice init [<dir>]` | Scaffold a vault (idempotent) |
| `lattice new <type> <slug>` | Create a note from the template |
| `lattice lint` | Cited-fact checker, structure + token-budget guard |
| `lattice link [--fix]` | Rebuild bidirectional `Referenced by` backlinks |
| `lattice stale [--days N]` | List notes older than N days |
| `lattice context <query> [--budget N] [--no-learn] [--ranker auto\|bm25\|embeddings] [--explain-ranker]` | Smallest relevant subgraph for a query. `--ranker` picks the backend (`auto` = local embeddings iff the `[embeddings]` extra is installed, else BM25); `--explain-ranker` notes which ran on stderr (stdout manifest unchanged) |
| `lattice used <slug> [<slug>...] [--bad]` | Record a local-only outcome so `context` ranks used notes slightly higher (`--bad` penalizes) |
| `lattice cache [--build]` | Pre-render context manifests for offline use |
| `lattice digest <history-file>` | Compress an unbounded session-history file |
| `lattice doctor [--days N] [--strict]` | Read-only vault health summary (counts, stale, orphans, budgets, lint); exits non-zero on hard problems |
| `lattice refresh [-s NAME] [--since REF] [--limit N] [--no-distill] [--dry-run] [--no-cache]` | Run configured source adapters and draft **uncited** candidate stubs into `_inbox/` for review (opt-in, default-off) |
| `lattice inbox` | List pending **uncited** drafts in the review-gate inbox dir (read-only; empty inbox is not an error) |
| `lattice promote <draft> [--type TYPE] [--slug SLUG] [--keep] [--force]` | Move an inbox draft into a real category dir as a templated note that **still** must earn citations to pass `lint` |

## The five opinions

1. **Structure by construction.** Configurable layers — `components/`, `flows/`,
   `api/`, or your own — so loose memory becomes organized automatically.
2. **Verification gates.** Every named service / endpoint / fact carries a
   citation. Speculation lives in a quarantined `## Open questions` section that
   physically can't pollute the body. `lattice lint` enforces it.
3. **Graph by markdown links, not a database.** `[[wikilinks]]` work in
   Obsidian, for any LLM, and in `grep`. Backlinks are maintained for you.
4. **Tool-agnostic.** Claude Code, Cursor, Windsurf, Aider, Continue — all read
   the same files. Per-tool entry stubs are thin pointers, not lock-in.
5. **Token-aware.** `lattice context` returns the smallest relevant subgraph,
   not the whole vault. Frontmatter budgets prevent runaway files.

## Configuration

Everything lives in `.lattice/config.toml`. Citation schemes and note types are
yours to define — nothing is hardcoded:

```toml
[types]
runbook = "runbooks"          # adds a new note type + directory

[citations]
extra = ["jira", "linear"]    # on top of the vendor-neutral defaults

[learn]
enabled = true                # outcome rank boost on context (set false to disable)
boost = 0.15                  # max uplift for a fresh positive `lattice used`
penalty = 0.30                # max downweight for a fresh `lattice used --bad`
half_life_days = 30           # how fast an outcome's effect decays with age
```

Defaults ship vendor-neutral (`file`, `doc`, `url`, `commit`, `pr`, `conv`,
`chat`); add whatever your team actually cites.

`lattice used` writes outcomes to `.lattice/cache/outcomes.jsonl` — local-only,
intentionally gitignored, and never sent anywhere. The boost it feeds into
`lattice context` is deliberately conservative: it can only nudge ranking, never
override strong BM25 relevance, and a penalized note is never dropped entirely.

## Source adapters & `lattice refresh`

`lattice refresh` pulls candidate facts from external sources into a review
queue — **without** ever bypassing the citation gate. It is **explicit and
default-off**: it only runs when you type it, there is no scheduler or daemon,
and with no `[sources]` configured it is a no-op.

```toml
# .lattice/config.toml — nothing here = refresh does nothing
[sources.repo]
adapter = "git"            # the only built-in adapter (local-only, no network/auth)
path    = "."              # repo to scan, relative to the vault
branch  = "main"           # optional
paths   = ["docs/", "src/"]  # optional path filter
```

```bash
$ lattice refresh --dry-run         # preview; writes nothing, no watermark move
repo           3 new since (first run) -> 3 would draft -> _inbox/

$ lattice refresh                   # draft uncited stubs into _inbox/
repo           3 new since (first run) -> 3 drafts -> _inbox/
refresh complete — 3 draft(s) in _inbox/ (uncited; review and promote by hand)
```

How the core invariant is preserved:

- Drafts land in **`_inbox/`**, a review area `load_vault` already excludes (it
  starts with `_`), so `lint`, `link`, and `context` never read them.
- Every draft is an **uncited stub** with a `needs-citation` marker. You promote
  it by hand: verify the claim, add a real citation, rewrite it into a note body,
  then delete the stub. Uncited claims still cannot enter a note body.
- The built-in **`git`** adapter is universal: it shells out to your local `git`
  binary (`git log` since a stored watermark under the gitignored
  `.lattice/cache/`), so it needs **no network and no token**. The first run is
  bounded to the most recent commits (not the whole history); `--limit` caps it
  further.
- Optional distillation reuses the same Claude path as `digest` and **no-ops
  without `ANTHROPIC_API_KEY`** (or with `--no-distill` / `[refresh] distill =
  false`), degrading to a cost-free heuristic.

`_inbox/` may contain raw commit text from a private repo — treat it as a
review area and consider gitignoring it; redaction happens when you promote.

**Custom adapters** (e.g. a fabricated `checkout-events`, `payment-gateway`, or
`jira` adapter) ship as **separate packages** that register under the
`lattice.adapters` entry-point group and expose `discover() -> list[RawItem]` —
so proprietary/internal sources stay out of this OSS tree and bring their own
dependencies. Installing a third-party adapter runs its code; a broken one is
skipped with a warning rather than aborting the run.

## Reviewing the inbox: `lattice inbox` & `lattice promote`

`_inbox/` is the review gate between adapter output and the verified corpus.
Two manual, side-effect-light commands work it — no scheduler, no network, no
LLM, no spend:

```bash
$ lattice inbox                                   # read-only list of pending drafts
2 pending draft(s) in _inbox/:
  add-checkout-settlement-step  ~  84t  [?]  add checkout settlement step
  payment-gateway-retry          ~  72t  [?]  payment gateway retry policy

$ lattice promote add-checkout-settlement-step --type flow
promoted to flows/add-checkout-settlement-step.md; add citations then run `lattice lint`
```

- `promote` builds a real templated note (same skeleton as `lattice new`) and
  carries the draft text in as clearly-**uncited scratch** under `## Open
  questions`. The promoted note therefore **still fails `lattice lint`** until a
  human verifies each claim, adds a citation token, and moves it into the body —
  promotion can never launder an uncited claim into the verified corpus.
- It is a **move** by default (the draft is consumed); `--keep` leaves the
  original. `--type` is inferred from the draft frontmatter when it names a
  configured note type, else it is required (never silently guessed). `--slug`
  overrides the filename stem; an existing target is refused unless `--force`.
- The draft identifier is resolved **inside the inbox dir only** — path
  traversal / arbitrary-path args are rejected, so `promote` can never move a
  file from outside the gate.
- The inbox dir name is config-driven (`[inbox] dir`, default `_inbox`) and is
  always excluded from `lint` / `context` / `link` / `stale`, even if renamed
  without a leading underscore.

## Documentation

- 🌐 **[Landing page](https://midhun1998.github.io/memlattice/)** — the pitch, visualized
- 📐 **[Design document](docs/design.md)** — architecture, diagrams, and rationale
- 🤝 **[Contributing](CONTRIBUTING.md)** — dev setup, tests, and PR flow
- 📓 **[Changelog](CHANGELOG.md)**

## Status

**v0.1.** `init`, `new`, `link`, `lint`, `stale`, `context`, `cache`,
`digest`, `doctor`, `refresh` (pluggable source adapters + built-in `git`
adapter), and the review-gated `inbox` / `promote` workflow all work, with a
test suite and CI across Python 3.10–3.12. Config-driven citation schemes and
note types. Roadmap (embedding backend, agentic `verify`) is in the
[design doc](docs/design.md#11-roadmap).

## License

[MIT](LICENSE).
