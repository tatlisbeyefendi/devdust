"""Tests for `.devdust.toml` discovery, parsing and validation."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from devdust import config as config_mod
from devdust.config import Config, ConfigError, discover, load, template


def write(directory: Path, text: str, name: str = config_mod.CONFIG_FILENAME) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(text, encoding="utf-8")
    return path


# ----------------------------------------------------------------- discovery


def test_discover_walks_up_from_a_subdirectory(tmp_path):
    found = write(tmp_path, "[devdust]\ntop = 5\n")
    nested = tmp_path / "a" / "b" / "c"
    nested.mkdir(parents=True)
    assert discover(nested) == found


def test_discover_returns_none_without_a_file(tmp_path):
    assert discover(tmp_path) is None


def test_discover_prefers_the_closest_file(tmp_path):
    write(tmp_path, "[devdust]\ntop = 1\n")
    inner = write(tmp_path / "inner", "[devdust]\ntop = 2\n")
    assert discover(tmp_path / "inner" / "src") == inner


def test_discover_stops_at_home(tmp_path):
    home = tmp_path / "home"
    top_level = write(tmp_path, "[devdust]\ntop = 9\n")  # above $HOME, never read
    project = home / "project"
    project.mkdir(parents=True)
    assert discover(project, home=home) is None
    assert top_level.is_file()


def test_discover_uses_the_xdg_config_dir(tmp_path, monkeypatch):
    xdg = tmp_path / "xdg"
    fallback = write(xdg / "devdust", "[devdust]\ntop = 3\n", name="config.toml")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))
    project = tmp_path / "project"
    project.mkdir()
    assert discover(project, home=tmp_path / "home") == fallback


# ------------------------------------------------------------------- loading


def test_load_parses_every_key(tmp_path):
    path = write(
        tmp_path,
        """
[devdust]
paths = ["~/code", "~/oss"]
exclude = [".git", "*-backup"]
kinds = ["node", "python"]
min_size = "20MB"
older_than = "30d"
include_review = true
top = 10
sort = "age"
color = "never"
summary = true
""",
    )
    config = load(path)
    assert config.source == path
    assert config.paths == ("~/code", "~/oss")
    assert config.exclude == (".git", "*-backup")
    assert config.kinds == ("node", "python")
    assert config.min_size == 20 * 1024**2
    assert config.older_than == timedelta(days=30)
    assert config.include_review is True
    assert config.top == 10
    assert config.sort == "age"
    assert config.color == "never"
    assert config.summary is True


def test_min_size_accepts_a_byte_count(tmp_path):
    assert load(write(tmp_path, "[devdust]\nmin_size = 4096\n")).min_size == 4096


def test_missing_table_means_no_settings(tmp_path):
    config = load(write(tmp_path, "# just a comment\n"))
    assert config.provided == frozenset()
    assert config.as_defaults() == {}


def test_as_defaults_only_contains_provided_keys(tmp_path):
    config = load(write(tmp_path, '[devdust]\nmin_size = "5MB"\nsummary = true\n'))
    defaults = config.as_defaults()
    assert set(defaults) == {"min_size", "summary"}
    assert defaults["min_size"] == 5 * 1024**2


def test_empty_config_is_the_default(tmp_path):
    assert load(write(tmp_path, "[devdust]\n")) == Config(
        source=tmp_path / config_mod.CONFIG_FILENAME
    )


# ------------------------------------------------------------------- errors


def test_invalid_toml(tmp_path):
    with pytest.raises(ConfigError, match="invalid TOML"):
        load(write(tmp_path, "[devdust\nmin_size = "))


def test_missing_file(tmp_path):
    with pytest.raises(ConfigError, match="cannot read"):
        load(tmp_path / "nope.toml")


def test_unknown_key_suggests_the_closest_match(tmp_path):
    with pytest.raises(ConfigError) as excinfo:
        load(write(tmp_path, '[devdust]\nmin_sizes = "5MB"\n'))
    message = str(excinfo.value)
    assert "min_sizes" in message
    assert "did you mean 'min_size'?" in message


def test_destructive_flags_are_rejected(tmp_path):
    for key in ("delete", "yes"):
        with pytest.raises(ConfigError, match="unknown key"):
            load(write(tmp_path, f"[devdust]\n{key} = true\n"))


@pytest.mark.parametrize(
    "body, needle",
    [
        ('kinds = ["node", "cobol"]', "unknown kinds"),
        ('sort = "biggest"', "must be one of"),
        ('color = "purple"', "must be one of"),
        ('include_review = "yes"', "must be true or false"),
        ("top = -1", "cannot be negative"),
        ('top = "five"', "whole number"),
        ('older_than = "soon"', "older_than"),
        ("older_than = 30", "duration string"),
        ('min_size = "10XB"', "min_size"),
        ("min_size = true", "size string"),
        ("paths = 3", "array of strings"),
        ("exclude = [1, 2]", "array of strings"),
    ],
)
def test_invalid_values_are_explained(tmp_path, body, needle):
    with pytest.raises(ConfigError, match=needle):
        load(write(tmp_path, f"[devdust]\n{body}\n"))


def test_table_must_be_a_table(tmp_path):
    with pytest.raises(ConfigError, match="must be a table"):
        load(write(tmp_path, "devdust = 5\n"))


# ----------------------------------------------------------------- template


def test_template_is_valid_and_changes_nothing(tmp_path):
    path = write(tmp_path, template())
    config = load(path)
    assert config.provided == frozenset()
    assert config.as_defaults() == {}
    assert config == Config(source=path)


def test_template_mentions_the_safety_caveat():
    text = template()
    assert "--delete" in text
    assert "*not* configurable" in text
