"""Review-gated draft inbox: `lattice inbox` + `lattice promote`.

`_inbox/` is the review gate between adapter output (`lattice refresh`) and the
verified corpus. `lattice inbox` lists pending uncited drafts (read-only).
`lattice promote <draft>` MOVES a draft into a real category dir as a properly
templated note that STILL must earn citations to pass `lint` — promotion can
never launder an uncited claim into the verified body. The inbox dir is excluded
from the normal vault scan and is config-driven via `[inbox] dir`.

All examples are fabricated (checkout, payment-gateway, jira).
"""
from __future__ import annotations

import os
from pathlib import Path

from click.testing import CliRunner

from lattice.cli import main
from lattice.vault import load_vault


def _init(root: Path) -> None:
    CliRunner().invoke(main, ["init", str(root)])


def _run(root: Path, *args: str):
    cwd = os.getcwd()
    try:
        os.chdir(root)
        return CliRunner().invoke(main, list(args))
    finally:
        os.chdir(cwd)


def _drop_draft(root: Path, name: str, body: str, dir_name: str = "_inbox") -> Path:
    d = root / dir_name
    d.mkdir(parents=True, exist_ok=True)
    p = d / name
    p.write_text(body)
    return p


# A fabricated uncited stub shaped like adapter output.
UNCITED_STUB = """\
---
type: inbox-draft
status: needs-citation
source: repo
ref: deadbeef
---

# DRAFT (uncited): add checkout settlement step

- [ ] TODO: verify and add a citation, then promote into a note body.

## Summary
The Worker calls the PaymentGateway directly.

## Raw source
```
add checkout settlement step
```
"""


# ---------- FAILING-FIRST: core invariant ----------

def test_promote_uncited_draft_still_fails_lint(tmp_path: Path):
    """Promotion must NOT launder an uncited claim into the verified corpus.

    Fails first because the `promote` command does not exist (Click reports
    'No such command')."""
    _init(tmp_path)
    _drop_draft(tmp_path, "orphan-draft.md", UNCITED_STUB)

    res = _run(tmp_path, "promote", "orphan-draft", "--type", "flow")
    assert res.exit_code == 0, res.output

    target = tmp_path / "flows" / "orphan-draft.md"
    assert target.exists(), f"promoted note should exist; output:\n{res.output}"

    lint = _run(tmp_path, "lint")
    assert lint.exit_code != 0, lint.output
    assert "un-cited" in lint.output, lint.output


# ---------- exclusion contract ----------

def test_inbox_dir_excluded_from_scan(tmp_path: Path):
    """A draft in _inbox/ is invisible to load_vault; a real note is not."""
    _init(tmp_path)
    _drop_draft(tmp_path, "draft-one.md", UNCITED_STUB)
    note = tmp_path / "flows" / "checkout.md"
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text(
        "---\ntype: flow\nlast_verified: 2026-06-01\nrelated: []\n---\n\n"
        "# Checkout\n\nThe gateway settles a payment [pr:acme/shop#7].\n\n"
        "## Open questions\n- none\n\n## Referenced by\n_none_\n"
    )
    slugs = {n.slug for n in load_vault(tmp_path)}
    assert slugs == {"checkout"}


def test_inbox_dir_configurable(tmp_path: Path):
    """`[inbox] dir = "_drafts"` relocates the gate: a file in _drafts/ is
    listed by `inbox`, excluded from load_vault, and promotable."""
    _init(tmp_path)
    (tmp_path / ".lattice" / "config.toml").write_text(
        (tmp_path / ".lattice" / "config.toml").read_text()
        + '\n[inbox]\ndir = "_drafts"\n'
    )
    _drop_draft(tmp_path, "relocated.md", UNCITED_STUB, dir_name="_drafts")

    # excluded from scan
    assert {n.slug for n in load_vault(tmp_path)} == set()

    # listed by inbox
    res = _run(tmp_path, "inbox")
    assert res.exit_code == 0, res.output
    assert "relocated" in res.output

    # promotable out of the relocated dir
    pro = _run(tmp_path, "promote", "relocated", "--type", "flow")
    assert pro.exit_code == 0, pro.output
    assert (tmp_path / "flows" / "relocated.md").exists()


def test_inbox_dir_configurable_non_underscore(tmp_path: Path):
    """A custom dir WITHOUT an underscore prefix must still be excluded from
    load_vault — proving the exclusion consults config, not just the `_` rule."""
    _init(tmp_path)
    (tmp_path / ".lattice" / "config.toml").write_text(
        (tmp_path / ".lattice" / "config.toml").read_text()
        + '\n[inbox]\ndir = "drafts"\n'
    )
    _drop_draft(tmp_path, "plain.md", UNCITED_STUB, dir_name="drafts")
    assert {n.slug for n in load_vault(tmp_path)} == set()


# ---------- inbox listing ----------

def test_inbox_lists_pending_drafts(tmp_path: Path):
    _init(tmp_path)
    _drop_draft(tmp_path, "draft-one.md", UNCITED_STUB)
    _drop_draft(tmp_path, "draft-two.md", UNCITED_STUB)
    res = _run(tmp_path, "inbox")
    assert res.exit_code == 0, res.output
    assert "draft-one" in res.output
    assert "draft-two" in res.output


def test_inbox_empty_state(tmp_path: Path):
    """Empty inbox prints the friendly empty-state and exits 0."""
    _init(tmp_path)
    res = _run(tmp_path, "inbox")
    assert res.exit_code == 0, res.output
    assert "empty" in res.output.lower()


def test_inbox_aborts_outside_vault(tmp_path: Path):
    """Exit 2 if not in a vault (reuse _abort_no_vault)."""
    res = _run(tmp_path, "inbox")
    assert res.exit_code == 2, res.output


# ---------- move semantics ----------

