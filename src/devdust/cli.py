"""The ``devdust`` command line interface."""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from . import __version__
from . import rules as rules_mod
from .formatting import (
    Style,
    ellipsize,
    human_age,
    human_count,
    human_size,
    parse_duration,
    parse_size,
    render_styled_table,
    shorten_home,
    supports_color,
    terminal_width,
)
from .scanner import Match, ScanError, ScanResult, remove, scan

PROG = "devdust"

EPILOG = """\
examples:
  devdust                          dry run over the current directory
  devdust ~/work ~/side-projects   scan several roots
  devdust --older-than 90d         only caches untouched for 3 months
  devdust --min-size 100MB --top 0 report everything worth seeing
  devdust --kinds node,python      stay inside one ecosystem
  devdust --delete                 remove the safe matches (asks first)

exit codes:
  0  nothing to do / everything went fine
  1  a directory could not be removed, or the scan itself failed
  2  invalid usage
"""


# ----------------------------------------------------------------- api types


def _kind_list(value: str) -> Sequence[str]:
    known = set(rules_mod.kinds())
    chosen = [part.strip().lower() for part in value.split(",") if part.strip()]
    unknown = [part for part in chosen if part not in known]
    if unknown:
        raise argparse.ArgumentTypeError(
            f"unknown kind(s): {', '.join(unknown)} (choose from: {', '.join(sorted(known))})"
        )
    return chosen


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROG,
        description=(
            "Find the build artifacts and caches your projects leave behind, "
            "and remove them when you are ready."
        ),
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "paths",
        nargs="*",
        metavar="PATH",
        help="directories to scan (default: the current directory)",
    )
    parser.add_argument(
        "--delete",
        action="store_true",
        help="actually remove the directories shown (dry run by default)",
    )
    parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="do not ask for confirmation when deleting",
    )
    parser.add_argument(
        "--include-review",
        action="store_true",
        help="also consider ambiguous names such as build/, bin/, target/",
    )
    parser.add_argument(
        "--kinds",
        type=_kind_list,
        metavar="LIST",
        help="restrict to ecosystems, e.g. python,node (see 'devdust rules')",
    )
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        metavar="GLOB",
        help="skip directories matching this glob (repeatable)",
    )
    parser.add_argument(
        "--min-size",
        type=parse_size,
        default=0,
        metavar="SIZE",
        help="ignore matches smaller than SIZE, e.g. 50MB",
    )
    parser.add_argument(
        "--older-than",
        type=parse_duration,
        default=None,
        metavar="AGE",
        help="only matches untouched for AGE, e.g. 30d, 12h, 2w",
    )
    parser.add_argument(
        "--max-depth",
        type=int,
        default=None,
        metavar="N",
        help="do not descend deeper than N levels below each root",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=25,
        metavar="N",
        help="show at most N entries; 0 shows everything (default: 25)",
    )
    parser.add_argument(
        "--sort",
        choices=("size", "age", "path", "kind"),
        default="size",
        help="entry order (default: size, biggest first)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="print machine readable JSON instead of a table",
    )
    parser.add_argument(
        "--color",
        choices=("auto", "always", "never"),
        default="auto",
        help="colourise output (default: auto)",
    )
    parser.add_argument("--version", action="version", version=f"{PROG} {__version__}")
    return parser


# ------------------------------------------------------------------- helpers


def _use_color(choice: str) -> bool:
    if choice == "always":
        return True
    if choice == "never":
        return False
    return supports_color(sys.stdout)


def _sort_matches(matches: list[Match], order: str) -> list[Match]:
    if order == "size":
        return sorted(matches, key=lambda m: (-m.size, str(m.path)))
    if order == "age":
        return sorted(matches, key=lambda m: (-m.age_seconds, str(m.path)))
    if order == "kind":
        return sorted(matches, key=lambda m: (m.kind, -m.size, str(m.path)))
    return sorted(matches, key=lambda m: str(m.path))


def _display_path(path: Path, budget: int) -> str:
    return ellipsize(shorten_home(str(path)), budget)


def _summary_counts(matches: Sequence[Match]) -> dict[str, Any]:
    by_conf: dict[str, int] = {}
    by_kind: dict[str, int] = {}
    for match in matches:
        by_conf[match.confidence] = by_conf.get(match.confidence, 0) + match.size
        by_kind[match.kind] = by_kind.get(match.kind, 0) + match.size
    return {"confidence": by_conf, "kind": by_kind}


