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
from devdust.config import template


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
    """--hard is the old behaviour: gone for good, nothing in the stash."""
    code, out, err = run(capsys, str(workspace), "--delete", "--hard", "--yes", "--color", "never")
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
    code, out, _ = run(capsys, str(workspace), "--delete", "--hard", "--color", "never")
    assert code == 0
    assert "removed" in out
    assert not (workspace / "web" / "node_modules").exists()


def test_delete_with_json_reports_removals(workspace, capsys):
    code, out, _ = run(capsys, str(workspace), "--delete", "--hard", "--yes", "--json")
    assert code == 0
    payload = json.loads(out)
    assert payload["removed"]["directories"] == 3
    assert payload["removed"]["failures"] == []
    assert payload["removed"]["freed"] > 0


def test_only_shown_entries_are_deleted(workspace, capsys):
    code, out, _ = run(
        capsys, str(workspace), "--delete", "--hard", "--yes", "--top", "1", "--color", "never"
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


# ------------------------------------------------------------------ config file


def write_config(directory, body: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / ".devdust.toml"
    path.write_text(body, encoding="utf-8")
    return path


def test_config_file_supplies_defaults(workspace, tmp_path, capsys):
    config = write_config(tmp_path / "cfg", '[devdust]\nmin_size = "5KB"\n')
    code, out, _ = run(capsys, str(workspace), "--config", str(config), "--color", "never")
    assert code == 0
    assert "node_modules" in out
    assert ".next" not in out  # 1 KiB, filtered out by the config
    assert ".devdust.toml" in out  # and the header says where the settings came from


def test_cli_flags_beat_the_config_file(workspace, tmp_path, capsys):
    config = write_config(tmp_path / "cfg", '[devdust]\nmin_size = "100KB"\n')
    _, out, _ = run(
        capsys,
        str(workspace),
        "--config",
        str(config),
        "--min-size",
        "0",
        "--color",
        "never",
    )
    assert ".next" in out


def test_no_config_ignores_the_file(workspace, tmp_path, monkeypatch, capsys):
    write_config(tmp_path, '[devdust]\nmin_size = "100KB"\n')
    monkeypatch.chdir(tmp_path)
    _, out, _ = run(capsys, str(workspace), "--no-config", "--color", "never")
    assert ".next" in out  # the config in the working directory was ignored


def test_config_can_supply_the_roots(tmp_path, workspace, capsys):
    config = write_config(tmp_path / "cfg", f'[devdust]\npaths = ["{workspace}"]\n')
    code, out, _ = run(capsys, "--config", str(config), "--color", "never")
    assert code == 0
    assert "node_modules" in out


def test_config_can_enable_review_directories(workspace, tmp_path, capsys):
    config = write_config(tmp_path / "cfg", "[devdust]\ninclude_review = true\n")
    _, out, _ = run(capsys, str(workspace), "--config", str(config), "--color", "never")
    assert "review" in out and "build" in out


def test_config_is_discovered_without_a_flag(tmp_path, workspace, monkeypatch, capsys):
    write_config(tmp_path, f'[devdust]\npaths = ["{workspace}"]\n')
    monkeypatch.chdir(tmp_path)
    code, out, _ = run(capsys, "--color", "never")
    assert code == 0
    assert "node_modules" in out


def test_broken_config_is_a_usage_error(workspace, tmp_path, capsys):
    config = write_config(tmp_path / "cfg", "[devdust]\nmin_size = \n")
    code, _, err = run(capsys, str(workspace), "--config", str(config), "--color", "never")
    assert code == 2
    assert "config" in err


def test_unknown_config_key_is_reported(workspace, tmp_path, capsys):
    config = write_config(tmp_path / "cfg", "[devdust]\ndelete = true\n")
    code, _, err = run(capsys, str(workspace), "--config", str(config), "--color", "never")
    assert code == 2
    assert "delete" in err


def test_missing_config_file_is_reported(workspace, tmp_path, capsys):
    code, _, err = run(
        capsys, str(workspace), "--config", str(tmp_path / "nope.toml"), "--color", "never"
    )
    assert code == 2
    assert "no such config file" in err


def test_config_and_no_config_conflict(workspace, tmp_path, capsys):
    config = write_config(tmp_path / "cfg", "[devdust]\ntop = 1\n")
    code, _, err = run(
        capsys, str(workspace), "--config", str(config), "--no-config", "--color", "never"
    )
    assert code == 2
    assert "cannot be combined" in err


# ------------------------------------------------------------------ devdust init


def test_init_writes_a_starter_file(tmp_path, capsys):
    code, out, _ = run(capsys, "init", str(tmp_path))
    assert code == 0
    written = tmp_path / ".devdust.toml"
    assert written.is_file()
    assert "[devdust]" in written.read_text(encoding="utf-8")
    assert str(written) in out


def test_init_output_runs_without_changing_behaviour(tmp_path, workspace, capsys):
    run(capsys, "init", str(tmp_path))
    code, out, _ = run(
        capsys,
        str(workspace),
        "--config",
        str(tmp_path / ".devdust.toml"),
        "--color",
        "never",
    )
    assert code == 0
    assert "node_modules" in out and ".next" in out


def test_init_refuses_to_overwrite(tmp_path, capsys):
    existing = tmp_path / ".devdust.toml"
    existing.write_text("[devdust]\ntop = 2\n", encoding="utf-8")
    code, _, err = run(capsys, "init", str(tmp_path))
    assert code == 1
    assert "already exists" in err
    assert "top = 2" in existing.read_text(encoding="utf-8")

    code, _, _ = run(capsys, "init", str(tmp_path), "--force")
    assert code == 0
    assert existing.read_text(encoding="utf-8") == template()


# --------------------------------------------------------------------- summary


def test_summary_breakdown(workspace, capsys):
    code, out, _ = run(capsys, str(workspace), "--summary", "--color", "never")
    assert code == 0
    assert "where the space goes" in out
    assert "node" in out and "python" in out
    assert "%" in out


def test_summary_is_off_by_default(workspace, capsys):
    _, out, _ = run(capsys, str(workspace), "--color", "never")
    assert "where the space goes" not in out


def test_json_contains_summary_and_config(workspace, tmp_path, capsys):
    config = write_config(tmp_path / "cfg", "[devdust]\ntop = 1\n")
    _, out, _ = run(capsys, str(workspace), "--config", str(config), "--json")
    payload = json.loads(out)
    assert payload["config"].endswith(".devdust.toml")
    assert payload["summary"]["by_kind"]["node"]["size"] == 2048 + 4096 + 1024
    assert set(payload["summary"]["by_confidence"]) == {"safe"}