def test_promote_moves_draft_out_of_inbox(tmp_path: Path):
    _init(tmp_path)
    src = _drop_draft(tmp_path, "movable.md", UNCITED_STUB)
    res = _run(tmp_path, "promote", "movable", "--type", "flow")
    assert res.exit_code == 0, res.output
    assert not src.exists(), "default promote is a MOVE — original should be gone"
    assert (tmp_path / "flows" / "movable.md").exists()


def test_promote_keep_leaves_original(tmp_path: Path):
    _init(tmp_path)
    src = _drop_draft(tmp_path, "kept.md", UNCITED_STUB)
    res = _run(tmp_path, "promote", "kept", "--type", "flow", "--keep")
    assert res.exit_code == 0, res.output
    assert src.exists(), "--keep should leave the original draft"
    assert (tmp_path / "flows" / "kept.md").exists()


def test_promote_refuses_to_clobber(tmp_path: Path):
    _init(tmp_path)
    src = _drop_draft(tmp_path, "dup.md", UNCITED_STUB)
    existing = tmp_path / "flows" / "dup.md"
    existing.parent.mkdir(parents=True, exist_ok=True)
    existing.write_text("PRE-EXISTING CONTENT\n")

    res = _run(tmp_path, "promote", "dup", "--type", "flow")
    assert res.exit_code == 1, res.output
    # both files untouched
    assert src.exists(), "draft must remain on a refused clobber"
    assert existing.read_text() == "PRE-EXISTING CONTENT\n"

    # --force overwrites
    res2 = _run(tmp_path, "promote", "dup", "--type", "flow", "--force")
    assert res2.exit_code == 0, res2.output
    assert existing.read_text() != "PRE-EXISTING CONTENT\n"


# ---------- type handling ----------

def test_promote_rejects_unconfigured_type(tmp_path: Path):
    _init(tmp_path)
    _drop_draft(tmp_path, "typeless.md", UNCITED_STUB)
    res = _run(tmp_path, "promote", "typeless", "--type", "bogustype")
    assert res.exit_code != 0, res.output
    assert "bogustype" in res.output or "unknown" in res.output.lower()


def test_promote_infers_type_from_frontmatter(tmp_path: Path):
    """A draft whose frontmatter declares a real note `type:` promotes into
    that type's dir without --type."""
    _init(tmp_path)
    stub = UNCITED_STUB.replace("type: inbox-draft", "type: component")
    _drop_draft(tmp_path, "inferred.md", stub)
    res = _run(tmp_path, "promote", "inferred")
    assert res.exit_code == 0, res.output
    assert (tmp_path / "components" / "inferred.md").exists()


def test_promote_requires_type_when_unknown(tmp_path: Path):
    """No --type and an unresolvable draft `type:` -> error asking for --type
    (never silently guesses)."""
    _init(tmp_path)
    # inbox-draft is not a real note type, so it can't be inferred
    _drop_draft(tmp_path, "needstype.md", UNCITED_STUB)
    res = _run(tmp_path, "promote", "needstype")
    assert res.exit_code != 0, res.output
    assert "--type" in res.output


# ---------- template structure ----------

def test_promoted_note_has_template_structure(tmp_path: Path):
    _init(tmp_path)
    _drop_draft(tmp_path, "shaped.md", UNCITED_STUB)
    assert _run(tmp_path, "promote", "shaped", "--type", "flow").exit_code == 0
    text = (tmp_path / "flows" / "shaped.md").read_text()
    assert "Open questions" in text
    assert "Referenced by" in text
    # the draft material is carried in (so a human can cite + move it)
    assert "PaymentGateway" in text


# ---------- security / scoping ----------

def test_promote_target_is_inbox_scoped(tmp_path: Path):
    """A path-traversal / outside-inbox arg is rejected; nothing is created."""
    _init(tmp_path)
    secret = tmp_path / "secret.md"
    secret.write_text("SECRET\n")
    res = _run(tmp_path, "promote", "../secret", "--type", "flow")
    assert res.exit_code != 0, res.output
    # the secret was not consumed/moved
    assert secret.read_text() == "SECRET\n"
    assert not (tmp_path / "flows" / "secret.md").exists()


def test_promote_slug_override(tmp_path: Path):
    """--slug overrides the destination filename stem."""
    _init(tmp_path)
    _drop_draft(tmp_path, "raw-stem.md", UNCITED_STUB)
    res = _run(tmp_path, "promote", "raw-stem", "--type", "flow", "--slug", "clean-name")
    assert res.exit_code == 0, res.output
    assert (tmp_path / "flows" / "clean-name.md").exists()
    assert not (tmp_path / "flows" / "raw-stem.md").exists()


def test_promote_missing_draft_errors(tmp_path: Path):
    _init(tmp_path)
    res = _run(tmp_path, "promote", "nope", "--type", "flow")
    assert res.exit_code != 0, res.output


# ---------- zero-spend / default-off ----------

def test_promote_with_no_api_key_works(tmp_path: Path, monkeypatch):
    """Promote is a pure file/template op — no LLM call, runs green with no key."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    _init(tmp_path)
    _drop_draft(tmp_path, "offline.md", UNCITED_STUB)
    res = _run(tmp_path, "promote", "offline", "--type", "flow")
    assert res.exit_code == 0, res.output
    assert (tmp_path / "flows" / "offline.md").exists()


def test_inbox_promote_no_unattended_primitives():
    """No scheduler/daemon/network/LLM in the inbox module."""
    import inspect
    import lattice.inbox as ib

    src = inspect.getsource(ib)
    for bad in ("import sched", "import threading", "crontab", "APScheduler",
                "Timer(", "anthropic", "requests", "urllib.request"):
        assert bad not in src, f"unattended/network primitive {bad!r} must not appear"
