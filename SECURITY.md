# Security Policy

## Reporting a vulnerability

lattice is a local, offline CLI with no server and no network calls in its core
paths, so its attack surface is small — but if you find a security issue, we
still want to hear about it.

Please **do not open a public issue** for security problems. Instead, use
GitHub's [private vulnerability reporting](https://github.com/midhun1998/lattice/security/advisories/new)
to report it privately. We'll acknowledge within a few days and work with you
on a fix and disclosure timeline.

## Scope notes

- The only optional network/credential surface is the `agentic` extra, which
  reads `ANTHROPIC_API_KEY` to call the Claude API for richer `digest` output.
  It is off unless you install the extra and set the key.
- lattice executes any shell command you configure under `[hooks]` in
  `config.toml`. Treat your own vault config as trusted input — don't run a
  vault whose `config.toml` you didn't write.

## Supported versions

lattice is pre-1.0; security fixes land on the latest release.
