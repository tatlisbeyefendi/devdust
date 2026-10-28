"""Tests for size/age formatting, colour handling and table rendering."""

from __future__ import annotations

import io
from datetime import timedelta

import pytest

from devdust.formatting import (
    Style,
    ellipsize,
    human_age,
    human_count,
    human_size,
    parse_duration,
    parse_size,
    render_styled_table,
    render_table,
    shorten_home,
    supports_color,
)


@pytest.mark.parametrize(
    "value, expected",
    [
        (0, "0 B"),
        (1, "1 B"),
        (1023, "1023 B"),
        (1024, "1 KB"),
        (1536, "1.5 KB"),
        (10 * 1024, "10 KB"),
        (1024**2, "1 MB"),
        (1024**3 * 1.42, "1.42 GB"),
        (1024**4 * 3, "3 TB"),
    ],
)
def test_human_size(value, expected):
    assert human_size(value) == expected


def test_human_size_rejects_negative():
    with pytest.raises(ValueError):
        human_size(-1)


@pytest.mark.parametrize(
    "text, expected",
    [
        ("512", 512),
        ("10KB", 10 * 1024),
        ("10kb", 10 * 1024),
        ("1.5 GB", int(1.5 * 1024**3)),
        ("2t", 2 * 1024**4),
    ],
)
def test_parse_size(text, expected):
    assert parse_size(text) == expected


@pytest.mark.parametrize("bad", ["", "abc", "10XB", "-5MB"])
def test_parse_size_errors(bad):
    with pytest.raises(ValueError):
        parse_size(bad)


@pytest.mark.parametrize(
    "text, expected",
    [
        ("30s", timedelta(seconds=30)),
        ("15m", timedelta(minutes=15)),
        ("12h", timedelta(hours=12)),
        ("7d", timedelta(days=7)),
        ("2w", timedelta(weeks=2)),
    ],
)
def test_parse_duration(text, expected):
    assert parse_duration(text) == expected


def test_parse_duration_errors():
    with pytest.raises(ValueError):
        parse_duration("soon")


@pytest.mark.parametrize(
    "seconds, expected",
    [
        (0, "0s"),
        (59, "59s"),
        (60, "1m"),
        (3600, "1h"),
        (86400 * 31, "31d"),
        (86400 * 800, "2y"),
        (None, "-"),
    ],
)
def test_human_age(seconds, expected):
    assert human_age(seconds) == expected


def test_human_count():
    assert human_count(999) == "999"
    assert human_count(1200) == "1.2k"
    assert human_count(2_400_000) == "2.4M"


def test_style_disabled_is_passthrough():
    style = Style(enabled=False)
    assert style.bold("x") == "x"
    assert style.paint("x", "bold", "green") == "x"


def test_style_enabled_wraps_in_ansi():
    style = Style(enabled=True)
    assert style.bold("x") == "\x1b[1mx\x1b[0m"
    assert style.paint("x", "bold", "green") == "\x1b[1;32mx\x1b[0m"
    assert style.paint("x", "nonsense") == "x"


def test_supports_color_respects_environment(monkeypatch):
    tty = io.StringIO()
    monkeypatch.delenv("FORCE_COLOR", raising=False)
    monkeypatch.delenv("NO_COLOR", raising=False)
    assert supports_color(tty) is False
    monkeypatch.setenv("NO_COLOR", "1")
    assert supports_color(tty) is False
    monkeypatch.setenv("FORCE_COLOR", "1")
    assert supports_color(tty) is True


def test_render_table_aligns_and_validates():
    text = render_table(["A", "B"], [["xx", "1"], ["y", "22"]], align=["left", "right"])
    lines = text.splitlines()
    assert lines[0].split() == ["A", "B"]
    assert all(line.endswith(("1", "2")) for line in lines[2:])
    with pytest.raises(ValueError):
        render_table(["A", "B"], [["only one"]])
    with pytest.raises(ValueError):
        render_table(["A"], [], align=["left", "right"])


def test_render_styled_table_pads_before_styling():
    def styler(_column, _row, cell):
        return f"<{cell}>"

    text = render_styled_table(["A", "B"], [["x", "1"]], align=["left", "right"], styler=styler)
    assert "<x>" in text and "<1>" in text  # padded first, then decorated


def test_shorten_home():
    assert shorten_home("/home/dev/work", home="/home/dev") == "~/work"
    assert shorten_home("/home/dev", home="/home/dev") == "~"
    assert shorten_home("/opt/thing", home="/home/dev") == "/opt/thing"
    assert shorten_home("/anything", home="/") == "/anything"


def test_ellipsize():
    assert ellipsize("short", 20) == "short"
    assert ellipsize("a/very/long/path/here", 10) == "…path/here"
    assert ellipsize("abcdef", 3) == "abc"
