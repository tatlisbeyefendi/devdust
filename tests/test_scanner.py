"""Tests for scanning, size accounting, safety guards and removal."""

from __future__ import annotations

import contextlib
import os
from datetime import timedelta
from pathlib import Path

import pytest

from devdust import rules as rules_mod
from devdust.scanner import (
    Match,
    SafetyError,
    ScanError,
    measure,
    remove,
    scan,
)

from .conftest import touch


def scan_default(roots, **kwargs):
    """Scan the way the CLI does by default: safe rules only."""
    return scan(roots, rules=rules_mod.select(), **kwargs)


# ------------------------------------------------------------------ scanning


def test_finds_safe_matches(workspace):
    result = scan_default([workspace])
    found = {m.path.relative_to(workspace).as_posix() for m in result.matches}
    assert found == {"web/node_modules", "web/.next", "api/__pycache__"}


def test_review_rules_only_when_asked(workspace):
    wide = scan([workspace], rules=rules_mod.select(include_review=True))
    assert "build" in {m.path.name for m in wide.matches}


def test_sizes_are_summed_over_the_whole_subtree(workspace):
    result = scan_default([workspace])
    node_modules = next(m for m in result.matches if m.path.name == "node_modules")
    # 2048 + 4096 (the nested .cache) — counted once, from the parent
    assert node_modules.size == 2048 + 4096
    assert node_modules.files == 2


def test_nested_matches_are_pruned_not_reported(workspace):
    result = scan_default([workspace])
    names = {m.path.name for m in result.matches}
    assert ".cache" not in names  # inside node_modules, already accounted for


def test_git_directory_is_never_entered(workspace):
    result = scan_default([workspace])
    assert all(".git" not in m.path.parts for m in result.matches)


def test_roots_are_never_proposed_for_deletion(workspace):
    result = scan([workspace / "web" / "node_modules"], rules=rules_mod.select())
    assert result.matches == []


def test_multiple_roots(tmp_path):
    for name in ("a", "b"):
        touch(tmp_path / name / "node_modules" / "x.js", 100)
    result = scan_default([tmp_path / "a", tmp_path / "b"])
    assert len(result.matches) == 2
    assert result.total_size == 200


def test_relative_and_tilde_paths(tmp_path, monkeypatch):
    touch(tmp_path / "node_modules" / "x.js", 10)
    monkeypatch.chdir(tmp_path)
    assert len(scan_default(["."]).matches) == 1
    monkeypatch.setenv("HOME", str(tmp_path))
    assert scan_default(["~"]).roots == (tmp_path.resolve(),)


def test_missing_root_raises():
    with pytest.raises(ScanError):
        scan_default(["/nope/definitely/not/here"])


def test_file_instead_of_directory_raises(tmp_path):
    file_path = tmp_path / "file.txt"
    file_path.write_text("hi")
    with pytest.raises(ScanError):
        scan_default([file_path])


def test_min_size_filter(workspace):
    result = scan_default([workspace], min_size=2000)
    assert all(m.size >= 2000 for m in result.matches)
    assert {m.path.name for m in result.matches} == {"node_modules"}


def test_older_than_filter(workspace):
    # __pycache__ in the fixture is 40 days old, everything else was just made
    quiet = scan_default([workspace], older_than=timedelta(days=7))
    assert {m.path.name for m in quiet.matches} == {"__pycache__"}
    nothing = scan_default([workspace], older_than=timedelta(days=90))
    assert nothing.matches == []


def test_exclude_globs(workspace):
    result = scan_default([workspace], excludes=["node_modules", ".next"])
    assert result.matches == [] or {m.path.name for m in result.matches} == {"__pycache__"}


def test_max_depth_limits_the_walk(workspace):
    shallow = scan_default([workspace], max_depth=1)
    assert shallow.matches == []


def test_symlinks_are_not_followed(workspace, huge_dir):
    link = workspace / "web" / "node_modules"  # replaces real dir with a symlink
    os.rename(link, link.with_name("node_modules_real"))
    link.symlink_to(huge_dir, target_is_directory=True)
    result = scan_default([workspace])
    assert all("50_000" != str(m.size) for m in result.matches)
    matched = {m.path.name for m in result.matches}
    assert "node_modules" not in matched  # symlinks are skipped entirely


