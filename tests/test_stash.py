"""The stash: deleting without burning the bridge."""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

import pytest

from devdust import stash as stash_mod
from devdust.cli import main
from devdust.rules import RULES
from devdust.scanner import Match, SafetyError, scan

NODE_RULE = next(rule for rule in RULES if rule.pattern == "node_modules")


def matches_for(root: Path):
    return scan([root]).matches


def by_name(matches, name: str) -> Match:
    for match in matches:
        if match.path.name == name:
            return match
    raise AssertionError(f"{name} not in {[str(m.path) for m in matches]}")


def run(capsys, *argv):
    code = main(list(argv))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


# -------------------------------------------------------------------- layout


def test_stash_dir_follows_the_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("DEVFDUST_STASH", str(tmp_path / "custom"))
    assert stash_mod.default_stash_dir() == tmp_path / "custom"
    monkeypatch.delenv("DEVFDUST_STASH")
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    assert stash_mod.default_stash_dir() == tmp_path / "state" / "devdust" / "stash"


def test_stash_dir_falls_back_to_home(tmp_path, monkeypatch):
    monkeypatch.delenv("DEVFDUST_STASH", raising=False)
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    assert (
        stash_mod.default_stash_dir()
        == tmp_path / "home" / ".local" / "state" / "devdust" / "stash"
    )


# ---------------------------------------------------------------- stashing


def test_stash_moves_the_directory_and_writes_a_manifest(workspace, tmp_path):
    matches = [by_name(matches_for(workspace), "node_modules")]
    record = stash_mod.stash(matches, roots=[workspace], stash_dir=tmp_path / "stash")

    assert not (workspace / "web" / "node_modules").exists()
    assert (record.directory / stash_mod.MANIFEST).is_file()
    assert record.items[0].original == workspace / "web" / "node_modules"
    assert record.items[0].size > 0
    assert (record.directory / record.items[0].stored).is_dir()


def test_stashed_content_survives(workspace, tmp_path):
    matches = [by_name(matches_for(workspace), "node_modules")]
    record = stash_mod.stash(matches, roots=[workspace], stash_dir=tmp_path / "stash")
    stashed = record.directory / record.items[0].stored
    assert (stashed / "react" / "index.js").is_file()


def test_stash_records_are_listed_newest_first(workspace, tmp_path):
    root = tmp_path / "stash"
    first = stash_mod.stash(
        [by_name(matches_for(workspace), ".next")], roots=[workspace], stash_dir=root
    )
    second = stash_mod.stash(
        [by_name(matches_for(workspace), "__pycache__")], roots=[workspace], stash_dir=root
    )
    ids = [record.id for record in stash_mod.list_records(root)]
    assert set(ids) == {first.id, second.id}
    assert ids[0] >= ids[1]


def test_stash_refuses_a_symlink(workspace, tmp_path):
    link = workspace / "web" / "node_modules"
    fake = Match(path=link, rule=NODE_RULE, size=1, files=1, age_seconds=0.0)
    outside = tmp_path / "outside"
    outside.mkdir()
    (workspace / "web" / "node_modules").rename(tmp_path / "parked")
    (workspace / "web" / "node_modules").symlink_to(outside)
    with pytest.raises(SafetyError):
        stash_mod.stash([fake], roots=[workspace], stash_dir=tmp_path / "stash")
    with pytest.raises(SafetyError):
        stash_mod.stash([fake], roots=[workspace], stash_dir=tmp_path / "stash")


def test_stash_refuses_a_path_outside_the_roots(workspace, tmp_path):
    outside = tmp_path / "elsewhere" / "node_modules"
    outside.mkdir(parents=True)
    fake = Match(path=outside, rule=NODE_RULE, size=0, files=0, age_seconds=0.0)
    with pytest.raises(SafetyError):
        stash_mod.stash([fake], roots=[workspace], stash_dir=tmp_path / "stash")


# --------------------------------------------------------------- restoring


def test_restore_puts_everything_back(workspace, tmp_path):
    matches = matches_for(workspace)
    names = sorted(m.path.name for m in matches)
    record = stash_mod.stash(matches, roots=[workspace], stash_dir=tmp_path / "stash")

    outcome = stash_mod.restore(record)
    assert outcome.restored == len(names)
    assert not outcome.failures
    assert sorted(p.path.name for p in matches) == names
    for original in [item.original for item in record.items]:
        assert original.is_dir()
    assert not record.directory.exists()  # emptied records clean themselves up


