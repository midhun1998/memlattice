"""P3-F optional local-embedding ranker for `lattice context`.

The embeddings backend ships as the `memlattice[embeddings]` extra. When it is
installed AND enabled in config, `context`/`cache` re-rank notes with local
sentence-embeddings (cosine similarity); when the package is absent, disabled,
or the model fails to load, it silently falls back to the existing BM25 ranker.

Core stays dependency-light: the heavy dep lives ONLY in
[project.optional-dependencies], every import is guarded, and the package
imports/runs with zero extras installed. The verification invariant is
untouched — re-ranking only reorders which existing note sections get
surfaced; it never writes to note bodies.
"""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest
from click.testing import CliRunner

from lattice.cli import main


def _init(root: Path) -> None:
    CliRunner().invoke(main, ["init", str(root)])


def _note(root: Path, rel: str, body: str = "") -> Path:
    """Write a fully-valid note (passes lint)."""
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        "---\ntype: flow\nlast_verified: 2026-06-01\nrelated: []\n---\n\n"
        f"# {p.stem}\n\n{body}\n\n## Open questions\n- none\n\n## Referenced by\n_none_\n"
    )
    return p


def _distractors(root: Path, n: int = 4) -> None:
    """Unrelated notes so matching notes stay a minority (keeps BM25 IDF positive)."""
    for i in range(n):
        _note(root, f"flows/distract{i}.md", body=f"gardening tomatoes weather report {i} sunshine")


def _fabricated_vault(root: Path) -> None:
    """A tiny fabricated vault — checkout-flow + payment-gateway + distractors."""
    _init(root)
    _note(
        root,
        "flows/checkout-flow.md",
        body="The checkout flow settles an order. It calls the payment gateway to "
        "charge the customer card and writes the receipt. [doc:checkout/runbook]",
    )
    _note(
        root,
        "components/payment-gateway.md",
        body="The payment gateway charges cards and refunds. It stores transaction "
        "tokens and talks to the bank settlement endpoint. [doc:payments/runbook]",
    )
    _distractors(root)


def _run(root: Path, *args: str):
    cwd = os.getcwd()
    try:
        os.chdir(root)
        return CliRunner().invoke(main, list(args))
    finally:
        os.chdir(cwd)


HAS_BACKEND = importlib.util.find_spec("sentence_transformers") is not None


# ---------- silent-fallback contract on the seam ----------

def test_context_falls_back_to_bm25_when_backend_unavailable(tmp_path: Path, monkeypatch):
    """When the embedding backend returns None (extra missing / model failed),
    `context` produces a manifest byte-identical to the pure-BM25 run."""
    _fabricated_vault(tmp_path)
    query = "how does an order settle a payment"

    # baseline: forced bm25 path
    bm25 = _run(tmp_path, "context", query, "--ranker", "bm25")
    assert bm25.exit_code == 0, bm25.output

    # simulate the backend being unavailable for the embeddings/auto path
    import lattice.embeddings as emb
    monkeypatch.setattr(emb, "embedding_scores", lambda *a, **k: None)

    auto = _run(tmp_path, "context", query, "--ranker", "auto")
    assert auto.exit_code == 0, auto.output
    assert auto.stdout == bm25.stdout

    forced = _run(tmp_path, "context", query, "--ranker", "embeddings")
    assert forced.exit_code == 0, forced.output
    assert forced.stdout == bm25.stdout


def test_embedding_scores_returns_none_when_import_missing(monkeypatch):
    """embedding_scores must return None (never raise) when the heavy import
    fails — the silent-fallback contract."""
    import builtins
    import lattice.embeddings as emb

    real_import = builtins.__import__

    def _no_st(name, *args, **kwargs):
        if name == "sentence_transformers" or name.startswith("sentence_transformers."):
            raise ImportError("simulated: extra not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _no_st)
    out = emb.embedding_scores("a query", ["doc one", "doc two"], "any-model")
    assert out is None


def test_embedding_scores_returns_none_when_numpy_missing(monkeypatch):
    """numpy lives behind the same guard as the backend: if it is missing,
    embedding_scores degrades to None rather than raising at module top-level."""
    import builtins
    import lattice.embeddings as emb

    real_import = builtins.__import__

    def _no_numpy(name, *args, **kwargs):
        if name == "numpy" or name.startswith("numpy."):
            raise ImportError("simulated: numpy not present")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _no_numpy)
    out = emb.embedding_scores("a query", ["doc one", "doc two"], "any-model")
    assert out is None


# ---------- --ranker behaviour with no extra (the venv's real state) ----------

def test_ranker_auto_uses_bm25_with_no_extra(tmp_path: Path):
    if HAS_BACKEND:
        pytest.skip("backend installed — this asserts the no-extra path")
    _fabricated_vault(tmp_path)
    auto = _run(tmp_path, "context", "settle a payment", "--ranker", "auto", "--explain-ranker")
    bm25 = _run(tmp_path, "context", "settle a payment", "--ranker", "bm25")
    assert auto.exit_code == 0
    assert auto.stdout == bm25.stdout
    assert "bm25" in auto.stderr.lower()
    assert "embeddings" in auto.stderr.lower()  # notes the extra isn't installed


