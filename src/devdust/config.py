"""Optional per-project configuration: ``.devdust.toml``.

Discovery order:

1. ``--config PATH`` (explicit, always wins)
2. ``.devdust.toml`` in the current directory, then in each parent directory
   (the search stops at ``$HOME``)
3. ``$XDG_CONFIG_HOME/devdust/config.toml`` (default ``~/.config/...``)

Only *preferences* live here. ``--delete`` and ``--yes`` are deliberately not
configurable: deleting files has to be an explicit decision every single time,
never an ambient default inherited from a file someone else committed.
"""

from __future__ import annotations

import contextlib
import difflib
import os
import tomllib
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from . import rules as rules_mod
from .formatting import parse_duration, parse_size

CONFIG_FILENAME = ".devdust.toml"
TABLE = "devdust"

SORT_CHOICES = ("size", "age", "path", "kind")
COLOR_CHOICES = ("auto", "always", "never")

#: Every key the ``[devdust]`` table may contain.
KNOWN_KEYS = (
    "paths",
    "exclude",
    "kinds",
    "min_size",
    "older_than",
    "include_review",
    "top",
    "sort",
    "color",
    "summary",
)


class ConfigError(Exception):
    """A config file that exists but cannot be used."""


@dataclass(frozen=True)
class Config:
    """Validated settings from a config file (empty when there is none)."""

    source: Path | None = None
    provided: frozenset[str] = frozenset()
    paths: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()
    kinds: tuple[str, ...] = ()
    min_size: int = 0
    older_than: timedelta | None = None
    include_review: bool = False
    top: int | None = None
    sort: str | None = None
    color: str | None = None
    summary: bool = False

    def as_defaults(self) -> dict[str, object]:
        """The keys the file actually set, ready for ``ArgumentParser.set_defaults``."""
        mapping: dict[str, object] = {
            "exclude": list(self.exclude),
            "kinds": list(self.kinds) or None,
            "min_size": self.min_size,
            "older_than": self.older_than,
            "include_review": self.include_review,
            "top": self.top,
            "sort": self.sort,
            "color": self.color,
            "summary": self.summary,
        }
        return {key: mapping[key] for key in self.provided if key in mapping}


# ----------------------------------------------------------------- discovery


def discover(start: Path | str | None = None, home: Path | None = None) -> Path | None:
    """Look for a config file near ``start`` (default: the working directory)."""
    home = home or Path.home()
    with contextlib.suppress(OSError):  # pragma: no cover - exotic environments
        home = home.resolve()
    current = Path(start).expanduser() if start is not None else Path.cwd()
    with contextlib.suppress(OSError):  # pragma: no cover
        current = current.resolve()

    for directory in (current, *current.parents):
        candidate = directory / CONFIG_FILENAME
        if candidate.is_file():
            return candidate
        if directory == home:  # never read configs from above the home directory
            break

    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg).expanduser() if xdg else home / ".config"
    candidate = base / "devdust" / "config.toml"
    return candidate if candidate.is_file() else None


# -------------------------------------------------------------------- loading


def load(path: Path | str) -> Config:
    """Read and validate a config file."""
    path = Path(path).expanduser()
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"cannot read {path}: {exc.strerror or exc}") from exc
    try:
        raw = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path}: invalid TOML ({exc})") from exc

    table = raw.get(TABLE, {})
    if not isinstance(table, dict):
        raise ConfigError(f"{path}: [{TABLE}] must be a table")
    _reject_unknown_keys(table, path)

    values: dict[str, object] = {}
    provided = frozenset(table)
    if "paths" in table:
        values["paths"] = _string_tuple("paths", table["paths"], path)
    if "exclude" in table:
        values["exclude"] = _string_tuple("exclude", table["exclude"], path)
    if "kinds" in table:
        values["kinds"] = _kinds("kinds", table["kinds"], path)
    if "min_size" in table:
        values["min_size"] = _size("min_size", table["min_size"], path)
    if "older_than" in table:
        values["older_than"] = _duration("older_than", table["older_than"], path)
    if "include_review" in table:
        values["include_review"] = _boolean("include_review", table["include_review"], path)
    if "summary" in table:
        values["summary"] = _boolean("summary", table["summary"], path)
    if "top" in table:
        values["top"] = _integer("top", table["top"], path)
    if "sort" in table:
        values["sort"] = _choice("sort", table["sort"], SORT_CHOICES, path)
    if "color" in table:
        values["color"] = _choice("color", table["color"], COLOR_CHOICES, path)

    return Config(source=path, provided=provided, **values)  # type: ignore[arg-type]