def _as_json(
    result: ScanResult,
    matches: Sequence[Match],
    *,
    elapsed: float,
    removal=None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "tool": PROG,
        "version": __version__,
        "roots": [str(root) for root in result.roots],
        "scanned_dirs": result.scanned_dirs,
        "unreadable": result.unreadable,
        "elapsed_seconds": round(elapsed, 3),
        "totals": {
            "size": sum(m.size for m in matches),
            "size_human": human_size(sum(m.size for m in matches)),
            "files": sum(m.files for m in matches),
            "directories": len(matches),
        },
        "items": [
            {
                "path": str(m.path),
                "size": m.size,
                "size_human": human_size(m.size),
                "files": m.files,
                "age_seconds": round(m.age_seconds, 3),
                "age_human": human_age(m.age_seconds),
                "kind": m.kind,
                "confidence": m.confidence,
                "rule": m.rule.pattern,
            }
            for m in matches
        ],
    }
    if removal is not None:
        payload["removed"] = {
            "freed": removal.freed,
            "freed_human": human_size(removal.freed),
            "directories": removal.removed,
            "failures": [
                {"path": str(item.match.path), "error": item.error} for item in removal.failures
            ],
        }
    return payload


# --------------------------------------------------------------------- scan


def _cmd_scan(args: argparse.Namespace) -> int:
    style = Style(enabled=_use_color(args.color))
    selected = rules_mod.select(kinds_in=args.kinds, include_review=args.include_review)
    if not selected:
        print(f"{PROG}: no rules enabled by --kinds/--include-review", file=sys.stderr)
        return 2

    roots = args.paths or ["."]
    started = time.perf_counter()
    try:
        result = scan(
            roots,
            rules=selected,
            excludes=args.exclude,
            min_size=args.min_size,
            older_than=args.older_than,
            max_depth=args.max_depth,
        )
    except ScanError as exc:
        print(f"{PROG}: error: {exc}", file=sys.stderr)
        return 1
    elapsed = time.perf_counter() - started

    matches = _sort_matches(result.matches, args.sort)
    shown = matches if args.top <= 0 else matches[: args.top]

    if args.as_json:
        return _print_json(result, matches, elapsed, args)

    _print_header(style, result, len(roots), elapsed)
    if not shown:
        _print_empty(style, args)
        return 0
    _print_table(style, shown, args)

    totals = _summary_counts(shown)
    header_note = (
        f"{len(shown)} of {len(matches)} directories"
        if len(shown) != len(matches)
        else f"{len(matches)} director{'y' if len(matches) == 1 else 'ies'}"
    )
    line = f"{header_note} · {style.bold(human_size(sum(m.size for m in shown)))} reclaimable"
    print(f"\n  {line}")
    parts = []
    for confidence in ("safe", "review"):
        if confidence in totals["confidence"]:
            size = totals["confidence"][confidence]
            count = sum(1 for m in shown if m.confidence == confidence)
            label = style.green(confidence) if confidence == "safe" else style.yellow(confidence)
            parts.append(f"{label} {human_size(size)} ({count})")
    if parts:
        print("  " + "   ".join(parts))
    if result.unreadable:
        print(
            "  "
            + style.yellow(f"! {result.unreadable} directories could not be read (permissions)")
        )

    if args.delete:
        return _do_delete(style, result, shown, len(matches), args)

    print("\n  " + style.dim("Dry run — nothing deleted. Re-run with --delete to remove these."))
    return 0


def _print_header(style: Style, result: ScanResult, root_count: int, elapsed: float) -> None:
    title = style.bold(f"{PROG} {__version__}")
    where = f"{root_count} root{'s' if root_count != 1 else ''}"
    dirs = human_count(result.scanned_dirs) + " dirs scanned"
    print(f"{title} · {style.dim(where)} · {style.dim(dirs)} · {style.dim(f'{elapsed:.2f}s')}")


def _print_empty(style: Style, args: argparse.Namespace) -> None:
    hint = "nothing to clean up here"
    if args.min_size or args.older_than or args.kinds or args.exclude:
        hint += " with the current filters"
    elif not args.include_review:
        hint += " — try --include-review for build/, bin/, target/ …"
    print("\n  " + style.green("✓ " + hint))


