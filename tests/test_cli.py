"""End-to-end tests for the command line interface."""

from __future__ import annotations

import io
import json
import re
import sys
from pathlib import Path

import pytest

from devdust import __version__
from devdust.cli import main


def run(capsys, *argv):
    code = main(list(argv))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def no_tty(monkeypatch):
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))


def test_dry_run_by_default(workspace, capsys):
    code, out, _ = run(capsys, str(workspace), "--color", "never")
    assert code == 0
    assert "node_modules" in out
    assert "__pycache__" in out
    assert "Dry run" in out
    assert (workspace / "web" / "node_modules").is_dir()


def test_report_mentions_the_reclaimable_total(workspace, capsys):
    _, out, _ = run(capsys, str(workspace), "--color", "never")
    assert "reclaimable" in out
    assert "safe" in out


def test_top_limits_rows(workspace, capsys):
    _, all_out, _ = run(capsys, str(workspace), "--color", "never", "--top", "0")
    _, one_out, _ = run(capsys, str(workspace), "--color", "never", "--top", "1")
    assert all_out.count("node_modules") >= 1
    assert "of 3 directories" in one_out


def test_include_review(workspace, capsys):
    _, out, _ = run(capsys, str(workspace), "--color", "never", "--include-review")
    assert "review" in out
    assert "build" in out


def test_min_size_filter(workspace, capsys):
    _, out, _ = run(capsys, str(workspace), "--color", "never", "--min-size", "5KB")
    assert "node_modules" in out  # 6 KiB, still above the threshold
    assert ".next" not in out  # 1 KiB, filtered out
    assert "__pycache__" not in out


def test_kinds_filter(workspace, capsys):
    _, out, _ = run(capsys, str(workspace), "--color", "never", "--kinds", "python")
    assert "__pycache__" in out
    assert "node_modules" not in out


def test_kinds_rejects_unknown_ecosystem(capsys):
    with pytest.raises(SystemExit) as excinfo:
        main([".", "--kinds", "cobol", "--color", "never"])
    assert excinfo.value.code == 2


def test_json_output(workspace, capsys):
    code, out, _ = run(capsys, str(workspace), "--json")
    assert code == 0
    payload = json.loads(out)
    assert payload["tool"] == "devdust"
    assert payload["version"] == __version__
    assert payload["totals"]["directories"] == len(payload["items"]) == 3
    first = payload["items"][0]
    assert {"path", "size", "files", "kind", "confidence", "age_seconds"} <= set(first)
    assert payload["items"] == sorted(payload["items"], key=lambda i: -i["size"])


def test_json_totals_match_items(workspace, capsys):
    _, out, _ = run(capsys, str(workspace), "--json")
    payload = json.loads(out)
    assert payload["totals"]["size"] == sum(i["size"] for i in payload["items"])
    assert payload["totals"]["files"] == sum(i["files"] for i in payload["items"])


def test_delete_with_yes(workspace, capsys):
    code, out, err = run(capsys, str(workspace), "--delete", "--yes", "--color", "never")
    assert code == 0
    assert "freed" in out
    assert not (workspace / "web" / "node_modules").exists()
    assert (workspace / "web" / "src" / "main.ts").is_file()
    assert err == ""


def test_delete_refuses_without_a_tty(workspace, capsys, monkeypatch):
    no_tty(monkeypatch)
    code, _, err = run(capsys, str(workspace), "--delete", "--color", "never")
    assert code == 1
    assert "--yes" in err
    assert (workspace / "web" / "node_modules").is_dir()


def test_delete_prompts_and_aborts_on_no(workspace, capsys, monkeypatch):
    monkeypatch.setattr(sys, "stdin", _FakeTty("n\n"))
    code, out, _ = run(capsys, str(workspace), "--delete", "--color", "never")
    assert code == 0
    assert "aborted" in out
    assert (workspace / "web" / "node_modules").is_dir()


def test_delete_prompts_and_proceeds_on_yes(workspace, capsys, monkeypatch):
    monkeypatch.setattr(sys, "stdin", _FakeTty("yes\n"))
    code, out, _ = run(capsys, str(workspace), "--delete", "--color", "never")
    assert code == 0
    assert "removed" in out
    assert not (workspace / "web" / "node_modules").exists()


def test_delete_with_json_reports_removals(workspace, capsys):
    code, out, _ = run(capsys, str(workspace), "--delete", "--yes", "--json")
    assert code == 0
    payload = json.loads(out)
    assert payload["removed"]["directories"] == 3
    assert payload["removed"]["failures"] == []
    assert payload["removed"]["freed"] > 0


def test_only_shown_entries_are_deleted(workspace, capsys):
    code, out, _ = run(
        capsys, str(workspace), "--delete", "--yes", "--top", "1", "--color", "never"
    )
    assert code == 0
    candidates = [
        workspace / "web" / "node_modules",
        workspace / "web" / ".next",
        workspace / "api" / "__pycache__",
    ]
    remaining = [path for path in candidates if path.exists()]
    assert len(remaining) == 2  # only the single biggest match was removed
    assert "only the 1 entries shown were removed" in out


def test_nothing_to_clean_up(tmp_path, capsys):
    (tmp_path / "src").mkdir()
    code, out, _ = run(capsys, str(tmp_path), "--color", "never")
    assert code == 0
    assert "nothing to clean up" in out


def test_missing_path_is_an_error(capsys):
    code, _, err = run(capsys, "/definitely/not/a/directory", "--color", "never")
    assert code == 1
    assert "error" in err


def test_older_than_and_exclude_flags(workspace, capsys):
    _, out, _ = run(capsys, str(workspace), "--color", "never", "--exclude", "node_modules")
    assert "web-app" not in out
    assert "__pycache__" in out


def test_rules_subcommand_lists_the_table(capsys):
    code, out, _ = run(capsys, "rules", "--color", "never")
    assert code == 0
    assert "node_modules" in out and "__pycache__" in out
    assert "safe" in out and "review" in out


def test_version_flag(capsys):
    with pytest.raises(SystemExit) as excinfo:
        main(["--version"])
    assert excinfo.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_sort_by_age(workspace, capsys):
    _, out, _ = run(capsys, str(workspace), "--json", "--sort", "age")
    ages = [item["age_seconds"] for item in json.loads(out)["items"]]
    assert ages == sorted(ages, reverse=True)


def test_pyproject_and_package_versions_agree():
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    match = re.search(r'^version = "([^"]+)"', pyproject.read_text(encoding="utf-8"), re.M)
    assert match is not None
    assert match.group(1) == __version__


class _FakeTty(io.StringIO):
    """A stdin that pretends to be an interactive terminal."""

    def isatty(self) -> bool:
        return True
