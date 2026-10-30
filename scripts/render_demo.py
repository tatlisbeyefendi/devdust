#!/usr/bin/env python3
"""Rebuild the documentation screenshots from the real CLI's output.

    python scripts/render_demo.py

Creates a throw-away workspace in the temp directory, runs ``devdust`` against
it and renders the output into ``docs/demo.svg``, ``docs/demo-delete.svg`` and
``docs/demo-undo.svg``.
Nothing is hard-coded, so the images cannot drift away from the tool.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PYTHON = sys.executable


def run(command: list[str], env: dict[str, str]) -> None:
    subprocess.run(command, check=True, env=env)


def main() -> int:
    home = Path(tempfile.gettempdir()) / "devdust-demo-home"
    env = dict(
        os.environ,
        PYTHONPATH=str(REPO / "src"),
        COLUMNS="100",
        HOME=str(home),
    )
    render = [PYTHON, str(REPO / "scripts" / "render_demo_svg.py")]
    devdust = [PYTHON, "-m", "devdust", str(home)]

    run([PYTHON, str(REPO / "scripts" / "make_demo_tree.py"), str(home), "--force"], env)

    run(
        [
            *render,
            str(REPO / "docs" / "demo.svg"),
            "--title",
            "devdust — dry run",
            "--prompt",
            "devdust ~ --include-review --summary",
            "--",
            *devdust,
            "--include-review",
            "--summary",
            "--top",
            "6",
        ],
        env,
    )
    run(
        [
            *render,
            str(REPO / "docs" / "demo-delete.svg"),
            "--title",
            "devdust --delete --yes",
            "--prompt",
            "devdust ~ --delete --yes",
            "--",
            *devdust,
            "--delete",
            "--yes",
            "--top",
            "5",
        ],
        env,
    )
    run(
        [
            *render,
            str(REPO / "docs" / "demo-undo.svg"),
            "--title",
            "devdust undo — put it back",
            "--prompt",
            "devdust undo",
            "--",
            *[PYTHON, "-m", "devdust", "undo"],
        ],
        env,
    )
    print("demo images regenerated in docs/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
