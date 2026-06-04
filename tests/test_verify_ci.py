"""verify CI surface: --format json|sarif and --changed git scoping.

The audit artifact is machine-readable so a CI job can fail the build and a
code-scanning view can render findings. --changed limits to memory files
changed vs a base ref.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from click.testing import CliRunner

from lattice import verify
from lattice.cli import main


def _vault(tmp_path: Path) -> None:
    CliRunner().invoke(main, ["init", str(tmp_path)])


def _run(root: Path, *args: str):
    cwd = os.getcwd()
    try:
        os.chdir(root)
        return CliRunner().invoke(main, list(args))
    finally:
        os.chdir(cwd)


def _note(tmp_path: Path, name: str, citation: str) -> None:
    (tmp_path / "flows" / name).write_text(
        "---\ntype: flow\nlast_verified: 2026-06-03\nrelated: []\n---\n\n"
        f"# {name}\n\nThe Gateway settles a payment [{citation}].\n\n"
        "## Open questions\n- none\n\n## Referenced by\n_none_\n"
    )


# ---------- JSON audit artifact ----------

def test_verify_json_report_shape(tmp_path: Path):
    _vault(tmp_path)
    _note(tmp_path, "good.md", "file:ref.txt")
    (tmp_path / "ref.txt").write_text("ok\n")
    _note(tmp_path, "bad.md", "file:gone.txt")
    res = _run(tmp_path, "verify", "--format", "json")
    # stdout must be valid JSON regardless of pass/fail
    data = json.loads(res.output)
    assert "notes" in data and "summary" in data
    statuses = {n["path"].split("/")[-1]: n["status"] for n in data["notes"]}
    assert statuses["good.md"] == "present"
    assert statuses["bad.md"] == "missing"
    assert data["summary"]["failed"] >= 1
    # each note carries its citations with per-citation status
    bad = next(n for n in data["notes"] if n["path"].endswith("bad.md"))
    assert any(c["status"] == "missing" for c in bad["citations"])


# ---------- SARIF ----------

def test_verify_sarif_is_valid_sarif(tmp_path: Path):
    _vault(tmp_path)
    _note(tmp_path, "bad.md", "file:gone.txt")
    res = _run(tmp_path, "verify", "--format", "sarif")
    data = json.loads(res.output)
    assert data["version"] == "2.1.0"
    assert "$schema" in data
    run0 = data["runs"][0]
    assert run0["tool"]["driver"]["name"] == "lattice"
    # at least one result for the missing citation, with a file location
    assert run0["results"], "expected a SARIF result for the missing citation"
    loc = run0["results"][0]["locations"][0]["physicalLocation"]["artifactLocation"]["uri"]
    assert loc.endswith("bad.md")


# ---------- exit codes hold under --format ----------

def test_json_format_still_exits_nonzero_on_fail(tmp_path: Path):
    _vault(tmp_path)
    _note(tmp_path, "bad.md", "file:gone.txt")
    res = _run(tmp_path, "verify", "--format", "json")
    assert res.exit_code != 0


# ---------- --changed git scoping ----------

def _git(root: Path, *args: str) -> None:
    env = os.environ.copy()
    env["GIT_AUTHOR_NAME"] = env["GIT_COMMITTER_NAME"] = "T"
    env["GIT_AUTHOR_EMAIL"] = env["GIT_COMMITTER_EMAIL"] = "t@e.com"
    subprocess.run(["git", *args], cwd=root, env=env, check=True, capture_output=True, text=True)


def test_changed_scopes_to_diff(tmp_path: Path):
    _vault(tmp_path)
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "commit.gpgsign", "false")
    _note(tmp_path, "old.md", "file:gone-old.txt")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "base")
    base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=tmp_path,
                          capture_output=True, text=True).stdout.strip()
    # add a NEW note with a missing citation after the base commit
    _note(tmp_path, "new.md", "file:gone-new.txt")
    res = _run(tmp_path, "verify", "--changed", "--base", base, "--format", "json")
    data = json.loads(res.output)
    paths = [n["path"] for n in data["notes"]]
    assert any(p.endswith("new.md") for p in paths)
    assert not any(p.endswith("old.md") for p in paths), "should only scan changed files"
