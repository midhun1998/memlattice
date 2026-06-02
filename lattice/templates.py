"""Embedded scaffold templates."""

PROTOCOL_MD = """\
---
type: protocol
last_verified: {today}
---

# Update Protocol

Applies to every file in this vault.

1. **Read fully before editing.** Update in place when the topic has a home.
2. **Verified content only in the main body.** Verification = code read,
   primary doc, log trace, or dated conversation.
3. **Speculation -> `## Open questions`.** Dated, labeled. Graduates only
   after verification.
4. **Cite sources.** Every named service / repo / endpoint gets a
   citation token: `[file:path]`, `[doc:url]`, `[url:link]`,
   `[commit:sha]`, `[pr:owner/repo#n]`, `[conv:person:date]`. Add your
   own schemes (jira, linear, ...) via `[citations] extra` in config.
5. **Datestamp updates.** Bump `last_verified` in frontmatter on edit.
6. **Never silently delete.** Use strikethrough +
   `(superseded YYYY-MM-DD: ...)`.
7. **Maintain `## Referenced by`.** `lattice link --fix` does this for you.
8. **End-of-session check.** Propose updates before closing.
"""

TEMPLATE_MD = """\
---
type: flow
last_verified: {today}
related: []
---

# <Flow name>

## 1. Scope & boundaries
What this covers. What it does NOT (and which file does).

## 2. End-to-end diagram
ASCII. Service names, transports, namespaces.

## 3. Touch points

| Service | Repo | In | Out | Auth | Logs | Owner |
|---|---|---|---|---|---|---|

## 4. Phase-by-phase narrative

### Phase A
### Phase B

## 5. Extension points
"If you want to add X, the seam is here."

## 6. Failure modes & where to look

| Symptom | Likely cause | Where to look |
|---|---|---|

## 7. Open questions
- [ ] (YYYY-MM-DD) ...

## 8. Referenced by
"""

README_MD = """\
# {name}

Long-term memory vault for AI coding agents. Managed by
[lattice](https://github.com/midhun1998/memlattice).

- `components/` per-service notes
- `flows/` end-to-end product paths
- `api/` validated endpoints / payloads
- `_protocol.md` update rules (READ before editing)
- `_template.md` skeleton for new flow files

Tell your agent:

> Long-term memory at `{path}`. Read `_protocol.md` before editing.
> Run `lattice context "<query>"` to load only the relevant subset.
"""

INBOX_STUB = """\
---
type: inbox-draft
status: needs-citation
source: {source}
ref: {ref}
---

# DRAFT (uncited): {title}

> [!warning] Review item — NOT verified knowledge.
> This stub was drafted by `lattice refresh` from a source item. It is
> deliberately UNCITED and lives in `_inbox/` (excluded from the note graph).
> To promote it: verify the claim, add a real citation token, rewrite it into
> the right note body, then delete this file. Do NOT link to it.

- [ ] TODO: verify and add a citation, then promote into a note body.

## Summary
{summary}

## Raw source
```
{raw}
```
"""

