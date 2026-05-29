<p align="center"><img src="docs/assets/lattice-logo.png" width="180" alt="lattice logo"/></p>

# lattice

> **Your AI agent's long-term memory, in plain markdown. Verified by construction.**

Every Claude Code / Cursor / Aider user ends up writing the same thing: a
sprawling `CLAUDE.md` / `AGENTS.md` / `.cursorrules` that grows into a
2000-line wiki the model never fully reads, riddled with speculation it
later cites as fact. `lattice` is a tiny CLI + markdown convention that
makes that memory **structured, verified, multi-tool, and cheap on
tokens** — without a database, a server, or vendor lock-in.

```
lattice init
lattice new flow checkout
lattice lint        # cited-fact checker, orphan finder
lattice stale       # what's older than 90 days
lattice context     # smallest token-set relevant to a query
lattice digest      # compress .CLAUDE.HISTORY into a re-loadable index
```

## The five opinions

1. **Three layers, mandatory.** `components/` (services), `flows/` (end-to-end
   product paths), `api/` (validated payloads). Loose memory becomes
   structured by construction.
2. **Verification gates.** Every named service / endpoint / fact carries a
   citation. Speculation lives in a quarantined `## Open questions`
   section that physically can't pollute the body. `lattice lint`
   enforces.
3. **Graph by markdown links, not a database.** `[[wikilinks]]` work in
   Obsidian, work for any LLM, work in `grep`. Bidirectional `## Referenced by`
   maintained by the CLI.
4. **Tool-agnostic.** Claude Code, Cursor, Windsurf, Aider, Continue —
   all read the same files. Per-tool entry stubs are thin pointers.
5. **Token-aware.** `lattice context <query>` returns only the smallest
   relevant subgraph, not the whole vault. Frontmatter token budgets
   prevent runaway files. History compression via `lattice digest`.

## Why not just use `CLAUDE.md`, mem0, letta, zep, Obsidian + Smart Connections?

| Tool | What it is | What it misses |
|---|---|---|
| `CLAUDE.md` / `AGENTS.md` | Single dump file | No structure, no verification, grows unbounded |
| mem0 / letta / zep | Hosted runtime memory store | Opaque, not file-native, single-tool |
| Obsidian + Smart Connections | Vault + RAG plugin | Not agent-native, no verification protocol, manual |
| Claude's auto-memory | Per-conversation type-tagged notes | Single-tool, no graph, loose taxonomy |

`lattice` is **a `pre-commit` for agent memory** — convention + small CLI,
not a service. Stays out of your way until your facts drift, then yells.

## Install (planned)

```bash
pipx install memlattice
# or
brew install lattice
```

For now: clone, `pip install -e .`, run `lattice init` in a vault dir.

## 30-second tour

```bash
$ lattice init ~/my-vault
created  components/  flows/  api/  _template.md  _protocol.md  README.md
hint:    add this to your CLAUDE.md / AGENTS.md / .cursorrules:
         "Long-term memory at ~/my-vault. Read _protocol.md before editing."

$ lattice new flow checkout
created  flows/checkout.md (from _template.md)

$ lattice lint
flows/checkout.md: ✗ 3 named services without citations: PaymentGateway, Redis, OrderQueue
flows/checkout.md: ✗ "Open questions" section missing
components/job-runner.md:    ✓ ok
1 file with errors. exit 1.

$ lattice stale --days 90
components/auth-service.md   last_verified=2025-12-04  age=176d
api/billing-payloads.md      last_verified=2026-02-11  age=107d

$ lattice context "how does checkout settle a payment?"
flows/checkout.md           (Phase C, lines 88-114)
components/payment-gateway.md (sections 1-3)
api/billing-payloads.md     (lines matching "settle")
~ 2,140 tokens. (vault total: 47,300)
```

## Status

**v0.0.1 — bootstrap.** CLI surface defined, scaffolding works, lint stub
in place. Eat-your-own-dogfood phase. Public release when v0.1
(`lint` + `stale` + `context` working) ships.

## License

MIT (planned).