def test_restore_reports_a_conflict(workspace, tmp_path):
    match = by_name(matches_for(workspace), "node_modules")
    record = stash_mod.stash([match], roots=[workspace], stash_dir=tmp_path / "stash")
    match.path.mkdir(parents=True)

    outcome = stash_mod.restore(record)
    assert outcome.restored == 0
    assert "already exists" in (outcome.failures[0].error or "")


def test_restore_force_replaces_what_is_there(workspace, tmp_path):
    match = by_name(matches_for(workspace), "node_modules")
    record = stash_mod.stash([match], roots=[workspace], stash_dir=tmp_path / "stash")
    match.path.mkdir(parents=True)
    (match.path / "stray.txt").write_text("new", "utf-8")

    outcome = stash_mod.restore(record, force=True)
    assert outcome.restored == 1
    assert not (match.path / "stray.txt").exists()
    assert (match.path / "react" / "index.js").exists()


def test_restore_only_touches_the_selected_item(workspace, tmp_path):
    matches = matches_for(workspace)
    record = stash_mod.stash(matches, roots=[workspace], stash_dir=tmp_path / "stash")
    target = str(by_name(matches, "node_modules").path)

    outcome = stash_mod.restore(record, only=[target])
    assert outcome.restored == 1
    assert (workspace / "web" / "node_modules").is_dir()
    assert len(stash_mod.list_records(tmp_path / "stash")[0].items) == len(matches) - 1


def test_restore_dry_run_changes_nothing(workspace, tmp_path):
    matches = matches_for(workspace)
    record = stash_mod.stash(matches, roots=[workspace], stash_dir=tmp_path / "stash")
    outcome = stash_mod.restore(record, dry_run=True)
    assert outcome.restored == len(matches)
    assert not any(item.original.exists() for item in record.items)


def test_restore_without_a_stash_says_so(tmp_path):
    with pytest.raises(stash_mod.StashError, match="empty"):
        stash_mod.find_record(None, tmp_path / "stash")


def test_find_record_accepts_a_prefix_and_latest(workspace, tmp_path):
    root = tmp_path / "stash"
    record = stash_mod.stash(
        [by_name(matches_for(workspace), ".next")][:1], roots=[workspace], stash_dir=root
    )
    assert stash_mod.find_record(None, root).id == record.id
    assert stash_mod.find_record("latest", root).id == record.id
    assert stash_mod.find_record(record.id[:8], root).id == record.id
    with pytest.raises(stash_mod.StashError, match="no stash"):
        stash_mod.find_record("nope", root)


# ------------------------------------------------------------------ purging


def test_purge_deletes_one_record(workspace, tmp_path):
    root = tmp_path / "stash"
    record = stash_mod.stash(
        [by_name(matches_for(workspace), "node_modules")], roots=[workspace], stash_dir=root
    )
    stash_mod.purge(record)
    assert not record.directory.exists()
    assert stash_mod.list_records(root) == []


def test_purge_all_and_prune(workspace, tmp_path):
    root = tmp_path / "stash"
    for name in ("node_modules", ".next", "__pycache__"):
        stash_mod.stash([by_name(matches_for(workspace), name)], roots=[workspace], stash_dir=root)
    kept, freed = stash_mod.prune(root, keep=1)
    assert kept == 2
    assert freed > 0
    assert len(stash_mod.list_records(root)) == 1

    count, size = stash_mod.purge_all(root)
    assert count == 1
    assert size > 0
    assert stash_mod.list_records(root) == []


def test_purge_handles_read_only_trees(workspace, tmp_path):
    match = by_name(matches_for(workspace), "node_modules")
    record = stash_mod.stash([match], roots=[workspace], stash_dir=tmp_path / "stash")
    stashed = record.directory / record.items[0].stored
    os.chmod(stashed, stat.S_IRUSR | stat.S_IXUSR)
    try:
        stash_mod.purge(record)
        assert not record.directory.exists()
    finally:
        if stashed.exists():  # pragma: no cover - only when the test itself fails
            os.chmod(stashed, stat.S_IRWXU)


# ---------------------------------------------------------------------- cli


