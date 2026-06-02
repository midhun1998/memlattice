"""Optional local-embedding ranker for `lattice context`.

Shipped as the `memlattice[embeddings]` extra. The heavy backend
(sentence-transformers, which transitively drags torch + numpy) is NEVER a core
dependency: every import here is guarded inside the functions, so the package
imports and the full CLI runs with zero extras installed. When the backend is
absent, disabled, or fails to load, `embedding_scores` returns ``None`` — never
raising — so callers fall back to BM25 silently.

This re-ranks which EXISTING note sections get surfaced; it never writes to a
note body, so lattice's citation/verification invariant is untouched. It is
fully local: no hosted API, no server, no spend. The only network touch is the
backend's first-run model-weight download (the model id is config-driven so
air-gapped users can point at a local path).

The default model id is resolved HERE and nowhere else — core (cli.py /
config.py) must never reference a vendor/model literal, honoring the
no-hardcoded-vendor rule.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Sequence

# The documented default local model. Resolved only inside this module; never
# referenced by name in cli.py / config.py. A small general-purpose sentence
# model that runs locally on CPU. Override via `[context] embedding_model`
# (a model id or a local path, for air-gapped use).
DEFAULT_EMBEDDING_MODEL = "all-MiniLM-L6-v2"

_CACHE_FILE_NAME = "embedding-cache.json"

# Process-local model cache so repeated calls in one run don't reload weights.
_MODEL_CACHE: dict[str, Any] = {}


def resolve_model(name: str | None) -> str:
    """Return the model id to use: the configured one, else the default.

    The default literal lives ONLY here, so core never hardcodes a vendor/model
    name."""
    if isinstance(name, str) and name.strip():
        return name.strip()
    return DEFAULT_EMBEDDING_MODEL


def backend_available() -> bool:
    """True iff the embeddings extra (and numpy) import cleanly. Never raises."""
    try:
        import numpy  # noqa: F401
        import sentence_transformers  # noqa: F401
    except Exception:
        return False
    return True


def _cache_path(vault: Path | None) -> Path | None:
    if vault is None:
        return None
    d = vault / ".lattice" / "cache"
    d.mkdir(parents=True, exist_ok=True)
    return d / _CACHE_FILE_NAME


def _load_cache(vault: Path | None) -> dict[str, list[float]]:
    p = _cache_path(vault)
    if p and p.exists():
        try:
            data = json.loads(p.read_text())
            return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save_cache(vault: Path | None, cache: dict[str, list[float]]) -> None:
    p = _cache_path(vault)
    if p:
        try:
            p.write_text(json.dumps(cache))
        except OSError:
            pass


def _doc_key(model: str, text: str) -> str:
    """Cache key keyed by model id + content hash (per the spec)."""
    h = hashlib.sha256((model + "\0" + text).encode("utf-8")).hexdigest()[:24]
    return f"{model}:{h}"


def embedding_scores(
    query: str,
    docs: Sequence[str],
    model: str | None = None,
    *,
    vault: Path | None = None,
    use_cache: bool = True,
) -> list[float] | None:
    """Return per-doc cosine similarities to ``query``, or ``None`` on any
    failure (missing extra, missing numpy, model load/encode error).

    Returning ``None`` is the silent-fallback contract: callers degrade to
    BM25. The heavy imports (sentence-transformers + numpy) are performed HERE,
    behind try/except, so module import never requires the extra.

    Per-doc vectors are cached under ``.lattice/cache/`` keyed by
    model-id + content hash (mirroring agentic.py's cache) when ``use_cache``
    and a ``vault`` is given, so re-running the same query over an unchanged
    vault skips re-encoding. The query vector is never cached.
    """
    if not docs:
        return None
    try:
        import numpy as np
        from sentence_transformers import SentenceTransformer
    except Exception:
        return None

    model_id = resolve_model(model)
    try:
        st_model = _MODEL_CACHE.get(model_id)
        if st_model is None:
            st_model = SentenceTransformer(model_id)
            _MODEL_CACHE[model_id] = st_model

        cache = _load_cache(vault) if use_cache else {}
        cache_dirty = False

        doc_vecs: list[list[float]] = []
        to_encode: list[str] = []
        to_encode_idx: list[int] = []
        placeholder: list[float] = []
        for i, text in enumerate(docs):
            key = _doc_key(model_id, text)
            cached = cache.get(key) if use_cache else None
            if isinstance(cached, list) and cached:
                doc_vecs.append(cached)
            else:
                doc_vecs.append(placeholder)  # filled after encoding
                to_encode.append(text)
                to_encode_idx.append(i)

        if to_encode:
            fresh = st_model.encode(to_encode, convert_to_numpy=True)
            fresh = np.asarray(fresh, dtype="float32")
            for j, idx in enumerate(to_encode_idx):
                vec = fresh[j].tolist()
                doc_vecs[idx] = vec
                if use_cache:
                    cache[_doc_key(model_id, docs[idx])] = vec
                    cache_dirty = True

        q_vec = np.asarray(
            st_model.encode([query], convert_to_numpy=True), dtype="float32"
        )[0]

        mat = np.asarray(doc_vecs, dtype="float32")
        q_norm = float(np.linalg.norm(q_vec))
        doc_norms = np.linalg.norm(mat, axis=1)
        denom = doc_norms * q_norm
        # avoid divide-by-zero for empty/degenerate vectors
        with np.errstate(divide="ignore", invalid="ignore"):
            sims = (mat @ q_vec) / denom
        sims = np.nan_to_num(sims, nan=0.0, posinf=0.0, neginf=0.0)

        if use_cache and cache_dirty:
            _save_cache(vault, cache)
        return [float(s) for s in sims.tolist()]
    except Exception:
        # Any backend error (download failure, OOM, encode crash) -> fall back.
        return None
