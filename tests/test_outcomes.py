"""P2-E outcome feedback loop.

`lattice used <slug> [<slug>...] [--bad]` appends local-only outcome records
to `.lattice/cache/outcomes.jsonl`, and `lattice context` applies a small,
conservative, recency-decayed multiplier on top of BM25 so recently/positively
used notes rank slightly higher and `--bad`-marked notes are slightly
penalized. No telemetry ever leaves the machine. Borrows only the SHAPE of
memgram's memory_outcome(good, ids), not any constants.
"""
from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path

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
    """Add unrelated notes so the matching notes are a minority of the corpus.

    BM25Okapi's IDF goes negative for a term present in more than ~half the
    docs, so a tiny vault where every note matches the query yields negative
    scores (and is gated out). Real vaults have many non-matching notes; these
    distractors reproduce that so query terms keep positive IDF."""
    for i in range(n):
        _note(root, f"flows/distract{i}.md", body=f"gardening tomatoes weather report {i} sunshine")


def _run(root: Path, *args: str):
    cwd = os.getcwd()
    try:
        os.chdir(root)
        return CliRunner().invoke(main, list(args))
    finally:
        os.chdir(cwd)


def _outcomes_path(root: Path) -> Path:
    return root / ".lattice" / "cache" / "outcomes.jsonl"


def _read_records(root: Path) -> list[dict]:
    lines = _outcomes_path(root).read_text().splitlines()
    return [json.loads(l) for l in lines if l.strip()]


# ---------- `lattice used` command ----------

def test_used_appends_record_to_outcomes_jsonl(tmp_path: Path):
    _init(tmp_path)
    _note(tmp_path, "flows/checkout.md")
    res = _run(tmp_path, "used", "checkout")
    assert res.exit_code == 0, res.output
    assert _outcomes_path(tmp_path).exists()
    recs = _read_records(tmp_path)
    assert len(recs) == 1
    rec = recs[0]
    assert rec["slugs"] == ["checkout"]
    assert rec["good"] is True
    # ts must be a parseable ISO-8601 timestamp
    dt.datetime.fromisoformat(rec["ts"])


def test_used_bad_records_negative_outcome(tmp_path: Path):
    _init(tmp_path)
    _note(tmp_path, "flows/checkout.md")
    res = _run(tmp_path, "used", "checkout", "--bad")
    assert res.exit_code == 0, res.output
    recs = _read_records(tmp_path)
    assert recs[0]["good"] is False


def test_used_multiple_slugs_one_record(tmp_path: Path):
    _init(tmp_path)
    _note(tmp_path, "flows/checkout.md")
    _note(tmp_path, "api/payment-gateway.md")
    res = _run(tmp_path, "used", "checkout", "payment-gateway")
    assert res.exit_code == 0, res.output
    recs = _read_records(tmp_path)
    assert len(recs) == 1
    assert set(recs[0]["slugs"]) == {"checkout", "payment-gateway"}


def test_used_rejects_unknown_slug(tmp_path: Path):
    _init(tmp_path)
    _note(tmp_path, "flows/checkout.md")
    res = _run(tmp_path, "used", "does-not-exist")
    assert res.exit_code != 0, res.output
    assert "does-not-exist" in res.output
    # NO record appended for garbage input
    assert not _outcomes_path(tmp_path).exists()


def test_used_appends_not_overwrites(tmp_path: Path):
    _init(tmp_path)
    _note(tmp_path, "flows/checkout.md")
    _run(tmp_path, "used", "checkout")
    _run(tmp_path, "used", "checkout", "--bad")
    recs = _read_records(tmp_path)
    assert len(recs) == 2
    assert recs[0]["good"] is True
    assert recs[1]["good"] is False


def test_used_no_vault_aborts(tmp_path: Path):
    res = _run(tmp_path, "used", "checkout")
    assert res.exit_code == 2, res.output


# ---------- context rank boost ----------

def test_context_boosts_positively_used_note(tmp_path: Path):
    """Two notes ranking closely on BM25; a positive outcome on B lifts it
    above A in the manifest ordering."""
    _init(tmp_path)
    _note(tmp_path, "flows/alpha.md", body="payment settle ledger flow alpha")
    _note(tmp_path, "flows/bravo.md", body="payment settle ledger flow bravo")
    _distractors(tmp_path)
    base = _run(tmp_path, "context", "payment settle ledger flow")
    assert base.exit_code == 0, base.output
    # confirm both present
    assert "alpha.md" in base.output and "bravo.md" in base.output
    # baseline ordering: alpha first (alphabetical tie-break / stable sort)
    assert base.output.index("alpha.md") < base.output.index("bravo.md")
    # now record a positive outcome on bravo
    assert _run(tmp_path, "used", "bravo").exit_code == 0
    boosted = _run(tmp_path, "context", "payment settle ledger flow")
    assert boosted.exit_code == 0, boosted.output
    assert boosted.output.index("bravo.md") < boosted.output.index("alpha.md")


