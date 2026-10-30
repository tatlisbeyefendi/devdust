"""Small, dependency-free helpers for sizes, ages, colours and tables."""

from __future__ import annotations

import math
import os
import re
import shutil
import sys
from collections.abc import Callable, Iterable, Sequence
from datetime import timedelta
from typing import ClassVar

# --------------------------------------------------------------------- sizes

_UNITS = ("B", "KB", "MB", "GB", "TB", "PB")


def human_size(num_bytes: float) -> str:
    """Format a byte count the way ``du -h`` mostly does: ``1.4 GB``."""
    if num_bytes < 0:
        raise ValueError("size cannot be negative")
    if num_bytes < 1024:
        return f"{int(num_bytes)} B"
    value = float(num_bytes)
    unit = _UNITS[1]
    for candidate in _UNITS[1:]:
        value /= 1024.0
        unit = candidate
        if value < 1023.5 or candidate == _UNITS[-1]:
            break
    if value >= 100:
        return f"{value:.0f} {unit}"
    if value >= 10:
        return f"{value:.1f}".rstrip("0").rstrip(".") + " " + unit
    return f"{value:.2f}".rstrip("0").rstrip(".") + " " + unit


_SIZE_RE = re.compile(r"^\s*(\d+(?:[.,]\d+)?)\s*([a-zA-Z]*)\s*$")
_SIZE_SUFFIXES = {
    "": 1,
    "b": 1,
    "k": 1024,
    "kb": 1024,
    "kib": 1024,
    "m": 1024**2,
    "mb": 1024**2,
    "mib": 1024**2,
    "g": 1024**3,
    "gb": 1024**3,
    "gib": 1024**3,
    "t": 1024**4,
    "tb": 1024**4,
    "tib": 1024**4,
}


def parse_size(text: str) -> int:
    """Parse ``"10MB"`` / ``"1.5g"`` / ``"512"`` into bytes."""
    match = _SIZE_RE.match(text)
    if not match:
        raise ValueError(f"cannot parse size: {text!r}")
    number, suffix = match.group(1).replace(",", "."), match.group(2).lower()
    if suffix not in _SIZE_SUFFIXES:
        raise ValueError(f"unknown size unit {suffix!r} in {text!r}")
    return int(float(number) * _SIZE_SUFFIXES[suffix])


# ---------------------------------------------------------------------- ages

_DURATION_RE = re.compile(r"^\s*(\d+(?:[.,]\d+)?)\s*([smhdw])\s*$", re.IGNORECASE)
_DURATION_UNITS = {
    "s": 1,
    "m": 60,
    "h": 3600,
    "d": 86400,
    "w": 604800,
}


def parse_duration(text: str) -> timedelta:
    """Parse ``"30d"`` / ``"12h"`` / ``"2w"`` into a :class:`~datetime.timedelta`."""
    match = _DURATION_RE.match(text)
    if not match:
        raise ValueError(f"cannot parse duration: {text!r} (try 12h, 7d, 2w)")
    number, unit = match.group(1).replace(",", "."), match.group(2).lower()
    return timedelta(seconds=float(number) * _DURATION_UNITS[unit])


def human_age(seconds: float | None) -> str:
    """Compact age: ``45s``, ``12m``, ``5h``, ``31d``, ``2y``."""
    if seconds is None:
        return "-"
    if seconds < 0:
        seconds = 0
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h"
    days = hours // 24
    if days < 365:
        return f"{days}d"
    return f"{days // 365}y"


def human_count(value: int) -> str:
    """``1234`` -> ``1.2k``; keeps table columns narrow."""
    if value < 1000:
        return str(value)
    if value < 1_000_000:
        return f"{value / 1000:.1f}k".replace(".0k", "k")
    return f"{value / 1_000_000:.1f}M".replace(".0M", "M")


# -------------------------------------------------------------------- colour


class Style:
    """Minimal ANSI styling that disappears when colour is disabled."""

    _CODES: ClassVar[dict[str, str]] = {
        "bold": "1",
        "dim": "2",
        "italic": "3",
        "underline": "4",
        "red": "31",
        "green": "32",
        "yellow": "33",
        "blue": "34",
        "magenta": "35",
        "cyan": "36",
        "grey": "90",
    }

    def __init__(self, enabled: bool = False) -> None:
        self.enabled = enabled

    def paint(self, text: str, *styles: str) -> str:
        if not self.enabled or not text:
            return text
        codes = ";".join(self._CODES[s] for s in styles if s in self._CODES)
        if not codes:
            return text
        return f"\x1b[{codes}m{text}\x1b[0m"

    # tiny convenience wrappers, handy in tests
    def bold(self, text: str) -> str:
        return self.paint(text, "bold")

    def dim(self, text: str) -> str:
        return self.paint(text, "dim")

    def green(self, text: str) -> str:
        return self.paint(text, "green")

    def yellow(self, text: str) -> str:
        return self.paint(text, "yellow")

    def cyan(self, text: str) -> str:
        return self.paint(text, "cyan")


