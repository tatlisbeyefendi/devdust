#!/usr/bin/env python3
"""Build a fake multi-project workspace, so demos and screenshots are honest.

Every directory it creates looks like the leftovers a real project leaves
behind; the files are sparse, so a "1.2 GB node_modules" costs almost no disk
space while still reporting a realistic size.

    python scripts/make_demo_tree.py /tmp/devdust-demo
"""

from __future__ import annotations

import argparse
import contextlib
import os
import random
from pathlib import Path

# (relative directory, file name pattern, how many files, size range in bytes)
LAYOUT = {
    "work/web-app": [
        ("node_modules/react/cjs", "bundle-{i}.js", 12, (200_000, 3_000_000)),
        ("node_modules/@types/node", "lib-{i}.d.ts", 20, (5_000, 120_000)),
        ("node_modules/esbuild/bin", "esbuild-{i}", 3, (9_000_000, 26_000_000)),
        ("node_modules/.cache/prettier", "chunk-{i}.json", 8, (10_000, 400_000)),
        (".next/static/chunks", "chunk-{i}.js", 40, (30_000, 900_000)),
        (".next/cache/webpack", "pack-{i}.pack", 6, (2_000_000, 14_000_000)),
    ],
    "work/api": [
        (".venv/lib/python3.11/site-packages/django", "mod_{i}.py", 60, (2_000, 60_000)),
        ("__pycache__", "core.cpython-311-{i}.pyc", 14, (1_000, 40_000)),
        (".pytest_cache/v/cache", "nodeids-{i}", 3, (2_000, 90_000)),
        (".mypy_cache/3.11", "meta-{i}.json", 25, (500, 12_000)),
        (".ruff_cache/0.6", "entry-{i}", 10, (400, 9_000)),
    ],
    "work/design-tokens": [
        ("dist", "tokens-{i}.css", 5, (4_000, 40_000)),
        ("node_modules/tinycolor2", "index-{i}.js", 4, (3_000, 18_000)),
    ],
    "oss/engine": [
        ("target/debug/deps", "libengine-{i}.rlib", 22, (400_000, 5_000_000)),
        ("target/debug/incremental", "s-{i}.o", 30, (40_000, 700_000)),
    ],
    "oss/site": [
        ("node_modules/astro/dist", "mod-{i}.mjs", 18, (20_000, 700_000)),
        ("node_modules/sharp/build", "obj-{i}.o", 9, (100_000, 1_400_000)),
    ],
    "archive/legacy-crm": [
        ("build/classes", "App{i}.class", 35, (2_000, 90_000)),
        ("out/production", "res-{i}.jar", 3, (900_000, 6_000_000)),
    ],
}

#: Age of each group in days: the archive is genuinely old, the rest is fresh.
FRESHNESS = {
    "archive/legacy-crm": 214,
    "work/design-tokens": 96,
    "oss/engine": 31,
}


def build(target: Path, seed: int = 7) -> Path:
    random.seed(seed)
    target = Path(target).expanduser()
    for project, groups in LAYOUT.items():
        base = target / project
        age_days = FRESHNESS.get(project, 2)
        touched = set()
        for rel, pattern, count, (low, high) in groups:
            directory = base / rel
            directory.mkdir(parents=True, exist_ok=True)
            for index in range(count):
                file_path = directory / pattern.format(i=index)
                size = random.randint(low, high)
                with open(file_path, "wb") as handle:
                    handle.truncate(size)
                touched.add(rel.split("/")[0])
        stamp = (Path(target) / "..").stat().st_mtime - age_days * 86400
        for top in touched:
            _stamp_tree(base / top, stamp)
    # A couple of source files so the workspace does not look like a junkyard.
    for project in LAYOUT:
        (target / project / "README.md").write_text(f"# {project}\n", encoding="utf-8")
        (target / project / "src").mkdir(parents=True, exist_ok=True)
        (target / project / "src" / "main.ts").write_text("export {}\n", encoding="utf-8")
    return target


def _stamp_tree(path: Path, stamp: float) -> None:
    for current, dirs, files in os.walk(path, topdown=False):
        for name in files:
            with contextlib.suppress(OSError):
                os.utime(Path(current) / name, (stamp, stamp))
        for name in dirs:
            with contextlib.suppress(OSError):
                os.utime(Path(current) / name, (stamp, stamp))
    with contextlib.suppress(OSError):
        os.utime(path, (stamp, stamp))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", nargs="?", default="/tmp/devdust-demo")
    parser.add_argument("--force", action="store_true", help="delete the target first")
    args = parser.parse_args()
    target = Path(args.target).expanduser()
    if target.exists() and args.force:
        import shutil

        shutil.rmtree(target)
    target.mkdir(parents=True, exist_ok=True)
    print(f"demo tree ready at {build(target)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
