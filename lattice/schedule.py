"""Scheduler HINT rendering — print a ready-to-paste cron/launchd snippet.

lattice ships NO daemon. This module never installs anything: it renders a
snippet to a string that the user copies and installs themselves. Nothing here
touches the crontab, writes a launchd plist, or runs on a timer.

Everything is config-driven: the scheduled subcommand comes from `[schedule]
command` (default "refresh"), so no vendor/tool name is hardcoded. The
`lattice` invocation is resolved at runtime (shutil.which, else
`<python> -m lattice`) so it works in venvs/pipx — never a literal binary path.

The snippet carries an inline comment that the job still obeys
`[budget] max_usd_per_day`, so an installed unattended job inherits the same
hard cost ceiling (silence is never green).

Pure stdlib. No new dependencies.
"""
from __future__ import annotations

import shlex
import shutil
import sys
from pathlib import Path

# Inline reminder embedded in every snippet. Generic on purpose — names no
# command literally beyond the user's own configured subcommand.
BUDGET_REMINDER = (
    "this job still obeys [budget] max_usd_per_day in config.toml; "
    "with the default ceiling 0 it will never spend (it degrades to the "
    "local heuristic). Raise the cap to enable any spend."
)


def lattice_invocation() -> list[str]:
    """Resolve how to invoke the user's own `lattice` CLI.

    Prefers a `lattice` on PATH (covers pipx / installed console-script), else
    falls back to `<this-python> -m lattice`. Never a hardcoded absolute path.
    """
    found = shutil.which("lattice")
    if found:
        return [found]
    return [sys.executable, "-m", "lattice"]


def command_string(vault: Path, subcommand: str) -> str:
    """The full shell command a scheduled job would run, pointed at `vault`."""
    parts = lattice_invocation() + [subcommand]
    # `digest` needs its history file argument; everything else takes the vault
    # via cwd. We `cd` into the vault so vault auto-discovery works, then run.
    cmd = " ".join(shlex.quote(p) for p in parts)
    return f"cd {shlex.quote(str(vault))} && {cmd}"


def _interval_minutes_hours(at: str, every_hours: int | None) -> tuple[int, int]:
    """Parse an 'HH:MM' time into (minute, hour). Defaults to 03:00 on bad input."""
    try:
        hh, mm = at.split(":", 1)
        hour, minute = int(hh), int(mm)
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError
    except (ValueError, AttributeError):
        hour, minute = 3, 0
    return minute, hour


def render_cron(vault: Path, subcommand: str, at: str = "03:00", every_hours: int | None = None) -> str:
    """Render a POSIX-portable crontab snippet (no GNU-only syntax).

    With `every_hours`, schedules at minute 0 every N hours (`0 */N * * *`).
    Otherwise schedules daily at `at` (`MM HH * * *`).
    """
    minute, hour = _interval_minutes_hours(at, every_hours)
    cmd = command_string(vault, subcommand)
    if every_hours and every_hours > 0:
        timespec = f"0 */{int(every_hours)} * * *"
        when = f"every {int(every_hours)}h"
    else:
        timespec = f"{minute} {hour} * * *"
        when = f"daily at {hour:02d}:{minute:02d}"
    return (
        f"# lattice schedule — paste into your crontab (crontab -e). {when}.\n"
        f"# lattice ships no daemon; you install this yourself.\n"
        f"# NOTE: {BUDGET_REMINDER}\n"
        f"{timespec} {cmd}\n"
    )


def render_launchd(vault: Path, subcommand: str, at: str = "03:00", every_hours: int | None = None) -> str:
    """Render a launchd plist string (darwin). Caller saves + loads it; we do
    not. Uses StartCalendarInterval for a daily time, or StartInterval seconds
    for an every-N-hours cadence."""
    minute, hour = _interval_minutes_hours(at, every_hours)
    args = lattice_invocation() + [subcommand]
    arg_xml = "\n".join(f"        <string>{a}</string>" for a in args)
    label = f"sh.lattice.{subcommand}"
    if every_hours and every_hours > 0:
        interval_block = (
            "    <key>StartInterval</key>\n"
            f"    <integer>{int(every_hours) * 3600}</integer>"
        )
    else:
        interval_block = (
            "    <key>StartCalendarInterval</key>\n"
            "    <dict>\n"
            "        <key>Hour</key>\n"
            f"        <integer>{hour}</integer>\n"
            "        <key>Minute</key>\n"
            f"        <integer>{minute}</integer>\n"
            "    </dict>"
        )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!-- lattice schedule — save as ~/Library/LaunchAgents/'
        f'{label}.plist then: launchctl load <that file>.\n'
        '     lattice ships no daemon; you install this yourself.\n'
        f'     NOTE: {BUDGET_REMINDER} -->\n'
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
        '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
        '<plist version="1.0">\n'
        "<dict>\n"
        "    <key>Label</key>\n"
        f"    <string>{label}</string>\n"
        "    <key>WorkingDirectory</key>\n"
        f"    <string>{vault}</string>\n"
        "    <key>ProgramArguments</key>\n"
        "    <array>\n"
        f"{arg_xml}\n"
        "    </array>\n"
        f"{interval_block}\n"
        "</dict>\n"
        "</plist>\n"
    )