def supports_color(stream=None) -> bool:
    """Honour the usual conventions: ``NO_COLOR``, ``FORCE_COLOR``, ``isatty``."""
    stream = stream if stream is not None else sys.stdout
    if os.environ.get("FORCE_COLOR"):
        return True
    if "NO_COLOR" in os.environ:
        return False
    if os.environ.get("TERM") == "dumb":
        return False
    return bool(getattr(stream, "isatty", lambda: False)())


# --------------------------------------------------------------------- table


def render_styled_table(
    headers: Sequence[str],
    rows: Iterable[Sequence[str]],
    *,
    align: Sequence[str] | None = None,
    indent: str = "  ",
    gap: str = "  ",
    styler: Callable[[int, int, str], str] | None = None,
    header_styler: Callable[[int, str], str] | None = None,
) -> str:
    """Like :func:`render_table`, but styled *after* padding.

    Colouring is applied to the already padded cell so ANSI escapes never
    break the column alignment.
    """
    rows = [list(map(str, row)) for row in rows]
    widths = [len(h) for h in headers]
    for row in rows:
        if len(row) != len(headers):
            raise ValueError("every row needs exactly one cell per header")
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))

    aligns = list(align or ["left"] * len(headers))
    if len(aligns) != len(headers):
        raise ValueError("align needs one entry per header")

    def pad(cell: str, index: int) -> str:
        if aligns[index] == "right":
            return cell.rjust(widths[index])
        if aligns[index] == "center":
            return cell.center(widths[index])
        return cell.ljust(widths[index])

    def fmt(cells: Sequence[str], header: bool = False, row_index: int = 0) -> str:
        parts = []
        for i, cell in enumerate(cells):
            padded = pad(cell, i)
            if header and header_styler is not None:
                padded = header_styler(i, padded)
            elif not header and styler is not None:
                padded = styler(i, row_index, padded)
            parts.append(padded)
        return indent + gap.join(parts).rstrip()

    lines = [fmt(list(headers), header=True)]
    if rows:
        lines.append(indent + gap.join("-" * w for w in widths))
        for index, row in enumerate(rows):
            lines.append(fmt(row, row_index=index))
    return "\n".join(lines)


def render_table(
    headers: Sequence[str],
    rows: Iterable[Sequence[str]],
    *,
    align: Sequence[str] | None = None,
    indent: str = "  ",
    gap: str = "  ",
) -> str:
    """Render a plain-text table with aligned columns (no external deps)."""
    return render_styled_table(headers, rows, align=align, indent=indent, gap=gap)


_TTY_WIDTH = shutil.get_terminal_size((100, 24)).columns


def terminal_width(default: int = 100) -> int:
    try:
        return shutil.get_terminal_size((default, 24)).columns
    except OSError:  # pragma: no cover - extremely unusual
        return default


def ellipsize(text: str, limit: int) -> str:
    """Shorten ``text`` to ``limit`` characters, keeping the tail of paths."""
    if limit <= 0 or len(text) <= limit:
        return text
    if limit <= 3:
        return text[:limit]
    return "…" + text[-(limit - 1) :]


def shorten_home(path: str, home: str | None = None) -> str:
    """Replace the user's home directory with ``~``."""
    home = home if home is not None else os.path.expanduser("~")
    if not home or home == os.sep:
        return path
    home = home.rstrip(os.sep)
    if path == home:
        return "~"
    if path.startswith(home + os.sep):
        return "~" + path[len(home) :]
    return path


def column_widths(cells: list[str]) -> list[int]:
    """Utility kept for symmetry; used by callers that need raw widths."""
    return [len(c) for c in cells]


def round_up(value: float) -> int:
    return math.ceil(value)


__all__ = [
    "Style",
    "ellipsize",
    "human_age",
    "human_count",
    "human_size",
    "parse_duration",
    "parse_size",
    "render_styled_table",
    "render_table",
    "shorten_home",
    "supports_color",
    "terminal_width",
]
