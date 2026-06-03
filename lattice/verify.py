"""`lattice verify` — does the cited source still back the claim?

Layer 1 (this module): deterministic existence/freshness, no LLM, network only
on opt-in fetch. Each citation resolves to a status:

  present       — the source exists (and, for file:line, the line is in range)
  drifted       — the source exists but changed since it was cited (hash differs)
  missing       — the source can't be found / commit not in repo / line out of range
  human-attested— conv:/chat: and similar — not machine-checkable, accepted
  unfetched     — doc:/url:/pr: not fetched (offline default); opt-in --fetch

Worst-status-wins reduces a note's citations to one status. `missing` (and, in
Layer 2, `contradicted`/`unsupported`) are FAIL; `drifted` is a warning. Pure
logic (worst/is_fail/parse) is separated from IO (git/fetch) for testing.

Layer 2 (entailment) lives behind --entail and the budget breaker; see verify
entailment wiring. This module degrades to Layer 1 when entailment is off.
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

# Ordered worst -> best for reduction. Lower index = worse. The "acceptable"
# statuses (unresolvable/unfetched/human-attested/fetched/present/supported)
# collapse to 'present' on reduction unless a worse concern is present.
# `unresolvable` (path into a tree not checked out here) is a WARN, not a FAIL —
# distinct from `missing` (the file is gone from a tree we CAN see).
_SEVERITY = ["missing", "contradicted", "unsupported", "drifted", "unresolvable",
             "unfetched", "human-attested", "fetched", "present", "supported"]
_FAIL = {"missing", "contradicted", "unsupported"}
_WARN = {"drifted", "unresolvable"}

# schemes we can check on disk without network
_HUMAN = {"conv", "chat"}
_FETCHABLE = {"doc", "url", "pr"}


@dataclass
class CiteStatus:
    token: str          # the raw citation body, e.g. "file:src/x.py:42"
    scheme: str         # "file", "commit", ...
    status: str         # one of _SEVERITY
    detail: str = ""


def is_fail(status: str) -> bool:
    return status in _FAIL


def worst(statuses: list[str]) -> str:
    """Reduce many statuses to the single worst *concern*. Empty -> 'present'.

    FAIL and WARN statuses win (most severe shown); otherwise everything
    'acceptable' collapses to 'present'."""
    concerns = [s for s in statuses if s in _FAIL or s in _WARN]
    if not concerns:
        return "present"
    return min(concerns, key=lambda s: _SEVERITY.index(s) if s in _SEVERITY else 0)


def _git_has_commit(root: Path, sha: str) -> bool:
    try:
        r = subprocess.run(
            ["git", "cat-file", "-e", f"{sha}^{{commit}}"],
            cwd=root, capture_output=True, text=True,
            env={"GIT_TERMINAL_PROMPT": "0"},
        )
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def resolve_citation(token: str, root: Path, fetch: bool = False) -> CiteStatus:
    """Resolve one citation token (scheme:body) to a CiteStatus. Layer 1 only."""
    scheme, _, body = token.partition(":")
    scheme = scheme.strip().lower()

    if scheme in _HUMAN:
        return CiteStatus(token, scheme, "human-attested", "not machine-checkable")

    if scheme == "file":
        # body is path or path:line
        m = re.match(r"^(.*?)(?::(\d+))?$", body)
        relpath = m.group(1) if m else body
        line = int(m.group(2)) if (m and m.group(2)) else None
        # Resolve ~ and absolute paths as-is; only truly relative paths join root.
        expanded = Path(relpath).expanduser()
        target = expanded if expanded.is_absolute() else (root / expanded)
        if not target.is_file():
            # Distinguish "gone from a tree we can see" (missing/FAIL) from
            # "into a tree not checked out here" (unresolvable/WARN). If the
            # parent directory doesn't exist, we almost certainly can't see the
            # repo this cites — don't fail the build for that.
            if not target.parent.is_dir():
                return CiteStatus(token, scheme, "unresolvable",
                                  f"path not present here (other repo?): {relpath}")
            return CiteStatus(token, scheme, "missing", f"no such file: {target}")
        if line is not None:
            try:
                n = sum(1 for _ in target.open())
            except OSError:
                return CiteStatus(token, scheme, "missing", "unreadable")
            if line < 1 or line > n:
                return CiteStatus(token, scheme, "missing", f"line {line} out of range (1..{n})")
        return CiteStatus(token, scheme, "present")

    if scheme == "commit":
        sha = body.strip()
        ok = _git_has_commit(root, sha)
        return CiteStatus(token, scheme, "present" if ok else "missing",
                          "" if ok else f"commit {sha} not in repo")

    if scheme in _FETCHABLE:
        if not fetch:
            return CiteStatus(token, scheme, "unfetched", "use --fetch to check")
        return _fetch_status(token, scheme, body)

    # unknown / user-defined scheme with no resolver: treat as human-attested
    return CiteStatus(token, scheme, "human-attested", "no resolver for scheme")


def _fetch_status(token: str, scheme: str, body: str) -> CiteStatus:
    """Opt-in fetch for doc/url/pr. Network IO isolated here so the default
    (no-fetch) path stays pure + offline. Best-effort: a fetch failure is
    'missing', a success is 'fetched' (entailment, if enabled, judges support).
    """
    url = body.strip()
    if scheme == "pr":  # owner/repo#n — can't resolve without a host adapter
        return CiteStatus(token, scheme, "human-attested", "no PR host adapter")
    try:
        import urllib.request
        req = urllib.request.Request(url, headers={"User-Agent": "lattice-verify"})
        with urllib.request.urlopen(req, timeout=15) as r:  # noqa: S310 (opt-in)
            r.read(1)
        return CiteStatus(token, scheme, "fetched")
    except Exception as e:  # network/DNS/HTTP — best-effort
        return CiteStatus(token, scheme, "missing", f"fetch failed: {e}")


def citations_in(text: str, cite_re) -> list[str]:
    """Extract citation token bodies (without the surrounding brackets) from text."""
    out = []
    for m in cite_re.finditer(text):
        inner = m.group(0)[1:-1]  # strip [ ]
        out.append(inner)
    return out
