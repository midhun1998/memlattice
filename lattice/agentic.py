"""Agentic helpers — Claude API for richer summarisation, with graceful fallback."""
from __future__ import annotations

import json
import os
import textwrap
from typing import Callable, Optional
from pathlib import Path

CACHE_FILE_NAME = "agentic-stub-cache.json"

# Optional spend-gating seam. `pre_spend` is consulted BEFORE the Claude client
# is constructed: it returns True to allow the call, False to block it (the
# caller degrades to the heuristic). `post_spend` is invoked AFTER a successful
# call so the local budget ledger can record the estimated cost. Both default to
# None (no gating) so this module stays usable standalone; the CLI injects the
# circuit-breaker. The client is NEVER constructed when pre_spend returns False.
PreSpend = Optional[Callable[[], bool]]
PostSpend = Optional[Callable[[], None]]


def _cache_path(vault: Path | None) -> Path | None:
    if vault is None:
        return None
    d = vault / ".lattice" / "cache"
    d.mkdir(parents=True, exist_ok=True)
    return d / CACHE_FILE_NAME


def _load_cache(vault: Path | None) -> dict[str, str]:
    p = _cache_path(vault)
    if p and p.exists():
        try:
            return json.loads(p.read_text())
        except json.JSONDecodeError:
            return {}
    return {}


def _save_cache(vault: Path | None, cache: dict[str, str]) -> None:
    p = _cache_path(vault)
    if p:
        p.write_text(json.dumps(cache, indent=2))


def _hash(text: str) -> str:
    import hashlib
    return hashlib.sha256(text.encode()).hexdigest()[:16]


PROMPT = textwrap.dedent("""\
    Compress this Claude Code session log into exactly 5 bullets, in this order:
    1. **Done** — what was actually completed (one short clause)
    2. **Files** — files changed, comma-separated paths only
    3. **Learned** — one citation-worthy fact (a fact future sessions should
       remember; only include if there really is one — otherwise write
       "Learned: -")
    4. **Open** — what is unfinished or blocked
    5. **Next** — concrete next action

    Constraints:
    - Each bullet ONE LINE only, max 120 chars.
    - No preamble, no headings, no commentary.
    - Output exactly 5 lines starting with "- **Done**:" / "- **Files**:" / etc.
    - If the session log lacks info for a bullet, write "- **<Label>**: -"

    Session log:
    ---
    {body}
    ---
""")


# Module-level handle so callers/tests can patch `agentic.Anthropic`. Resolved
# lazily inside _make_client so the optional `anthropic` dep stays guarded and
# absent installs degrade gracefully.
Anthropic = None  # type: ignore[assignment]


def _make_client(key: str):
    """Construct the Claude client, honoring a monkeypatched module-level
    `Anthropic` if one is set; otherwise lazily import the real SDK. Returns
    None when the SDK is unavailable. The construction is the actual spend
    trigger — gating MUST happen before this is called."""
    cls = globals().get("Anthropic")
    if cls is None:
        try:
            from anthropic import Anthropic as cls  # type: ignore
        except ImportError:
            return None
    return cls(api_key=key)


def agentic_stub(
    body: str,
    vault: Path | None = None,
    use_cache: bool = True,
    pre_spend: PreSpend = None,
    post_spend: PostSpend = None,
) -> str | None:
    """Return a 5-line stub via Claude API, or None if unavailable.

    Caches by content hash unless use_cache=False. Reads ANTHROPIC_API_KEY.

    Spend gating: if `pre_spend` is provided and returns False, the Claude
    client is NEVER constructed and None is returned (caller degrades). A cache
    hit costs nothing, so it is served regardless of the gate. After a
    successful, validated call, `post_spend` (if any) records the spend.
    """
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return None
    cache = _load_cache(vault) if use_cache else {}
    h = _hash(body)
    if use_cache and h in cache:
        return cache[h]
    # Consult the cost circuit-breaker BEFORE any spend. A False decision means
    # we must not construct the client — degrade silently to the heuristic.
    if pre_spend is not None and not pre_spend():
        return None
    try:
        client = _make_client(key)
        if client is None:
            return None
        msg = client.messages.create(
            model=os.environ.get("LATTICE_DIGEST_MODEL", "claude-haiku-4-5-20251001"),
            max_tokens=400,
            messages=[{"role": "user", "content": PROMPT.format(body=body[:8000])}],
        )
        text = "".join(b.text for b in msg.content if hasattr(b, "text")).strip()
    except Exception as e:  # network, auth, rate-limit — fall back gracefully
        print(f"[lattice] agentic stub failed: {e}; falling back to heuristic")
        return None
    # validate shape — must be 5 lines starting with "- **"
    lines = [l for l in text.splitlines() if l.strip().startswith("- **")]
    if len(lines) < 5:
        return None
    if post_spend is not None:
        post_spend()
    out = "\n".join(f"  {l}" for l in lines[:5])
    if use_cache:
        cache[h] = out
        _save_cache(vault, cache)
    return out


DISTILL_PROMPT = textwrap.dedent("""\
    Summarise the following source item into ONE neutral sentence (max 200
    chars) describing what changed or happened. Do NOT invent facts, do NOT add
    citations or links, do NOT add commentary or preamble. Output the sentence
    only.

    Source item:
    ---
    {body}
    ---
""")


def agentic_distill(raw_text: str, vault: Path | None = None, use_cache: bool = True) -> str | None:
    """Distil a raw source item to one neutral summary line via the Claude API,
    or None when unavailable (no key, no SDK, or any API error).

    Reuses the same cache plumbing + ANTHROPIC_API_KEY gating as agentic_stub,
    so `lattice refresh` degrades to a pure heuristic with zero cost when no key
    is set. The summary is intentionally NOT a citation — refresh keeps drafts
    uncited regardless of what this returns.
    """
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return None
    cache = _load_cache(vault) if use_cache else {}
    h = "distill:" + _hash(raw_text)
    if use_cache and h in cache:
        return cache[h]
    try:
        from anthropic import Anthropic
    except ImportError:
        return None
    try:
        client = Anthropic(api_key=key)
        msg = client.messages.create(
            model=os.environ.get("LATTICE_DIGEST_MODEL", "claude-haiku-4-5-20251001"),
            max_tokens=150,
            messages=[{"role": "user", "content": DISTILL_PROMPT.format(body=raw_text[:8000])}],
        )
        text = "".join(b.text for b in msg.content if hasattr(b, "text")).strip()
    except Exception as e:  # network, auth, rate-limit — degrade to heuristic
        print(f"[lattice] agentic distill failed: {e}; falling back to heuristic")
        return None
    text = text.splitlines()[0].strip() if text else ""
    if not text:
        return None
    out = text[:200]
    if use_cache:
        cache[h] = out
        _save_cache(vault, cache)
    return out