def _reject_unknown_keys(table: dict[str, object], path: Path) -> None:
    unknown = sorted(set(table) - set(KNOWN_KEYS))
    if not unknown:
        return
    hints = []
    for key in unknown:
        close = difflib.get_close_matches(key, KNOWN_KEYS, n=1)
        hints.append(f"{key!r}" + (f" (did you mean {close[0]!r}?)" if close else ""))
    raise ConfigError(
        f"{path}: unknown key(s) in [{TABLE}]: {', '.join(hints)}. "
        f"Known keys: {', '.join(KNOWN_KEYS)}"
    )


def _string_tuple(key: str, value: object, path: Path) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ConfigError(f"{path}: {key} must be a string or an array of strings")
    return tuple(item for item in value if item.strip())


def _kinds(key: str, value: object, path: Path) -> tuple[str, ...]:
    chosen = _string_tuple(key, value, path)
    known = set(rules_mod.kinds())
    unknown = [kind for kind in chosen if kind not in known]
    if unknown:
        raise ConfigError(
            f"{path}: unknown {key}: {', '.join(unknown)} (choose from: {', '.join(sorted(known))})"
        )
    return chosen


def _size(key: str, value: object, path: Path) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        if value < 0:
            raise ConfigError(f"{path}: {key} cannot be negative")
        return value
    if isinstance(value, str):
        try:
            return parse_size(value)
        except ValueError as exc:
            raise ConfigError(f"{path}: {key}: {exc}") from exc
    raise ConfigError(f'{path}: {key} must be a size string like "20MB" or a byte count')


def _duration(key: str, value: object, path: Path) -> timedelta:
    if not isinstance(value, str):
        raise ConfigError(f'{path}: {key} must be a duration string like "30d"')
    try:
        return parse_duration(value)
    except ValueError as exc:
        raise ConfigError(f"{path}: {key}: {exc}") from exc


def _boolean(key: str, value: object, path: Path) -> bool:
    if not isinstance(value, bool):
        raise ConfigError(f"{path}: {key} must be true or false")
    return value


def _integer(key: str, value: object, path: Path) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ConfigError(f"{path}: {key} must be a whole number")
    if value < 0:
        raise ConfigError(f"{path}: {key} cannot be negative")
    return value


def _choice(key: str, value: object, choices: tuple[str, ...], path: Path) -> str:
    if not isinstance(value, str) or value not in choices:
        raise ConfigError(f"{path}: {key} must be one of: {', '.join(choices)}")
    return value


# ------------------------------------------------------------------- template


def template() -> str:
    """A starter config file: every setting documented, nothing enabled."""
    return """\
# .devdust.toml — preferences for `devdust` in this directory tree.
#
# devdust reads this file from the current directory or any parent (stopping at
# your home directory), and falls back to $XDG_CONFIG_HOME/devdust/config.toml.
# Command line flags always win over anything written here, and `--delete` /
# `--yes` are deliberately *not* configurable: removing files stays an explicit
# decision every single time.
#
# Everything below is commented out — `devdust init` changes nothing until you
# uncomment what you want.

[devdust]
# Directories to scan when none are given on the command line.
# paths = ["~/code", "~/oss"]

# Minimum size before a match is worth reporting ("20MB" or a byte count).
# min_size = "20MB"

# Only report directories nobody has touched for this long: 12h, 30d, 2w.
# older_than = "30d"

# Ecosystems to look at (see `devdust rules` for the full list).
# kinds = ["node", "python", "rust"]

# Extra directory names to skip; shell globs are supported.
# exclude = ["vendor", "*-backup"]

# Also consider ambiguous names such as build/, bin/, target/.
# include_review = false

# How many entries to print (0 = all) and in which order.
# top = 25
# sort = "size"

# auto | always | never
# color = "auto"

# Add the "where the space goes" breakdown after the table.
# summary = false
"""


__all__ = [
    "COLOR_CHOICES",
    "CONFIG_FILENAME",
    "KNOWN_KEYS",
    "SORT_CHOICES",
    "Config",
    "ConfigError",
    "discover",
    "load",
    "template",
]