def test_delete_stashes_by_default(workspace, capsys, tmp_path, monkeypatch):
    monkeypatch.setenv("DEVFDUST_STASH", str(tmp_path / "stash"))
    code, out, _ = run(capsys, str(workspace), "--delete", "--yes", "--color", "never")
    assert code == 0
    assert "stashed" in out
    assert "undo" in out
    assert not (workspace / "web" / "node_modules").exists()
    assert stash_mod.list_records(tmp_path / "stash")


def test_hard_delete_is_permanent(workspace, capsys, tmp_path, monkeypatch):
    monkeypatch.setenv("DEVFDUST_STASH", str(tmp_path / "stash"))
    code, out, _ = run(capsys, str(workspace), "--delete", "--hard", "--yes", "--color", "never")
    assert code == 0
    assert "permanent" in out
    assert not (workspace / "web" / "node_modules").exists()
    assert stash_mod.list_records(tmp_path / "stash") == []


def test_stash_command_lists_and_shows(workspace, capsys, tmp_path, monkeypatch):
    monkeypatch.setenv("DEVFDUST_STASH", str(tmp_path / "stash"))
    run(capsys, str(workspace), "--delete", "--yes", "--color", "never")

    code, out, _ = run(capsys, "stash", "--color", "never")
    assert code == 0
    assert "node_modules" in out
    assert "put it back" in out

    record = stash_mod.list_records(tmp_path / "stash")[0]
    code, out, _ = run(capsys, "stash", "show", record.id[:8], "--color", "never")
    assert code == 0
    assert record.id in out


def test_stash_command_on_empty_stash(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("DEVFDUST_STASH", str(tmp_path / "stash"))
    code, out, _ = run(capsys, "stash", "--color", "never")
    assert code == 0
    assert "empty" in out


def test_undo_command(workspace, capsys, tmp_path, monkeypatch):
    monkeypatch.setenv("DEVFDUST_STASH", str(tmp_path / "stash"))
    run(capsys, str(workspace), "--delete", "--yes", "--color", "never")
    code, out, _ = run(capsys, "undo", "--color", "never")
    assert code == 0
    assert "restored" in out
    assert (workspace / "web" / "node_modules").is_dir()


def test_undo_json(workspace, capsys, tmp_path, monkeypatch):
    import json

    monkeypatch.setenv("DEVFDUST_STASH", str(tmp_path / "stash"))
    run(capsys, str(workspace), "--delete", "--yes", "--color", "never")
    code, out, _ = run(capsys, "undo", "--json")
    payload = json.loads(out)
    assert code == 0
    assert payload["restored"] >= 1
    assert all("path" in row for row in payload["results"])


def test_purge_command_refuses_without_a_tty(workspace, capsys, tmp_path, monkeypatch):
    monkeypatch.setenv("DEVFDUST_STASH", str(tmp_path / "stash"))
    monkeypatch.setattr(sys, "stdin", __import__("io").StringIO(""))
    run(capsys, str(workspace), "--delete", "--yes", "--color", "never")
    code, _, err = run(capsys, "purge", "--all")
    assert code == 1
    assert "refusing" in err
    assert stash_mod.list_records(tmp_path / "stash")


def test_purge_command_with_yes(workspace, capsys, tmp_path, monkeypatch):
    monkeypatch.setenv("DEVFDUST_STASH", str(tmp_path / "stash"))
    run(capsys, str(workspace), "--delete", "--yes", "--color", "never")
    code, out, _ = run(capsys, "purge", "--all", "--yes")
    assert code == 0
    assert "gone for good" in out
    assert stash_mod.list_records(tmp_path / "stash") == []


def test_json_delete_reports_the_stash(workspace, capsys, tmp_path, monkeypatch):
    import json

    monkeypatch.setenv("DEVFDUST_STASH", str(tmp_path / "stash"))
    code, out, _ = run(capsys, str(workspace), "--delete", "--json")
    payload = json.loads(out)
    assert code == 0
    assert payload["stash"]["count"] >= 1
    assert payload["stash"]["items"][0]["original"]


def test_stash_prunes_old_records(workspace, capsys, tmp_path, monkeypatch):
    from devdust.cli import STASH_KEEP

    monkeypatch.setenv("DEVFDUST_STASH", str(tmp_path / "stash"))
    root = tmp_path / "stash"
    for _ in range(STASH_KEEP + 3):
        (workspace / "web" / "node_modules").mkdir(parents=True, exist_ok=True)
        run(capsys, str(workspace), "--delete", "--yes", "--color", "never")
    assert len(stash_mod.list_records(root)) <= STASH_KEEP
