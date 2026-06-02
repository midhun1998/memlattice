"""P1-C — pluggable source adapters + built-in git adapter + `lattice refresh`.

`lattice refresh` is explicit/opt-in: it only runs when invoked, never on a
schedule, and is a no-op unless `[sources]` is configured. The built-in `git`
adapter scans new commits since a stored watermark (local-only `git log`, no
network, no auth) and drafts UNCITED candidate stubs into `_inbox/` — a review
area `load_vault` already excludes (dir starts with `_`). Drafts NEVER enter a
note body, preserving lattice's core invariant. Distillation reuses the
existing agentic.py Claude path and degrades to a heuristic with no API key.

All examples are fabricated (checkout, payment-gateway, jira).
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from click.testing import CliRunner

from lattice.cli import main
from lattice.config import citation_regex
from lattice.vault import load_vault


def _init(root: Path) -> None:
    CliRunner().invoke(main, ["init", str(root)])


def _git(root: Path, *args: str) -> None:
    env = os.environ.copy()
    env["GIT_AUTHOR_NAME"] = env["GIT_COMMITTER_NAME"] = "Test"
    env["GIT_AUTHOR_EMAIL"] = env["GIT_COMMITTER_EMAIL"] = "test@example.com"
    subprocess.run(["git", *args], cwd=root, env=env, check=True, capture_output=True, text=True)


def _git_repo(root: Path) -> None:
    _git(root, "init", "-q")
    _git(root, "config", "commit.gpgsign", "false")


def _commit(root: Path, fname: str, content: str, subject: str) -> None:
    (root / fname).write_text(content)
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", subject)


def _set_config(root: Path, body: str) -> None:
    (root / ".lattice" / "config.toml").write_text(body)


def _run(root: Path, *args: str):
    cwd = os.getcwd()
    try:
        os.chdir(root)
        return CliRunner().invoke(main, list(args))
    finally:
        os.chdir(cwd)


def _inbox_files(root: Path) -> list[Path]:
    inbox = root / "_inbox"
    if not inbox.exists():
        return []
    return sorted(inbox.glob("*.md"))


def _watermark_path(root: Path, source: str) -> Path:
    return root / ".lattice" / "cache" / "refresh" / f"{source}.json"


SOURCES_GIT = '[sources.repo]\nadapter = "git"\npath = "."\n'


# ---------- FAILING-FIRST happy path ----------

def test_refresh_git_adapter_drafts_uncited_stub_to_inbox(tmp_path: Path):
    """A tmp git repo that is also a lattice vault; refresh drafts an uncited
    stub into _inbox/ that names the commit and carries a needs-citation marker.
    Fails first because adapters.py/refresh.py/the command don't exist."""
    _init(tmp_path)
    _git_repo(tmp_path)
    _commit(tmp_path, "a.txt", "alpha", "add checkout settlement step")
    _commit(tmp_path, "b.txt", "beta", "wire payment-gateway retries")
    _set_config(tmp_path, SOURCES_GIT)

    res = _run(tmp_path, "refresh", "--no-distill")
    assert res.exit_code == 0, res.output

    files = _inbox_files(tmp_path)
    assert files, f"expected an _inbox draft; output:\n{res.output}"

    cite_re = citation_regex(tmp_path)
    all_text = "\n".join(f.read_text() for f in files)
    # uncited: carries a needs-citation / TODO marker, no citation token
    assert "needs-citation" in all_text.lower() or "todo" in all_text.lower()
    assert cite_re.search(all_text) is None, "draft must be UNCITED"
    # the commit subject appears somewhere in the drafts
    assert "checkout settlement" in all_text or "payment-gateway retries" in all_text


def test_refresh_writes_nothing_into_note_bodies(tmp_path: Path):
    """Real notes are byte-identical before/after; load_vault is unchanged."""
    _init(tmp_path)
    _git_repo(tmp_path)
    note = tmp_path / "flows" / "checkout.md"
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text(
        "---\ntype: flow\nlast_verified: 2026-06-01\nrelated: []\n---\n\n"
        "# Checkout\n\nThe gateway settles a payment [pr:acme/shop#7].\n\n"
        "## Open questions\n- none\n\n## Referenced by\n_none_\n"
    )
    _commit(tmp_path, "a.txt", "alpha", "add checkout settlement step")
    _set_config(tmp_path, SOURCES_GIT)

    before = note.read_bytes()
    before_notes = {n.slug: n.body for n in load_vault(tmp_path)}

    res = _run(tmp_path, "refresh", "--no-distill")
    assert res.exit_code == 0, res.output

    assert note.read_bytes() == before, "refresh must not touch note bodies"
    after_notes = {n.slug: n.body for n in load_vault(tmp_path)}
    assert after_notes == before_notes, "load_vault graph must be unchanged"


