"""Filesystem walking, size accounting and safe removal."""

from __future__ import annotations

import contextlib
import os
import shutil
import stat
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import timedelta
from fnmatch import fnmatchcase
from pathlib import Path

from .rules import RULES, Rule

#: Never walked into: version control internals, and virtual filesystems.
DEFAULT_EXCLUDES: tuple[str, ...] = (".git", ".hg", ".svn")

#: Hard safety net so a bind-mount loop can never spin forever.
MAX_WALK_DEPTH = 64


class ScanError(Exception):
    """A root that cannot be scanned at all (missing, not a directory)."""


class SafetyError(Exception):
    """devdust refused to delete something it does not understand."""


@dataclass(frozen=True)
class Match:
    """A directory that devdust considers reclaimable."""

    path: Path
    rule: Rule
    size: int
    files: int
    age_seconds: float

    @property
    def kind(self) -> str:
        return self.rule.kind

    @property
    def confidence(self) -> str:
        return self.rule.confidence


@dataclass
class ScanResult:
    roots: tuple[Path, ...]
    matches: list[Match] = field(default_factory=list)
    unreadable: int = 0
    scanned_dirs: int = 0

    @property
    def total_size(self) -> int:
        return sum(m.size for m in self.matches)

    @property
    def total_files(self) -> int:
        return sum(m.files for m in self.matches)

    def by_confidence(self) -> dict[str, int]:
        totals: dict[str, int] = {}
        for match in self.matches:
            totals[match.confidence] = totals.get(match.confidence, 0) + match.size
        return totals


@dataclass
class Removal:
    match: Match
    ok: bool
    error: str | None = None


@dataclass
class RemovalResult:
    removals: list[Removal] = field(default_factory=list)

    @property
    def freed(self) -> int:
        return sum(r.match.size for r in self.removals if r.ok)

    @property
    def removed(self) -> int:
        return sum(1 for r in self.removals if r.ok)

    @property
    def failures(self) -> list[Removal]:
        return [r for r in self.removals if not r.ok]


# ------------------------------------------------------------------ scanning


def _resolve_roots(roots: Iterable[Path | str]) -> tuple[Path, ...]:
    resolved: list[Path] = []
    for raw in roots:
        path = Path(os.path.expanduser(str(raw))).resolve()
        if not path.exists():
            raise ScanError(f"no such directory: {raw}")
        if not path.is_dir():
            raise ScanError(f"not a directory: {raw}")
        if path not in resolved:
            resolved.append(path)
    if not resolved:
        raise ScanError("no directories to scan")
    return tuple(resolved)


def measure(path: Path) -> tuple[int, int, float]:
    """Total size, file count and newest mtime of the tree at ``path``.

    Symlinks are never followed, so a link pointing at ``/`` cannot blow up the
    numbers (or the walk). Unreadable entries are skipped silently.
    """
    size = 0
    files = 0
    newest = 0.0
    stack: list[tuple[Path, int]] = [(path, 0)]
    while stack:
        directory, depth = stack.pop()
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    try:
                        if entry.is_symlink():
                            continue
                        if entry.is_dir(follow_symlinks=False):
                            if depth + 1 < MAX_WALK_DEPTH:
                                stack.append((Path(entry.path), depth + 1))
                        elif entry.is_file(follow_symlinks=False):
                            info = entry.stat(follow_symlinks=False)
                            size += info.st_size
                            files += 1
                            if info.st_mtime > newest:
                                newest = info.st_mtime
                    except OSError:
                        continue
        except OSError:
            continue
    if files == 0:  # empty tree: fall back to the directory's own timestamp
        with contextlib.suppress(OSError):
            newest = path.stat().st_mtime
    return size, files, newest


def _compile_excludes(excludes: Sequence[str]) -> tuple[str, ...]:
    names = list(DEFAULT_EXCLUDES)
    for pattern in excludes:
        pattern = str(pattern).strip()
        if pattern:
            names.append(pattern)
    return tuple(names)


