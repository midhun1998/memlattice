"""Note types are config-driven; `new` accepts user-defined types."""
from __future__ import annotations

from pathlib import Path

from lattice.config import note_types, DEFAULT_TYPES


def test_default_types_preserved():
    """The original three types remain the zero-config default."""
    assert DEFAULT_TYPES == {
        "flow": "flows",
        "component": "components",
        "api": "api",
    }


def test_note_types_defaults_when_no_config(tmp_path: Path):
    (tmp_path / "_protocol.md").write_text("---\ntype: protocol\n---\n")
    assert note_types(tmp_path) == DEFAULT_TYPES


def test_config_adds_custom_types(tmp_path: Path):
    (tmp_path / ".lattice").mkdir(parents=True)
    (tmp_path / ".lattice" / "config.toml").write_text(
        '[types]\nrunbook = "runbooks"\ndecision = "decisions"\n'
    )
    (tmp_path / "_protocol.md").write_text("---\ntype: protocol\n---\n")
    types = note_types(tmp_path)
    # custom types present
    assert types["runbook"] == "runbooks"
    assert types["decision"] == "decisions"
    # defaults still present (additive)
    assert types["flow"] == "flows"


def test_config_can_override_default_dir(tmp_path: Path):
    """A user may remap a default type's directory."""
    (tmp_path / ".lattice").mkdir(parents=True)
    (tmp_path / ".lattice" / "config.toml").write_text(
        '[types]\napi = "endpoints"\n'
    )
    (tmp_path / "_protocol.md").write_text("---\ntype: protocol\n---\n")
    assert note_types(tmp_path)["api"] == "endpoints"