def test_inbox_excluded_from_lint_and_link(tmp_path: Path):
    """The deliberately-uncited _inbox stub is invisible to load_vault, so
    `lattice lint` stays clean."""
    _init(tmp_path)
    _git_repo(tmp_path)
    _commit(tmp_path, "a.txt", "alpha", "the Worker calls the PaymentGateway directly")
    _set_config(tmp_path, SOURCES_GIT)

    assert _run(tmp_path, "refresh", "--no-distill").exit_code == 0
    assert _inbox_files(tmp_path), "expected a draft"

    # _inbox not picked up by load_vault
    slugs = {n.slug for n in load_vault(tmp_path)}
    for f in _inbox_files(tmp_path):
        assert f.stem not in slugs

    lint = _run(tmp_path, "lint")
    assert lint.exit_code == 0, lint.output
    assert "un-cited" not in lint.output


# ---------- default-off / opt-in proofs ----------

def test_refresh_no_sources_is_noop(tmp_path: Path):
    """No [sources] -> exit 0, writes nothing, prints a hint."""
    _init(tmp_path)
    _git_repo(tmp_path)
    _commit(tmp_path, "a.txt", "alpha", "some commit")
    # default scaffold config has [sources] commented out
    res = _run(tmp_path, "refresh", "--no-distill")
    assert res.exit_code == 0, res.output
    assert not _inbox_files(tmp_path)
    assert "no sources" in res.output.lower()


def test_refresh_is_explicit_no_unattended_path(tmp_path: Path):
    """No scheduler/daemon/cron in the refresh path; nothing runs on init."""
    import lattice.refresh as r
    import inspect

    src = inspect.getsource(r) + inspect.getsource(__import__("lattice.adapters", fromlist=["x"]))
    for bad in ("import sched", "import threading", "crontab", "APScheduler", "Timer("):
        assert bad not in src, f"unattended primitive {bad!r} must not appear"

    # init must not create an _inbox or run adapters
    _init(tmp_path)
    _git_repo(tmp_path)
    _commit(tmp_path, "a.txt", "alpha", "x")
    _set_config(tmp_path, SOURCES_GIT)
    # re-run init (idempotent) — still no inbox produced
    _run(tmp_path, "init", ".")
    assert not _inbox_files(tmp_path)


# ---------- watermark behavior ----------

def test_git_adapter_advances_watermark(tmp_path: Path):
    """First run drafts, advances watermark to HEAD. A new commit -> second run
    yields ONLY the new commit."""
    _init(tmp_path)
    _git_repo(tmp_path)
    _commit(tmp_path, "a.txt", "alpha", "first commit subject")
    _commit(tmp_path, "b.txt", "beta", "second commit subject")
    _set_config(tmp_path, SOURCES_GIT)

    assert _run(tmp_path, "refresh", "--no-distill").exit_code == 0
    wm = _watermark_path(tmp_path, "repo")
    assert wm.exists(), "watermark must persist after a successful run"
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, capture_output=True, text=True
    ).stdout.strip()
    assert json.loads(wm.read_text())["watermark"] == head

    n_after_first = len(_inbox_files(tmp_path))

    _commit(tmp_path, "c.txt", "gamma", "third commit subject UNIQUE")
    assert _run(tmp_path, "refresh", "--no-distill").exit_code == 0
    # only the third commit produced a new draft
    new_files = [f for f in _inbox_files(tmp_path) if "third-commit" in f.name or "UNIQUE" in f.read_text()]
    assert new_files, "second run should draft the new commit"
    # the new draft references the third commit only
    text = "\n".join(f.read_text() for f in new_files)
    assert "third commit subject" in text
    assert "second commit subject" not in text


def test_git_adapter_dry_run_no_write_no_watermark(tmp_path: Path):
    """--dry-run prints candidates, writes no files, leaves watermark absent."""
    _init(tmp_path)
    _git_repo(tmp_path)
    _commit(tmp_path, "a.txt", "alpha", "dry run candidate subject")
    _set_config(tmp_path, SOURCES_GIT)

    res = _run(tmp_path, "refresh", "--no-distill", "--dry-run")
    assert res.exit_code == 0, res.output
    assert not _inbox_files(tmp_path), "dry-run must write nothing"
    assert not _watermark_path(tmp_path, "repo").exists(), "dry-run must not advance watermark"
    assert "dry run candidate subject" in res.output or "would" in res.output.lower()


