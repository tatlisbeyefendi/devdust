#!/usr/bin/env python3
"""Render the output of a command into a self-contained SVG "terminal card".

Handy for documentation screenshots that never go stale: the image is produced
from real program output, so it cannot lie.

    python scripts/render_demo_svg.py docs/demo.svg --title devdust \\
        --prompt "devdust ~/work" -- devdust ~/work --top 6
"""

from __future__ import annotations

import argparse
import html
import os
import re
import subprocess
import sys
from pathlib import Path

ANSI_RE = re.compile(r"\x1b\[([0-9;]*)m")

PALETTE = {
    "30": "#484f58",
    "31": "#ff7b72",
    "32": "#7ee787",
    "33": "#ffd166",
    "34": "#79c0ff",
    "35": "#d2a8ff",
    "36": "#56d4dd",
    "37": "#d6deeb",
    "90": "#6e7b8b",
    "91": "#ff7b72",
    "92": "#7ee787",
    "93": "#ffd166",
    "94": "#79c0ff",
    "95": "#d2a8ff",
    "96": "#56d4dd",
    "97": "#f0f6fc",
}
DEFAULT_FG = "#c9d1d9"
BG = "#0d1117"
BAR = "#161b22"
FONT_SIZE = 13.0
CHAR_W = FONT_SIZE * 0.602
LINE_H = 21.0
PAD_X = 22.0
PAD_Y = 18.0
BAR_H = 34.0


def parse_ansi(line: str) -> list[tuple[str, set[str], str | None]]:
    """Split a line into ``(text, active_styles, colour)`` runs."""
    runs: list[tuple[str, set[str], str | None]] = []
    styles: set[str] = set()
    colour: str | None = None
    position = 0
    for match in ANSI_RE.finditer(line):
        chunk = line[position : match.start()]
        if chunk:
            runs.append((chunk, set(styles), colour))
        position = match.end()
        codes = [code for code in match.group(1).split(";") if code != ""] or ["0"]
        for code in codes:
            if code in ("0", ""):
                styles.clear()
                colour = None
            elif code in ("1", "2", "3", "4"):
                styles.add(code)
            elif code == "22":
                styles.discard("1")
                styles.discard("2")
            elif code in PALETTE:
                colour = PALETTE[code]
            elif code == "39":
                colour = None
    tail = line[position:]
    if tail:
        runs.append((tail, set(styles), colour))
    return runs


def render(lines: list[str], title: str) -> str:
    parsed = [parse_ansi(line) for line in lines]
    visible = [ANSI_RE.sub("", line) for line in lines]
    columns = max((len(line) for line in visible), default=20)
    width = round(columns * CHAR_W + PAD_X * 2)
    height = round(BAR_H + PAD_Y * 2 + len(lines) * LINE_H)

    out: list[str] = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-label="{html.escape(title)}">',
        "<title>" + html.escape(title) + "</title>",
        "<style>"
        "text{font-family:ui-monospace,SFMono-Regular,'SF Mono',Menlo,Consolas,"
        f"'Liberation Mono',monospace;font-size:{FONT_SIZE:.1f}px;white-space:pre}}"
        "</style>",
        f'<rect width="{width}" height="{height}" rx="10" fill="{BG}"/>',
        f'<rect width="{width}" height="{BAR_H}" rx="10" fill="{BAR}"/>',
        f'<rect y="{BAR_H - 10}" width="{width}" height="10" fill="{BAR}"/>',
    ]
    for index, colour in enumerate(("#ff5f57", "#febc2e", "#28c840")):
        cx = PAD_X + index * 18
        out.append(f'<circle cx="{cx}" cy="{BAR_H / 2}" r="5.5" fill="{colour}"/>')
    out.append(
        f'<text x="{width / 2}" y="{BAR_H / 2 + 4.5}" fill="#8b949e" '
        f'text-anchor="middle" font-size="11.5">{html.escape(title)}</text>'
    )

    y = BAR_H + PAD_Y + FONT_SIZE
    for runs in parsed:
        if not runs:
            y += LINE_H
            continue
        parts = [f'<text x="{PAD_X:.0f}" y="{y:.1f}" xml:space="preserve">']
        for text, styles, colour in runs:
            attrs = []
            if colour:
                attrs.append(f'fill="{colour}"')
            if "1" in styles:
                attrs.append('font-weight="600"')
            if "2" in styles:
                attrs.append('fill-opacity="0.62"')
            attr_text = (" " + " ".join(attrs)) if attrs else ""
            parts.append(f"<tspan{attr_text}>{html.escape(text)}</tspan>")
        parts.append("</text>")
        out.append("".join(parts))
        y += LINE_H
    out.append("</svg>")
    return "\n".join(out) + "\n"


def run_command(command: list[str]) -> list[str]:
    env = dict(os.environ, FORCE_COLOR="1", TERM="xterm-256color", COLUMNS="100")
    env.pop("NO_COLOR", None)
    completed = subprocess.run(command, capture_output=True, text=True, env=env, check=False)
    if completed.returncode != 0:
        print(completed.stderr, file=sys.stderr)
        raise SystemExit(f"command failed with {completed.returncode}: {' '.join(command)}")
    return completed.stdout.rstrip("\n").split("\n")


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--" in argv:
        split = argv.index("--")
        argv, command = argv[:split], argv[split + 1 :]
    else:
        command = []
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--title", default="devdust")
    parser.add_argument("--prompt", default=None, help="command line to show first")
    args = parser.parse_args(argv)
    if not command:
        parser.error("no command given (put it after --)")

    lines = run_command(command)
    if args.prompt:
        lines = [f"\x1b[2m$\x1b[0m \x1b[1m{args.prompt}\x1b[0m", "", *lines]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render(lines, args.title), encoding="utf-8")
    print(f"wrote {args.output} ({len(lines)} lines)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