def _print_table(style: Style, shown: Sequence[Match], args: argparse.Namespace) -> None:
    widths = terminal_width()
    budget = max(24, widths - 46)
    headers = ["SIZE", "FILES", "AGE", "KIND", "CONF", "PATH"]
    rows = [
        [
            human_size(m.size),
            human_count(m.files),
            human_age(m.age_seconds),
            m.kind,
            m.confidence,
            _display_path(m.path, budget),
        ]
        for m in shown
    ]
    align = ["right", "right", "right", "left", "left", "left"]

    def styler(column: int, _row: int, cell: str) -> str:
        if column == 0:
            return style.paint(cell, "bold")
        if column == 3:
            return style.paint(cell, "cyan")
        if column == 4:
            return style.paint(cell, "green" if cell.strip() == "safe" else "yellow")
        if column in (1, 2):
            return style.dim(cell)
        return cell

    table = render_styled_table(
        headers,
        rows,
        align=align,
        styler=styler,
        header_styler=lambda _col, cell: style.dim(cell),
    )
    print()
    print(table)


def _print_json(result: ScanResult, matches: Sequence[Match], elapsed: float, args) -> int:
    removal = None
    if args.delete and matches:
        removal = remove(matches, roots=result.roots, dry_run=False)
    payload = _as_json(result, matches, elapsed=elapsed, removal=removal)
    json.dump(payload, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")
    if removal is not None and removal.failures:
        for failure in removal.failures:
            print(
                f"{PROG}: could not remove {failure.match.path}: {failure.error}", file=sys.stderr
            )
        return 1
    return 0


def _do_delete(
    style: Style,
    result: ScanResult,
    shown: Sequence[Match],
    total: int,
    args: argparse.Namespace,
) -> int:
    targets = list(shown)
    size = sum(m.size for m in targets)
    label = f"{len(targets)} director{'ies' if len(targets) != 1 else 'y'} ({human_size(size)})"

    if not args.yes:
        if not sys.stdin.isatty():
            print(
                f"\n  {style.yellow('refusing to delete without confirmation')}: "
                "re-run with --yes for non-interactive use.",
                file=sys.stderr,
            )
            return 1
        sys.stdout.write(f"\n  Delete {label}? [y/N] ")
        sys.stdout.flush()
        answer = sys.stdin.readline().strip().lower()
        if answer not in ("y", "yes"):
            print("  " + style.dim("aborted, nothing deleted."))
            return 0

    removal = remove(targets, roots=result.roots, dry_run=False)
    for failure in removal.failures:
        print(
            f"  {style.yellow('!')} {failure.match.path}: {failure.error}",
            file=sys.stderr,
        )
    freed = human_size(removal.freed)
    summary = f"removed {removal.removed} of {len(targets)} directories · freed {freed}"
    print("\n  " + (style.green("✓ " + summary) if not removal.failures else style.bold(summary)))
    if len(shown) != total:
        print(
            "  "
            + style.dim(
                f"only the {len(shown)} entries shown were removed; use --top 0 to cover the rest."
            )
        )
    return 0 if not removal.failures else 1


# -------------------------------------------------------------------- rules


def _cmd_rules(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(
        prog=f"{PROG} rules",
        description="List every directory pattern devdust knows about.",
    )
    parser.add_argument("--color", choices=("auto", "always", "never"), default="auto")
    args = parser.parse_args(list(argv))
    style = Style(enabled=_use_color(args.color))

    rows = [
        [
            rule.pattern,
            rule.kind,
            rule.confidence,
            rule.description,
        ]
        for rule in rules_mod.RULES
    ]

    def styler(column: int, _row: int, cell: str) -> str:
        if column == 0:
            return style.paint(cell, "bold")
        if column == 1:
            return style.paint(cell, "cyan")
        if column == 2:
            return style.paint(cell, "green" if cell.strip() == "safe" else "yellow")
        return style.dim(cell)

    print(
        render_styled_table(
            ["PATTERN", "KIND", "CONF", "WHAT IT IS"],
            rows,
            styler=styler,
            header_styler=lambda _c, cell: style.dim(cell),
        )
    )
    safe = sum(1 for r in rules_mod.RULES if r.confidence == rules_mod.SAFE)
    review = len(rules_mod.RULES) - safe
    print(
        "\n  "
        + style.dim(
            f"{len(rules_mod.RULES)} rules · {safe} safe (deleted by default) · "
            f"{review} review (opt in with --include-review)"
        )
    )
    return 0


# --------------------------------------------------------------------- main


def main(argv: Sequence[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "rules":
        return _cmd_rules(argv[1:])
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return _cmd_scan(args)
    except KeyboardInterrupt:  # pragma: no cover - interactive only
        print("\naborted", file=sys.stderr)
        return 130


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