def scan(
    roots: Iterable[Path | str],
    *,
    rules: Sequence[Rule] = RULES,
    excludes: Sequence[str] = (),
    min_size: int = 0,
    older_than: timedelta | None = None,
    max_depth: int | None = None,
    now: float | None = None,
    on_enter: Callable[[Path], None] | None = None,
) -> ScanResult:
    """Walk ``roots`` and collect every directory that matches ``rules``.

    A matched directory is *measured* and then pruned from the walk: nested
    caches inside ``node_modules`` are irrelevant once the parent is gone, and
    counting them twice would inflate the reported total.

    The roots themselves are never proposed for deletion (only their
    descendants), which keeps ``devdust ~/project/node_modules`` from offering
    to nuke the directory you pointed it at.
    """
    root_paths = _resolve_roots(roots)
    ignore = _compile_excludes(excludes)
    result = ScanResult(roots=root_paths)
    now = now if now is not None else _now()
    cutoff = older_than.total_seconds() if older_than is not None else None

    for root in root_paths:
        stack: list[tuple[Path, int]] = [(root, 0)]
        while stack:
            directory, depth = stack.pop()
            if on_enter is not None:
                on_enter(directory)
            result.scanned_dirs += 1
            try:
                with os.scandir(directory) as entries:
                    children = sorted(entries, key=lambda e: e.name)
            except OSError:
                result.unreadable += 1
                continue

            for entry in children:
                if any(fnmatchcase(entry.name, pattern) for pattern in ignore):
                    continue
                try:
                    if entry.is_symlink() or not entry.is_dir(follow_symlinks=False):
                        continue
                except OSError:
                    continue

                child = Path(entry.path)
                depth_here = depth + 1
                rule = _match_rule(entry.name, rules)
                if rule is not None:
                    size, files, newest = measure(child)
                    age = max(0.0, now - newest)
                    if size < min_size:
                        continue
                    if cutoff is not None and age < cutoff:
                        continue
                    result.matches.append(
                        Match(
                            path=child,
                            rule=rule,
                            size=size,
                            files=files,
                            age_seconds=age,
                        )
                    )
                    continue  # pruned: no reason to look inside

                if max_depth is not None and depth_here >= max_depth:
                    continue
                if depth_here >= MAX_WALK_DEPTH:
                    continue
                stack.append((child, depth_here))

    result.matches.sort(key=lambda m: (-m.size, str(m.path)))
    return result


def _match_rule(name: str, rules: Sequence[Rule]) -> Rule | None:
    for rule in rules:
        if rule.matches(name):
            return rule
    return None


def _now() -> float:
    return time.time()


# ------------------------------------------------------------------ deleting


def _guard(path: Path, roots: Sequence[Path]) -> None:
    """Refuse anything that is not a plain directory inside a scanned root."""
    if path.is_symlink():
        raise SafetyError(f"refusing to delete symlink: {path}")
    if not path.is_dir():
        raise SafetyError(f"not a directory (anymore): {path}")
    if path == Path(path.anchor):
        raise SafetyError(f"refusing to delete filesystem root: {path}")
    try:
        home = Path.home()
    except (RuntimeError, KeyError):  # pragma: no cover - exotic envs
        home = None
    if home is not None and path in (home, Path.cwd(), *roots):
        raise SafetyError(f"refusing to delete a scan root: {path}")
    for root in roots:
        if path == root or not path.is_relative_to(root):
            raise SafetyError(f"{path} is outside the scanned roots")


def _unlock_tree(path: Path) -> None:
    """Best effort: make every directory under ``path`` writable again.

    Read-only directories (``node_modules`` built inside a container, caches
    copied from a backup) make ``shutil.rmtree`` fail halfway through; making
    the directories writable first is what makes deletion actually work.
    """
    for current, dirs, _files in os.walk(path, onerror=lambda _e: None):
        for name in dirs:
            with contextlib.suppress(OSError):
                os.chmod(os.path.join(current, name), stat.S_IRWXU)
    with contextlib.suppress(OSError):
        os.chmod(path, stat.S_IRWXU)


def remove(
    matches: Sequence[Match],
    *,
    roots: Sequence[Path],
    dry_run: bool = True,
) -> RemovalResult:
    """Delete ``matches`` (or pretend to, when ``dry_run`` is true)."""
    result = RemovalResult()
    for match in matches:
        if dry_run:
            result.removals.append(Removal(match=match, ok=True))
            continue
        try:
            _guard(match.path, roots)
        except SafetyError as exc:
            result.removals.append(Removal(match=match, ok=False, error=str(exc)))
            continue
        try:
            shutil.rmtree(match.path)
        except OSError:
            # second chance: unlock the tree and try once more
            _unlock_tree(match.path)
            try:
                shutil.rmtree(match.path)
            except OSError as exc:
                result.removals.append(
                    Removal(match=match, ok=False, error=exc.strerror or str(exc))
                )
                continue
        if match.path.exists():
            result.removals.append(
                Removal(match=match, ok=False, error="directory survived removal")
            )
            continue
        result.removals.append(Removal(match=match, ok=True))
    return result


__all__ = [
    "DEFAULT_EXCLUDES",
    "Match",
    "Removal",
    "RemovalResult",
    "SafetyError",
    "ScanError",
    "ScanResult",
    "measure",
    "remove",
    "scan",
]
