"""Agentic helpers — Claude API for richer summarisation, with graceful fallback."""
from __future__ import annotations

import json
import os
import textwrap
from pathlib import Path

CACHE_FILE_NAME = "agentic-stub-cache.json"


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


def agentic_stub(body: str, vault: Path | None = None) -> str | None:
    """Return a 5-line stub via Claude API, or None if unavailable.

    Caches by content hash. Reads ANTHROPIC_API_KEY from env.
    """
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return None
    cache = _load_cache(vault)
    h = _hash(body)
    if h in cache:
        return cache[h]
    try:
        from anthropic import Anthropic
    except ImportError:
        return None
    try:
        client = Anthropic(api_key=key)
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
    out = "\n".join(f"  {l}" for l in lines[:5])
    cache[h] = out
    _save_cache(vault, cache)
    return out