def test_scanned_dirs_counter(workspace):
    result = scan_default([workspace])
    assert result.scanned_dirs > 0
    assert result.unreadable == 0


# ------------------------------------------------------------------ measure


def test_measure_sums_files_and_reports_newest_mtime(tmp_path):
    touch(tmp_path / "a" / "one.bin", 100, age_days=10)
    touch(tmp_path / "a" / "deep" / "two.bin", 200, age_days=1)
    size, files, newest = measure(tmp_path / "a")
    assert (size, files) == (300, 2)
    assert newest > 0


def test_measure_ignores_symlinked_files(tmp_path, huge_dir):
    target = tmp_path / "cache"
    touch(target / "real.bin", 10)
    (target / "link.bin").symlink_to(huge_dir / "big.js")
    size, files, _ = measure(target)
    assert (size, files) == (10, 1)


def test_age_is_computed_from_the_newest_file(workspace):
    result = scan_default([workspace])
    pycache = next(m for m in result.matches if m.path.name == "__pycache__")
    assert pycache.age_seconds > 30 * 86400


# ------------------------------------------------------------------- removal


def test_dry_run_keeps_everything(workspace):
    result = scan_default([workspace])
    removal = remove(result.matches, roots=result.roots, dry_run=True)
    assert removal.removed == len(result.matches)
    assert removal.freed == result.total_size
    assert (workspace / "web" / "node_modules").is_dir()


def test_delete_removes_directories(workspace):
    result = scan_default([workspace])
    removal = remove(result.matches, roots=result.roots, dry_run=False)
    assert removal.failures == []
    assert removal.freed == result.total_size
    assert not (workspace / "web" / "node_modules").exists()
    assert not (workspace / "api" / "__pycache__").exists()
    # sources and .git survive
    assert (workspace / "web" / "src" / "main.ts").is_file()
    assert (workspace / ".git" / "node_modules" / "hook.js").is_file()


def test_delete_refuses_a_scan_root(workspace):
    match = Match(
        path=workspace,
        rule=rules_mod.match("node_modules"),
        size=1,
        files=1,
        age_seconds=0,
    )
    removal = remove([match], roots=[workspace], dry_run=False)
    assert removal.removed == 0
    assert workspace.is_dir()
    assert "root" in (removal.failures[0].error or "")


def test_delete_refuses_paths_outside_the_roots(workspace, tmp_path):
    outside = tmp_path / "elsewhere" / "node_modules"
    touch(outside / "x.js", 10)
    match = Match(
        path=outside, rule=rules_mod.match("node_modules"), size=10, files=1, age_seconds=0
    )
    removal = remove([match], roots=[workspace], dry_run=False)
    assert removal.removed == 0
    assert outside.is_dir()


def test_delete_refuses_symlinks(workspace, huge_dir):
    link = workspace / "link"
    link.symlink_to(huge_dir, target_is_directory=True)
    match = Match(path=link, rule=rules_mod.match("node_modules"), size=1, files=1, age_seconds=0)
    removal = remove([match], roots=[workspace], dry_run=False)
    assert removal.removed == 0
    assert huge_dir.is_dir()


def test_missing_directory_is_reported_not_raised(workspace):
    ghost = workspace / "node_modules"
    match = Match(path=ghost, rule=rules_mod.match("node_modules"), size=1, files=1, age_seconds=0)
    removal = remove([match], roots=[workspace], dry_run=False)
    assert removal.failures and "not a directory" in (removal.failures[0].error or "")


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores directory permissions")
def test_read_only_entries_are_made_writable(tmp_path):
    root = tmp_path / "root"
    locked = root / "node_modules" / "locked"
    touch(locked / "file.js", 10)
    os.chmod(locked, 0o500)
    result = scan_default([root])
    removal = remove(result.matches, roots=result.roots, dry_run=False)
    try:
        assert removal.failures == []
        assert not (root / "node_modules").exists()
    finally:
        with contextlib.suppress(OSError):
            os.chmod(locked, 0o700)


def test_guard_accepts_a_plain_directory(tmp_path):
    from devdust.scanner import _guard

    root = tmp_path / "root"
    target = root / "node_modules"
    target.mkdir(parents=True)
    _guard(target, [root])  # does not raise


def test_guard_rejects_filesystem_root():
    from devdust.scanner import _guard

    with pytest.raises(SafetyError):
        _guard(Path(Path("/").anchor), [Path("/")])
