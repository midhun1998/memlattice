"""`lattice verify` Layer 1 — deterministic existence/freshness checks.

No LLM, no network by default. Resolves each citation to a status:
  present | drifted | missing | human-attested | unfetched
and reduces per-note to a worst-status. Exit non-zero on FAIL statuses
(missing). file/commit citations are checkable offline against the repo.
"""
from __future__ import annotations

import os
from pathlib import Path

from click.testing import CliRunner

from lattice import verify
from lattice.cli import main


# ---------- unit: status resolution per scheme ----------

def test_file_citation_present(tmp_path: Path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "x.py").write_text("line1\nthe worker calls the gateway\nline3\n")
    st = verify.resolve_citation("file:src/x.py", root=tmp_path)
    assert st.status == "present"


def test_file_citation_missing_when_parent_exists(tmp_path: Path):
    """Parent dir exists but the file is gone = genuinely missing (FAIL)."""
    (tmp_path / "src").mkdir()
    st = verify.resolve_citation("file:src/nope.py", root=tmp_path)
    assert st.status == "missing"


def test_file_citation_unresolvable_when_parent_absent(tmp_path: Path):
    """Path into a dir that doesn't exist here = unresolvable (likely another
    repo not checked out), a WARN, not a FAIL. Regression from dogfooding:
    cross-repo citations were wrongly failing as 'missing'."""
    st = verify.resolve_citation("file:chatbots/other-repo/src/x.py", root=tmp_path)
    assert st.status == "unresolvable"
    assert not verify.is_fail("unresolvable")


def test_file_citation_with_line_present(tmp_path: Path):
    (tmp_path / "a.py").write_text("one\ntwo\nthree\n")
    st = verify.resolve_citation("file:a.py:2", root=tmp_path)
    assert st.status == "present"


def test_file_citation_line_out_of_range_missing(tmp_path: Path):
    (tmp_path / "a.py").write_text("one\ntwo\n")
    st = verify.resolve_citation("file:a.py:99", root=tmp_path)
    assert st.status == "missing"


def test_file_citation_tilde_and_absolute_paths(tmp_path: Path):
    """A citation may use an absolute or ~-relative path; resolve it as such,
    not naively under root. Regression from dogfooding the real vault."""
    abs_file = tmp_path / "abs.txt"
    abs_file.write_text("content\n")
    # absolute path citation
    st = verify.resolve_citation(f"file:{abs_file}", root=tmp_path / "elsewhere")
    assert st.status == "present", st.detail
    # ~ expansion: point at a real file under HOME via ~ if one exists is fragile;
    # instead assert ~-paths are expanded (a bogus ~ path is 'missing', not
    # mis-resolved under root with a literal '~' segment)
    st2 = verify.resolve_citation("file:~/definitely-not-a-real-lattice-file.xyz", root=tmp_path)
    assert st2.status == "missing"
    assert "~" not in st2.detail  # the ~ was expanded, not kept literal


def test_human_attested_schemes(tmp_path: Path):
    for tok in ("conv:user:2026-06-03", "chat:#team:2026-06-03"):
        st = verify.resolve_citation(tok, root=tmp_path)
        assert st.status == "human-attested", tok


def test_url_unfetched_by_default(tmp_path: Path):
    st = verify.resolve_citation("url:https://example.com/x", root=tmp_path, fetch=False)
    assert st.status == "unfetched"


def test_commit_citation_missing_when_not_in_repo(tmp_path: Path):
    # tmp_path is not a git repo -> commit can't resolve -> missing
    st = verify.resolve_citation("commit:deadbeef", root=tmp_path)
    assert st.status == "missing"


# ---------- worst-status reduction ----------

def test_worst_status_reduction():
    assert verify.worst(["present", "human-attested", "present"]) == "present"
    assert verify.worst(["present", "drifted"]) == "drifted"
    assert verify.worst(["present", "missing", "drifted"]) == "missing"
    assert verify.worst([]) == "present"  # nothing to check = clean


def test_fail_statuses():
    assert verify.is_fail("missing")
    assert not verify.is_fail("present")
    assert not verify.is_fail("drifted")        # warn, not fail
    assert not verify.is_fail("human-attested")


# ---------- CLI integration ----------

def _vault(tmp_path: Path) -> None:
    CliRunner().invoke(main, ["init", str(tmp_path)])


def _run(root: Path, *args: str):
    cwd = os.getcwd()
    try:
        os.chdir(root)
        return CliRunner().invoke(main, list(args))
    finally:
        os.chdir(cwd)


def test_verify_command_passes_on_present_citation(tmp_path: Path):
    _vault(tmp_path)
    (tmp_path / "ref.txt").write_text("the gateway settles payments\n")
    note = tmp_path / "flows" / "checkout.md"
    note.write_text(
        "---\ntype: flow\nlast_verified: 2026-06-03\nrelated: []\n---\n\n"
        "# Checkout\n\nThe Gateway settles a payment [file:ref.txt].\n\n"
        "## Open questions\n- none\n\n## Referenced by\n_none_\n"
    )
    res = _run(tmp_path, "verify")
    assert res.exit_code == 0, res.output
    assert "present" in res.output.lower()


def test_verify_command_fails_on_missing_citation(tmp_path: Path):
    _vault(tmp_path)
    note = tmp_path / "flows" / "checkout.md"
    note.write_text(
        "---\ntype: flow\nlast_verified: 2026-06-03\nrelated: []\n---\n\n"
        "# Checkout\n\nThe Gateway settles a payment [file:gone.txt].\n\n"
        "## Open questions\n- none\n\n## Referenced by\n_none_\n"
    )
    res = _run(tmp_path, "verify")
    assert res.exit_code != 0, res.output
    assert "missing" in res.output.lower()