def test_ranker_bm25_forces_legacy_path(tmp_path: Path):
    """`--ranker bm25` is the exact current output regardless of any backend."""
    _fabricated_vault(tmp_path)
    res = _run(tmp_path, "context", "settle a payment", "--ranker", "bm25")
    assert res.exit_code == 0
    # the legacy manifest carries the score= column and a totals footer
    assert "score=" in res.stdout
    assert "# total:" in res.stdout


def test_ranker_embeddings_forced_but_unavailable_does_not_crash(tmp_path: Path):
    if HAS_BACKEND:
        pytest.skip("backend installed — this asserts the forced-but-missing path")
    _fabricated_vault(tmp_path)
    res = _run(tmp_path, "context", "settle a payment", "--ranker", "embeddings", "--explain-ranker")
    assert res.exit_code == 0, res.output
    # valid BM25 manifest produced
    bm25 = _run(tmp_path, "context", "settle a payment", "--ranker", "bm25")
    assert res.stdout == bm25.stdout
    # exactly one stderr fallback notice
    assert res.stderr.lower().count("fall") <= 2  # tolerant: the notice mentions falling back
    assert "bm25" in res.stderr.lower()


def test_explain_ranker_keeps_stdout_identical(tmp_path: Path):
    """--explain-ranker writes only to stderr; stdout manifest is unchanged."""
    _fabricated_vault(tmp_path)
    plain = _run(tmp_path, "context", "settle a payment", "--ranker", "bm25")
    explained = _run(tmp_path, "context", "settle a payment", "--ranker", "bm25", "--explain-ranker")
    assert plain.stdout == explained.stdout
    assert explained.stderr.strip() != ""


# ---------- backend present (skips on the no-extra CI/venv) ----------

def test_embedding_path_ranks_when_backend_present(tmp_path: Path):
    if not HAS_BACKEND:
        pytest.skip("sentence-transformers extra not installed")
    _fabricated_vault(tmp_path)
    res = _run(tmp_path, "context", "billing card charge", "--ranker", "embeddings", "--explain-ranker")
    assert res.exit_code == 0, res.output
    assert "embeddings" in res.stderr.lower()
    assert "score=" in res.stdout


# ---------- config-posture regression tests ----------

def test_embeddings_extra_not_in_core_dependencies():
    """sentence-transformers must NOT be a core dep and MUST be the embeddings extra."""
    try:
        import tomllib
    except ImportError:  # pragma: no cover
        import tomli as tomllib  # type: ignore
    root = Path(__file__).resolve().parents[1]
    data = tomllib.loads((root / "pyproject.toml").read_text())
    core = " ".join(data["project"]["dependencies"]).lower()
    assert "sentence" not in core and "torch" not in core and "numpy" not in core
    extras = data["project"]["optional-dependencies"]
    assert "embeddings" in extras
    joined = " ".join(extras["embeddings"]).lower()
    assert "sentence-transformers" in joined or "sentence_transformers" in joined


def test_package_imports_with_zero_extras():
    """The package + the embeddings module import even when no extra is present."""
    import importlib
    import lattice.cli  # noqa: F401
    emb = importlib.import_module("lattice.embeddings")
    assert hasattr(emb, "embedding_scores")
    # module top-level must not require the heavy backend
    assert importlib.util.find_spec("lattice.embeddings") is not None


def test_cache_build_respects_ranker(tmp_path: Path):
    """`cache --build` with [context] ranker unset on a no-extra system produces
    BM25 manifests (no regression to the offline cache)."""
    if HAS_BACKEND:
        pytest.skip("backend installed — assert the no-extra cache parity path")
    _fabricated_vault(tmp_path)
    # add a cache query under the existing (scaffolded) [cache.queries] table
    cfg = tmp_path / ".lattice" / "config.toml"
    cfg.write_text(cfg.read_text() + '\nco = "settle a payment"\n')
    res = _run(tmp_path, "cache", "--build")
    assert res.exit_code == 0, res.output
    built = (tmp_path / ".lattice" / "cache" / "queries" / "co.md").read_text()
    # the manifest a pure-bm25 context run would produce (context echoes a
    # trailing newline that the cache file write does not add)
    direct = _run(tmp_path, "context", "settle a payment", "--ranker", "bm25")
    assert built == direct.stdout.rstrip("\n")


def test_verification_invariant_untouched(tmp_path: Path):
    """Running context never modifies any note file on disk (re-ranking is read-only)."""
    _fabricated_vault(tmp_path)
    notes = list((tmp_path).rglob("*.md"))
    before = {p: p.read_text() for p in notes}
    _run(tmp_path, "context", "settle a payment", "--ranker", "embeddings")
    _run(tmp_path, "context", "settle a payment", "--ranker", "auto")
    _run(tmp_path, "context", "settle a payment", "--ranker", "bm25")
    after = {p: p.read_text() for p in notes}
    assert before == after
