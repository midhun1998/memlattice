# Contributing to lattice

Thanks for your interest in improving lattice! This project is a small,
dependency-light CLI — contributions that keep it that way are especially
welcome.

## Ground rules

- **Stay dependency-light.** Core depends only on `click`, `pyyaml`, and
  `rank-bm25`. Anything heavier (embeddings, model backends) belongs behind
  an optional extra (`pip install memlattice[...]`), never in the core path.
- **No vendor lock-in.** Citation schemes, note types, and sources are
  config-driven. Don't hardcode any specific tool, service, or provider name
  into core code — make it configurable instead.
- **Fabricate all examples.** Docs, tests, and templates must use invented
  names (`checkout`, `payment-gateway`, `jira`) — never real internal systems.
- **Verification by construction.** lattice's whole premise is that uncited
  claims can't enter a note's body. Don't add features that bypass that gate.

## Development setup

```bash
git clone https://github.com/midhun1998/lattice && cd lattice
python -m venv .venv && source .venv/bin/activate
pip install -e ".[agentic]"      # editable install + optional Claude backend
pip install pytest               # test runner
```

## Running the tests

```bash
pytest -q
```

Every behavior change needs a test. lattice follows test-driven development:
write the failing test first, watch it fail, then make it pass. Bug fixes
must include a regression test that reproduces the bug.

## Making a change

1. **Open an issue first** for anything non-trivial, so we can agree on the
   approach before you invest time.
2. Branch from `main`: `git checkout -b feat/short-description`.
3. Make the change with a test. Keep commits focused.
4. Use [Conventional Commits](https://www.conventionalcommits.org/):
   `feat:`, `fix:`, `docs:`, `test:`, `refactor:`, `chore:`.
5. Run `pytest -q` — all green, no warnings.
6. Open a pull request describing **what** changed and **why**.

## Project layout

```
lattice/        # the CLI package
  cli.py        # commands: init, new, link, lint, stale, context, cache, digest
  vault.py      # vault discovery, frontmatter + link-graph parsing
  config.py     # .lattice/config.toml loader; citation schemes & note types
  agentic.py    # optional Claude-backed digest, with heuristic fallback
  templates.py  # embedded scaffold templates
tests/          # pytest suite
docs/           # landing page (index.html) + assets
SPEC.md         # design spec / rationale
```

## Maintainer notes — releasing

<details>
<summary>Publishing a new version to PyPI (maintainers only)</summary>

```bash
# 1. Bump version in pyproject.toml AND lattice/__init__.py
# 2. Add a ## vX.Y.Z section to CHANGELOG.md
# 3. Commit + tag
git commit -am "chore: release vX.Y.Z"
git tag vX.Y.Z && git push --tags

# 4. Build + validate
rm -rf dist/ && python -m build && twine check dist/*

# 5. Test on TestPyPI before the real thing
twine upload --repository testpypi dist/*
pipx install --pip-args="--index-url https://test.pypi.org/simple/ \
  --extra-index-url https://pypi.org/simple/" memlattice
lattice --version && pipx uninstall memlattice

# 6. Production PyPI (a yanked version number is burned forever — be sure)
twine upload dist/*
```

</details>

## License

By contributing, you agree that your contributions are licensed under the
[MIT License](LICENSE).
