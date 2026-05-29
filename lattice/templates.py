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
   citation token: `[file:path]`, `[doc:url]`, `[jira:saved-search]`,
   `[chat:#channel:date]`, `[conv:person:date]`.
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
[lattice](https://github.com/midhun1998/lattice).

- `components/` per-service notes
- `flows/` end-to-end product paths
- `api/` validated endpoints / payloads
- `_protocol.md` update rules (READ before editing)
- `_template.md` skeleton for new flow files

Tell your agent:

> Long-term memory at `{path}`. Read `_protocol.md` before editing.
> Run `lattice context "<query>"` to load only the relevant subset.
"""

CONFIG_TOML = """\
[budgets]
file_warn = 6000
file_max = 12000
context_default = 4000

[lint]
require_citations = true
require_open_questions = true
require_referenced_by = true

# Run scripts after a lattice command finishes successfully.
# Available events: post-init, post-new, post-link, post-lint, post-stale,
#                   post-context, post-digest, post-cache.
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