CONFIG_TOML = """\
[budgets]
file_warn = 6000
file_max = 12000
context_default = 4000

# Retrieval ranking for `lattice context` (and the offline `lattice cache`).
# `ranker` is a three-way switch, default "auto":
#   auto       -> use the OPTIONAL local-embedding ranker iff its extra is
#                 installed AND `ranker` here is not "bm25"; otherwise BM25.
#   bm25       -> always the built-in BM25 path (no extra needed).
#   embeddings -> force the local-embedding ranker; if the extra is not
#                 installed it prints one notice and degrades to BM25 (never
#                 errors). Install it with: pip install "memlattice[embeddings]".
# The embedding ranker is fully local (no hosted API, no server, no spend).
# `embedding_model` is a model id OR a local path (leave empty to use the
# built-in default resolved by lattice). `embedding_cache` persists per-note
# vectors under .lattice/cache/ (gitignored) so re-runs skip re-encoding.
# `lattice context --ranker {auto|bm25|embeddings}` overrides per-invocation.
[context]
# ranker          = "auto"
# embedding_model = ""
# embedding_cache = true

[lint]
require_citations = true
require_open_questions = true
require_referenced_by = true

# Outcome feedback loop. `lattice used <slug> [<slug>...] [--bad]` records
# local-only outcomes to .lattice/cache/outcomes.jsonl (gitignored, never sent
# anywhere). `lattice context` then applies a small, recency-decayed multiplier
# so recently/positively-used notes rank slightly higher (--bad penalizes).
# On by default but deliberately conservative — it can only nudge, never flip
# strong BM25 signal. Disable per-invocation with `context --no-learn`.
[learn]
enabled = true
boost = 0.15           # max positive uplift: a fresh good outcome -> score * (1 + boost)
penalty = 0.30         # max downweight for a fresh --bad outcome (floored above zero)
half_life_days = 30    # outcome weight = 0.5 ** (age_days / half_life_days)

# Note types -> their directory. The three below are the built-in defaults;
# uncomment/extend to add your own (the dir is created on first `lattice new`).
[types]
# runbook  = "runbooks"
# decision = "decisions"

# Citation schemes. Defaults are vendor-neutral: file, doc, url, commit, pr,
# conv, chat. Add the source systems YOUR team cites so `lattice lint` accepts
# them, e.g. jira / linear / notion / confluence.
[citations]
# extra = ["jira", "confluence"]

# Source adapters for `lattice refresh` (explicit, opt-in, default OFF).
# `lattice refresh` only runs when you type it — there is no scheduler/daemon.
# With NO entries below it is a no-op. Each entry names an adapter and its
# options; drafts land in _inbox/ as UNCITED review stubs (never note bodies).
# The built-in `git` adapter is local-only: no network, no auth. Third-party
# adapters install as separate packages registering under the entry-point group
# "lattice.adapters" (installing one runs its code — a trust boundary).
[sources]
# [sources.repo]
# adapter = "git"
# path    = "."             # repo to scan, relative to the vault
# branch  = "main"          # optional; defaults to HEAD
# paths   = ["docs/", "src/"]  # optional path filter

# Refresh behaviour. `distill` toggles the optional Claude distillation (no-ops
# without ANTHROPIC_API_KEY); `limit` caps drafted items per source to bound
# cost / inbox spam.
[refresh]
# distill   = true
# limit     = 50

# Review-gated draft inbox. `lattice refresh` drops UNCITED stubs here; review
# them with `lattice inbox` and `lattice promote <draft> --type <type>` to turn
# one into a real templated note (which STILL must earn citations to pass lint).
# `dir` is the single source of truth for the inbox directory name and is always
# excluded from the verified-corpus scan (lint/context/link/stale), even if you
# rename it without a leading underscore. Left fully commented so the default is
# the built-in "_inbox"; uncomment the whole block to relocate the gate.
# [inbox]
# dir = "_inbox"

# Run scripts after a lattice command finishes successfully.
# Available events: post-init, post-new, post-link, post-lint, post-stale,
#                   post-context, post-digest, post-cache, post-doctor,
#                   post-used, post-refresh, post-inbox, post-promote.
# Each entry is a shell command. Working dir = vault root.
# Useful env vars passed in:
#   LATTICE_VAULT, LATTICE_EVENT, LATTICE_ARGS,
#   LATTICE_OUTPUT_FILE (post-context, post-cache only)
[hooks]
# post-context = "cp $LATTICE_OUTPUT_FILE .lattice/cache/last-context.md"
# post-link    = "git add -A && git -c commit.gpgsign=false commit -m 'lattice: refresh backlinks' || true"

# Offline cache: pre-render context manifests for these queries on
# `lattice cache --build`. Files land in .lattice/cache/queries/<slug>.md
# so the agent can read them with no network / no Python / no live BM25.
[cache.queries]
# checkout-flow    = "how does checkout settle a payment end to end"
# auth-overview    = "auth service token issuance refresh"
# billing-payloads = "billing api request response examples"
"""