def test_refresh_respects_limit(tmp_path: Path):
    """Many commits + --limit 2 -> at most 2 drafts."""
    _init(tmp_path)
    _git_repo(tmp_path)
    for i in range(6):
        _commit(tmp_path, f"f{i}.txt", str(i), f"commit number {i}")
    _set_config(tmp_path, SOURCES_GIT)

    res = _run(tmp_path, "refresh", "--no-distill", "--limit", "2")
    assert res.exit_code == 0, res.output
    assert len(_inbox_files(tmp_path)) <= 2


# ---------- distillation degrade + reuse of agentic path ----------

def test_distill_degrades_without_api_key(tmp_path: Path, monkeypatch):
    """No ANTHROPIC_API_KEY -> heuristic stub, still uncited."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    _init(tmp_path)
    _git_repo(tmp_path)
    _commit(tmp_path, "a.txt", "alpha", "heuristic path commit")
    _set_config(tmp_path, SOURCES_GIT)

    res = _run(tmp_path, "refresh")  # distill on by default, but no key
    assert res.exit_code == 0, res.output
    files = _inbox_files(tmp_path)
    assert files
    cite_re = citation_regex(tmp_path)
    assert cite_re.search("\n".join(f.read_text() for f in files)) is None


def test_distill_uses_agentic_path_when_available(tmp_path: Path, monkeypatch):
    """A monkeypatched agentic_distill returning text is used in the stub —
    proving reuse of the agentic path, while output stays uncited."""
    _init(tmp_path)
    _git_repo(tmp_path)
    _commit(tmp_path, "a.txt", "alpha", "distill me please")
    _set_config(tmp_path, SOURCES_GIT)

    import lattice.refresh as r

    def fake_distill(raw_text, vault=None, use_cache=True):
        return "DISTILLED_MARKER summary line"

    monkeypatch.setattr(r, "agentic_distill", fake_distill)
    res = _run(tmp_path, "refresh")
    assert res.exit_code == 0, res.output
    text = "\n".join(f.read_text() for f in _inbox_files(tmp_path))
    assert "DISTILLED_MARKER" in text
    # still uncited
    assert citation_regex(tmp_path).search(text) is None


# ---------- adapter discovery ----------

def test_adapter_discovery_via_entry_points_and_config(tmp_path: Path):
    """Built-in 'git' is available; an unknown adapter name yields a clear
    error (non-zero, names the adapter) rather than a traceback."""
    from lattice.adapters import available_adapters

    assert "git" in available_adapters()

    _init(tmp_path)
    _git_repo(tmp_path)
    _commit(tmp_path, "a.txt", "alpha", "x")
    _set_config(tmp_path, '[sources.repo]\nadapter = "nonesuch"\npath = "."\n')

    res = _run(tmp_path, "refresh", "--no-distill")
    assert res.exit_code != 0, res.output
    assert "nonesuch" in res.output


def test_git_adapter_no_network_no_auth(tmp_path: Path, monkeypatch):
    """Adapter requires no token/env and works offline. We assert it produces
    results with all auth-ish env vars cleared."""
    for var in ("ANTHROPIC_API_KEY", "GITHUB_TOKEN", "GIT_ASKPASS", "SSH_AUTH_SOCK"):
        monkeypatch.delenv(var, raising=False)
    _init(tmp_path)
    _git_repo(tmp_path)
    _commit(tmp_path, "a.txt", "alpha", "offline commit subject")
    _set_config(tmp_path, SOURCES_GIT)
    res = _run(tmp_path, "refresh", "--no-distill")
    assert res.exit_code == 0, res.output
    assert _inbox_files(tmp_path)


def test_refresh_source_filter(tmp_path: Path):
    """--source selects only the named source(s)."""
    _init(tmp_path)
    _git_repo(tmp_path)
    _commit(tmp_path, "a.txt", "alpha", "filter commit subject")
    _set_config(
        tmp_path,
        '[sources.repo]\nadapter = "git"\npath = "."\n\n'
        '[sources.other]\nadapter = "git"\npath = "."\n',
    )
    res = _run(tmp_path, "refresh", "--no-distill", "--source", "repo")
    assert res.exit_code == 0, res.output
    # only the 'repo' source ran -> its watermark exists, 'other' does not
    assert _watermark_path(tmp_path, "repo").exists()
    assert not _watermark_path(tmp_path, "other").exists()
