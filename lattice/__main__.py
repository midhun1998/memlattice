"""Enable `python -m lattice` so the scheduler-hint fallback invocation works.

`lattice schedule` resolves the CLI via `shutil.which("lattice")` and falls back
to `<python> -m lattice` when no console-script is on PATH (venv/pipx edge
cases). That fallback needs this module to be runnable.
"""
from .cli import main

if __name__ == "__main__":
    main()
