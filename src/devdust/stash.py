"""Reversible removal: move directories into a stash instead of ``rm -rf``.

Deleting a cache is supposed to be cheap, but "supposed to" is doing a lot of
work in that sentence. ``devdust --delete`` therefore moves every match into a
stash directory and writes a manifest next to it, so a wrong ``--kinds`` or an
over-eager ``--top`` costs you a ``devdust undo`` instead of a rebuild.

Layout::

    <stash>/20261030T182000-4f2a/
        manifest.json
        1/node_modules/
        2/__pycache__/

The manifest is the source of truth: it keeps the original absolute path, the
measured size and the rule that matched. Nothing here ever follows a symlink.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import stat
import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .scanner import Match, _guard, _unlock_tree

MANIFEST = "manifest.json"
FORMAT_VERSION = 1


class StashError(Exception):
    """The stash is unusable, or the requested record is not there."""


# --------------------------------------------------------------------- layout


def default_stash_dir() -> Path:
    """Where stashes live unless told otherwise."""
    override = os.environ.get("DEVFDUST_STASH")
    if override:
        return Path(override).expanduser()
    state = os.environ.get("XDG_STATE_HOME")
    base = Path(state).expanduser() if state else Path.home() / ".local" / "state"
    return base / "devdust" / "stash"


def _new_id(now: float | None = None) -> str:
    stamp = time.strftime("%Y%m%dT%H%M%S", time.localtime(now if now is not None else time.time()))
    suffix = os.urandom(2).hex()
    return f"{stamp}-{suffix}"


# ---------------------------------------------------------------------- types


@dataclass
class StashedItem:
    """One directory waiting in the stash."""

    original: Path
    stored: str
    size: int
    files: int
    kind: str
    confidence: str

    @property
    def name(self) -> str:
        return self.original.name

    def as_dict(self) -> dict[str, Any]:
        return {
            "original": str(self.original),
            "stored": self.stored,
            "size": self.size,
            "files": self.files,
            "kind": self.kind,
            "confidence": self.confidence,
        }


@dataclass
class StashRecord:
    """A manifest on disk, loaded or freshly written."""

    id: str
    directory: Path
    created: str
    label: str = ""
    items: list[StashedItem] = field(default_factory=list)

    @property
    def total_size(self) -> int:
        return sum(item.size for item in self.items)

    @property
    def total_files(self) -> int:
        return sum(item.files for item in self.items)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "created": self.created,
            "label": self.label,
            "directory": str(self.directory),
            "size": self.total_size,
            "files": self.total_files,
            "count": len(self.items),
            "items": [item.as_dict() for item in self.items],
        }

    def to_manifest(self) -> dict[str, Any]:
        return {
            "format": FORMAT_VERSION,
            "id": self.id,
            "created": self.created,
            "label": self.label,
            "items": [item.as_dict() for item in self.items],
        }


@dataclass
class Restore:
    item: StashedItem
    ok: bool
    error: str | None = None


@dataclass
class RestoreResult:
    record: StashRecord
    restores: list[Restore] = field(default_factory=list)

    @property
    def restored(self) -> int:
        return sum(1 for r in self.restores if r.ok)

    @property
    def failures(self) -> list[Restore]:
        return [r for r in self.restores if not r.ok]

    @property
    def size(self) -> int:
        return sum(r.item.size for r in self.restores if r.ok)


# --------------------------------------------------------------- write / read


def _write_manifest(record: StashRecord) -> None:
    path = record.directory / MANIFEST
    path.write_text(json.dumps(record.to_manifest(), ensure_ascii=False, indent=2), "utf-8")


def _read_manifest(directory: Path) -> StashRecord:
    path = directory / MANIFEST
    try:
        payload = json.loads(path.read_text("utf-8"))
    except OSError as exc:
        raise StashError(f"cannot read {path}: {exc.strerror or exc}") from exc
    except json.JSONDecodeError as exc:
        raise StashError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict) or "items" not in payload:
        raise StashError(f"{path} is not a devdust manifest")
    items = [
        StashedItem(
            original=Path(str(raw["original"])),
            stored=str(raw["stored"]),
            size=int(raw.get("size", 0)),
            files=int(raw.get("files", 0)),
            kind=str(raw.get("kind", "unknown")),
            confidence=str(raw.get("confidence", "safe")),
        )
        for raw in payload.get("items", [])
    ]
    return StashRecord(
        id=str(payload.get("id", directory.name)),
        directory=directory,
        created=str(payload.get("created", "")),
        label=str(payload.get("label", "")),
        items=items,
    )


def list_records(stash_dir: Path | None = None) -> list[StashRecord]:
    """Every stash on disk, newest first. Unreadable records are skipped."""
    root = Path(stash_dir or default_stash_dir()).expanduser()
    if not root.is_dir():
        return []
    records: list[StashRecord] = []
    for child in root.iterdir():
        if not child.is_dir() or not (child / MANIFEST).exists():
            continue
        with contextlib.suppress(StashError):
            record = _read_manifest(child)
            if record.items:
                records.append(record)
    records.sort(key=lambda r: (r.created, r.id), reverse=True)
    return records


def find_record(which: str | None, stash_dir: Path | None = None) -> StashRecord:
    """Resolve ``which`` — an id, ``latest`` or ``None`` — to a record."""
    records = list_records(stash_dir)
    if not records:
        raise StashError("stash is empty — nothing to restore")
    if which in (None, "", "latest", "last"):
        return records[0]
    for record in records:
        if record.id == which:
            return record
    matches = [r for r in records if r.id.startswith(which)]
    if len(matches) == 1:
        return matches[0]
    if matches:
        raise StashError(f"'{which}' is ambiguous: {', '.join(r.id for r in matches)}")
    raise StashError(f"no stash called '{which}'")


# ------------------------------------------------------------------ stashing


def stash(
    matches: Sequence[Match],
    *,
    roots: Sequence[Path],
    stash_dir: Path | None = None,
    label: str = "",
) -> StashRecord:
    """Move ``matches`` into the stash and return the written record."""
    root = Path(stash_dir or default_stash_dir()).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    record = StashRecord(
        id=_new_id(),
        directory=root / "",
        created=time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
        label=label,
    )
    record.directory = root / record.id
    record.directory.mkdir(parents=True, exist_ok=True)

    for match in matches:
        _guard(match.path, roots)
        index = len(record.items) + 1
        stored = f"{index}/{match.path.name}"
        target = record.directory / stored
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.move(str(match.path), str(target))
        except OSError:
            _unlock_tree(match.path)
            try:
                shutil.move(str(match.path), str(target))
            except OSError as exc:
                raise StashError(f"cannot stash {match.path}: {exc.strerror or exc}") from exc
        record.items.append(
            StashedItem(
                original=match.path,
                stored=stored,
                size=match.size,
                files=match.files,
                kind=match.kind,
                confidence=match.confidence,
            )
        )
        _write_manifest(record)

    _write_manifest(record)
    return record


# ----------------------------------------------------------------- restoring


def restore(
    record: StashRecord,
    *,
    only: Iterable[str] | None = None,
    force: bool = False,
    dry_run: bool = False,
) -> RestoreResult:
    """Put the stashed directories back where they came from."""
    wanted = {str(Path(os.path.expanduser(str(sel)))) for sel in only or ()}
    result = RestoreResult(record=record)
    for item in record.items:
        if wanted and not any(
            str(item.original) == sel
            or item.original.name == sel
            or str(item.original).endswith(sel.rstrip("/"))
            for sel in wanted
        ):
            continue
        target = item.original
        source = record.directory / item.stored
        if not source.exists():
            result.restores.append(Restore(item=item, ok=False, error="missing from the stash"))
            continue
        if target.exists() or target.is_symlink():
            if not force:
                result.restores.append(
                    Restore(item=item, ok=False, error="already exists (use --force to replace)")
                )
                continue
            if dry_run:
                result.restores.append(Restore(item=item, ok=True))
                continue
            try:
                if target.is_dir() and not target.is_symlink():
                    _unlock_tree(target)
                    shutil.rmtree(target)
                else:
                    target.unlink()
            except OSError as exc:
                result.restores.append(Restore(item=item, ok=False, error=exc.strerror or str(exc)))
                continue
        if dry_run:
            result.restores.append(Restore(item=item, ok=True))
            continue
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(target))
        except OSError as exc:
            result.restores.append(Restore(item=item, ok=False, error=exc.strerror or str(exc)))
            continue
        if not target.exists():
            result.restores.append(
                Restore(item=item, ok=False, error="directory did not come back")
            )
            continue
        result.restores.append(Restore(item=item, ok=True))

    if not dry_run and result.restored:
        _forget(record, {r.item.stored for r in result.restores if r.ok})
    return result


def _forget(record: StashRecord, stored: set[str]) -> None:
    """Drop restored items from the manifest, deleting the record when empty."""
    record.items = [item for item in record.items if item.stored not in stored]
    if record.items:
        with contextlib.suppress(OSError):
            _write_manifest(record)
        return
    purge(record.directory)


# ------------------------------------------------------------------ purging


def purge(directory: Path | StashRecord) -> None:
    """Delete a whole stash record for real."""
    path = directory.directory if isinstance(directory, StashRecord) else Path(directory)
    if not path.exists():
        return
    _unlock_tree(path)
    try:
        shutil.rmtree(path)
    except OSError as exc:
        raise StashError(f"cannot purge {path}: {exc.strerror or exc}") from exc


def purge_all(stash_dir: Path | None = None) -> tuple[int, int]:
    """Delete every record; returns (records, bytes)."""
    records = list_records(stash_dir)
    freed = 0
    for record in records:
        freed += record.total_size
        purge(record)
    root = Path(stash_dir or default_stash_dir()).expanduser()
    with contextlib.suppress(OSError):
        os.rmdir(root)  # only succeeds when nothing is left behind
    return len(records), freed


def prune(stash_dir: Path | None = None, *, keep: int = 5) -> tuple[int, int]:
    """Keep the ``keep`` newest records, purge the rest."""
    records = list_records(stash_dir)
    freed = 0
    doomed = records[keep:] if keep >= 0 else []
    for record in doomed:
        freed += record.total_size
        purge(record)
    return len(doomed), freed


def probe_readonly(path: Path) -> bool:  # pragma: no cover - convenience for tests
    mode = path.stat().st_mode if path.exists() else 0
    return not mode & stat.S_IWUSR


__all__ = [
    "MANIFEST",
    "Restore",
    "RestoreResult",
    "StashError",
    "StashRecord",
    "StashedItem",
    "default_stash_dir",
    "find_record",
    "list_records",
    "prune",
    "purge",
    "purge_all",
    "restore",
    "stash",
]
