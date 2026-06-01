"""Citation scheme is config-driven, not hardcoded to internal vendors."""
from __future__ import annotations

from pathlib import Path

from lattice.config import citation_regex, DEFAULT_CITATION_SCHEMES
from lattice.vault import CITATION_RE


def test_public_citation_re_is_vendor_neutral():
    """The module-level CITATION_RE must not embed any internal vendor name."""
    for vendor in ("jira", "chat", "gitlab"):
        assert vendor not in CITATION_RE.pattern
    # still matches the generic defaults
    assert CITATION_RE.search("[file:x.py]")
    assert CITATION_RE.search("[doc:https://x]")


def test_default_schemes_are_vendor_neutral():
    """OSS default must not bake in any internal/vendor source name."""
    for vendor in ("jira", "chat", "gitlab", "jira"):
        assert vendor not in DEFAULT_CITATION_SCHEMES, (
            f"{vendor!r} is vendor-specific and must not be an OSS default"
        )
    # generic, universally-applicable schemes should be present
    for generic in ("file", "doc", "url", "commit", "pr", "conv", "chat"):
        assert generic in DEFAULT_CITATION_SCHEMES


def test_regex_matches_default_schemes():
    rx = citation_regex(None)  # no vault -> defaults only
    assert rx.search("the worker writes here [file:src/x.py:10]")
    assert rx.search("see [doc:https://example.com/spec]")
    assert rx.search("merged in [pr:owner/repo#42]")


def test_regex_excludes_unconfigured_scheme_by_default():
    rx = citation_regex(None)
    # 'jira' is NOT a default; a bare jira citation should not match
    assert not rx.search("query [jira:my-saved-search]")


def test_config_extra_schemes_extend_defaults(tmp_path: Path):
    """A user can declare extra citation schemes in config.toml."""
    _write_vault(tmp_path, extra_citations=["jira", "jira"])
    rx = citation_regex(tmp_path)
    # extras now match...
    assert rx.search("query [jira:my-saved-search]")
    assert rx.search("ticket [jira:PROJ-123]")
    # ...and defaults still match
    assert rx.search("code [file:a/b.py]")


def test_config_extra_is_additive_not_replacing(tmp_path: Path):
    _write_vault(tmp_path, extra_citations=["jira"])
    rx = citation_regex(tmp_path)
    assert rx.search("[doc:x]")  # default survives
    assert rx.search("[jira:PROJ-1]")  # extra added


def _write_vault(root: Path, extra_citations: list[str]) -> None:
    (root / ".lattice").mkdir(parents=True, exist_ok=True)
    extras = ", ".join(f'"{c}"' for c in extra_citations)
    (root / ".lattice" / "config.toml").write_text(
        f"[citations]\nextra = [{extras}]\n"
    )
    (root / "_protocol.md").write_text("---\ntype: protocol\n---\n")
