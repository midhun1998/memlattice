# lattice — 90-second screencast script

**Goal:** in 90 seconds make a Claude / Cursor / Aider user say
"I need this." Pain → demo → close.

**Format:** terminal screen recording, no talking head, captions burned
in. asciinema or QuickTime + ffmpeg.

---

## 0:00 — 0:08  Hook  (8s)

**Screen:** scroll a 1,800-line `CLAUDE.md` file fast.

**Caption:**
> Every Claude Code project ends here. A 1,800-line CLAUDE.md the model
> never fully reads. With facts that are out of date, speculation it
> cites as truth, and zero structure.

---

## 0:08 — 0:18  The other half of the pain  (10s)

**Screen:** open a `.CLAUDE.HISTORY`, scroll, scroll, scroll. Show file
size: `127 KB`.

**Caption:**
> Plus a `.CLAUDE.HISTORY` that grows forever and silently eats your
> token budget on every new session.

---

## 0:18 — 0:30  The fix, in two commands  (12s)

**Screen:** terminal.

```
$ pipx install memlattice
$ lattice init my-vault
vault initialised at my-vault
  created: _protocol.md, _template.md, README.md, .lattice/config.toml
```

**Caption:** > Three folders. components/, flows/, api/. One protocol
> file the agent reads before editing. Plain markdown. No DB, no server.

---

## 0:30 — 0:50  The core idea  (20s)

**Screen:** type `lattice new flow checkout`, open the file, point
at frontmatter + Open questions section.

```
---
type: flow
last_verified: 2026-05-29
related: []
---

# checkout
…
## 7. Open questions
- [ ] (2026-05-29) ...
## 8. Referenced by
```

**Caption:**
> Verified facts go in the body — every named service needs a citation.
> Speculation goes in `Open questions`, dated. `lattice lint` enforces
> it. Speculation can't pollute the body by accident.

---

## 0:50 — 1:10  The win — token-aware retrieval  (20s)

**Screen:**
```
$ lattice context "how does the spark job submit to payment-gateway?"
--- flows/checkout.md (Phase C, ~1180 tok) ---
…
--- components/payment-gateway.md (sections 1-3, ~520 tok, link-hop) ---
…
# total: ~2140 / 4000 tokens, 3 files
```

**Caption:**
> Instead of dumping a 47K-token vault into your session, lattice
> finds the smallest relevant subgraph. BM25 + one-hop graph
> traversal across `[[wikilinks]]`. Fits in 4K tokens. No vector DB.

---

## 1:10 — 1:25  History compression  (15s)

**Screen:**
```
$ lattice digest .CLAUDE.HISTORY --keep-recent 3
digest: 31,400 -> 6,200 tokens (80% reduction)
…
$ lattice digest .CLAUDE.HISTORY --keep-recent 3 --write
wrote .CLAUDE.HISTORY; backup at .CLAUDE.HISTORY.bak
```

**Caption:**
> Old sessions become 5-line stubs that link to full archives. Last 3
> sessions stay verbatim. Sessions older than that no longer eat
> context on every cold start.

---

## 1:25 — 1:30  Close  (5s)

**Screen:** static frame, logo, three lines:

```
memlattice  —  pipx install memlattice
github.com/midhun1998/lattice
MIT
```

**Caption:**
> Plain markdown. Verified by construction. Tool-agnostic.
> Try it.

---

## Production notes

- Keep typing speed natural — no unrealistic 2-cps demos.
- Use a real vault with 5-10 notes; viewers can tell when it's empty.
- `asciinema rec` then `agg` to GIF, or QuickTime + ffmpeg to MP4.
- Aspect 16:9, font ≥ 16pt, dark background, no shell prompt clutter
  (use `PS1="$ "`).
- Subtitles burned in — most LinkedIn / Twitter views are muted.
