"""Shared fixtures: small, believable project trees built in ``tmp_path``."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest


def touch(path: Path, size: int = 1024, age_days: float = 0.0) -> Path:
    """Create a file of ``size`` bytes, optionally backdated by ``age_days``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    if age_days:
        stamp = time.time() - age_days * 86400
        os.utime(path, (stamp, stamp))
    return path


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """A three-project workspace with safe matches, review matches and a .git."""
    root = tmp_path / "workspace"
    # javascript project: node_modules (2 KiB) with a nested cache inside it
    touch(root / "web" / "node_modules" / "react" / "index.js", 2048)
    touch(root / "web" / "node_modules" / ".cache" / "prettier.json", 4096)
    touch(root / "web" / "src" / "main.ts", 512)
    touch(root / "web" / ".next" / "chunk.js", 1024)
    # python project: __pycache__ + build/ (review confidence)
    touch(root / "api" / "__pycache__" / "core.pyc", 300, age_days=40)
    touch(root / "api" / "build" / "lib.py", 700)
    touch(root / "api" / "src" / "app.py", 256)
    # something inside .git that must never be reported
    touch(root / ".git" / "node_modules" / "hook.js", 99999)
    return root


@pytest.fixture
def huge_dir(tmp_path: Path) -> Path:
    """A directory well outside the scanned root, reachable via symlink."""
    path = tmp_path / "outside" / "node_modules"
    touch(path / "big.js", 50_000)
    return path
