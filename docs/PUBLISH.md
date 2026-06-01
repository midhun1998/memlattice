# Publishing memlattice

## GitHub (public repo)

All examples in this repo are fabricated — no real service names.

```bash
cd /path/to/lattice

# Create the public repo on github.com first (web UI or `gh repo create`).
git remote add origin git@github.com:<you>/lattice.git
git branch -M main
git push -u origin main
```

## PyPI (memlattice)

Build artifacts already produced under `dist/` via `python -m build`.
Validate:

```bash
.venv/bin/twine check dist/*
# Both files should report PASSED.
```

### Test on TestPyPI first

```bash
# Need an account at https://test.pypi.org/ + an API token
.venv/bin/twine upload --repository testpypi dist/*

# Verify install
pipx install --pip-args="--index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/" memlattice
lattice --version
pipx uninstall memlattice
```

### Production PyPI

**Don't run this until ready** — once a name is uploaded and yanked,
the version is burned forever.

```bash
.venv/bin/twine upload dist/*
# Token at https://pypi.org/manage/account/token/
```

After upload:

```bash
pipx install memlattice
lattice --version
```

## Bumping the version

1. Update `pyproject.toml` `version = "..."`.
2. Update `lattice/__init__.py` `__version__`.
3. Add a `## vX.Y.Z` section to `CHANGELOG.md`.
4. Commit, tag (`git tag vX.Y.Z`), push (`git push --tags`).
5. `rm -rf dist/ && python -m build && twine check dist/*`.
6. Upload as above.