def test_context_no_learn_flag_disables_boost(tmp_path: Path):
    _init(tmp_path)
    _note(tmp_path, "flows/alpha.md", body="payment settle ledger flow alpha")
    _note(tmp_path, "flows/bravo.md", body="payment settle ledger flow bravo")
    _distractors(tmp_path)
    _run(tmp_path, "used", "bravo")
    res = _run(tmp_path, "context", "payment settle ledger flow", "--no-learn")
    assert res.exit_code == 0, res.output
    # pure BM25: alpha stays ahead of bravo
    assert res.output.index("alpha.md") < res.output.index("bravo.md")


def test_bad_outcome_penalizes_but_never_zeroes(tmp_path: Path):
    """A --bad note still appears when it's the only BM25 match — the penalty
    floors above zero, preserving relevance gating."""
    _init(tmp_path)
    _note(tmp_path, "flows/checkout.md", body="checkout settles a payment")
    _distractors(tmp_path)
    _run(tmp_path, "used", "checkout", "--bad")
    res = _run(tmp_path, "context", "checkout payment")
    assert res.exit_code == 0, res.output
    assert "checkout.md" in res.output


def test_boost_is_conservative_does_not_override_strong_bm25(tmp_path: Path):
    """A note with a much higher BM25 score is NOT overtaken by a weakly
    matching note that has a positive outcome (boost cap can't flip big gaps)."""
    _init(tmp_path)
    # strong: query terms appear many times
    _note(tmp_path, "flows/strong.md", body="payment payment payment settle settle ledger flow")
    # weak: a single passing match
    _note(tmp_path, "flows/weak.md", body="payment occasionally mentioned once here")
    _distractors(tmp_path)
    _run(tmp_path, "used", "weak")  # positive outcome on the weak note
    res = _run(tmp_path, "context", "payment settle ledger flow")
    assert res.exit_code == 0, res.output
    assert "strong.md" in res.output and "weak.md" in res.output
    assert res.output.index("strong.md") < res.output.index("weak.md")


def test_learn_disabled_in_config_no_boost(tmp_path: Path):
    _init(tmp_path)
    (tmp_path / ".lattice" / "config.toml").write_text("[learn]\nenabled = false\n")
    _note(tmp_path, "flows/alpha.md", body="payment settle ledger flow alpha")
    _note(tmp_path, "flows/bravo.md", body="payment settle ledger flow bravo")
    _distractors(tmp_path)
    _run(tmp_path, "used", "bravo")
    res = _run(tmp_path, "context", "payment settle ledger flow")
    assert res.exit_code == 0, res.output
    assert res.output.index("alpha.md") < res.output.index("bravo.md")


def test_malformed_outcomes_line_is_skipped(tmp_path: Path):
    _init(tmp_path)
    _note(tmp_path, "flows/checkout.md", body="checkout settles a payment")
    _distractors(tmp_path)
    _run(tmp_path, "used", "checkout")
    p = _outcomes_path(tmp_path)
    p.write_text(p.read_text() + "this is not json\n{also bad\n")
    res = _run(tmp_path, "context", "checkout payment")
    assert res.exit_code == 0, res.output
    assert "checkout.md" in res.output


# ---------- unit: outcomes.py scoring ----------

def test_recency_decay_old_outcome_has_less_effect(tmp_path: Path):
    from lattice import outcomes
    from lattice.config import learn_config

    _init(tmp_path)
    cfg = learn_config(tmp_path)
    now = dt.datetime(2026, 6, 1, tzinfo=dt.timezone.utc)

    # fresh positive outcome
    outcomes.record(tmp_path, ["fresh"], good=True)
    # rewrite the single record to be "now" so decay is ~0
    p = _outcomes_path(tmp_path)
    p.write_text(json.dumps({"ts": now.isoformat(), "slugs": ["fresh"], "good": True}) + "\n")
    fresh_mult = outcomes.slug_multipliers(tmp_path, cfg, now=now)["fresh"]

    # very old positive outcome (age >> half_life)
    old = now - dt.timedelta(days=10000)
    p.write_text(json.dumps({"ts": old.isoformat(), "slugs": ["stale"], "good": True}) + "\n")
    old_mult = outcomes.slug_multipliers(tmp_path, cfg, now=now)["stale"]

    assert fresh_mult > 1.0
    assert abs(old_mult - 1.0) < 0.01  # decayed to negligible


def test_used_unit_load_and_score(tmp_path: Path):
    from lattice import outcomes
    from lattice.config import learn_config

    _init(tmp_path)
    cfg = learn_config(tmp_path)
    outcomes.record(tmp_path, ["good-note"], good=True)
    outcomes.record(tmp_path, ["bad-note"], good=False)
    now = dt.datetime.now(dt.timezone.utc)
    mults = outcomes.slug_multipliers(tmp_path, cfg, now=now)
    assert mults["good-note"] > 1.0
    assert mults["bad-note"] < 1.0
    # unseen slug -> neutral
    assert mults.get("never-seen", 1.0) == 1.0
