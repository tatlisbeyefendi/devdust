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
from . import config as config_mod
from . import rules as rules_mod
from . import stash as stash_mod
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
from .scanner import Match, SafetyError, ScanError, ScanResult, remove, scan

PROG = "devdust"

#: How many stash records to keep after a --delete run.
STASH_KEEP = 8

EPILOG = """\
examples:
  devdust                          dry run over the current directory
  devdust ~/work ~/side-projects   scan several roots
  devdust --older-than 90d         only caches untouched for 3 months
  devdust --min-size 100MB --top 0 report everything worth seeing
  devdust --kinds node,python      stay inside one ecosystem
  devdust --summary                where is the space actually going?
  devdust --delete                 move the safe matches to the stash (asks first)
  devdust undo                     put the last stash back where it was
  devdust stash                    what is sitting in the stash right now
  devdust --delete --hard           delete for real, no undo (asks first)

  devdust init                     write a starter .devdust.toml
  devdust rules                    list every known directory pattern

Configuration:
  devdust reads .devdust.toml from the current directory or its parents (up to
  $HOME), then $XDG_CONFIG_HOME/devdust/config.toml. Command line flags always
  win. --delete/--yes can never be set from a config file.

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
        help="directories to scan (default: paths from the config, else '.')",
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
        "--hard",
        action="store_true",
        help="with --delete: remove for real instead of moving to the stash",
    )
    parser.add_argument(
        "--stash-dir",
        type=Path,
        default=None,
        metavar="PATH",
        help="where --delete parks directories (default: $DEVFDUST_STASH or "
        "~/.local/state/devdust/stash)",
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
        "--summary",
        action="store_true",
        help="add a 'where the space goes' breakdown by ecosystem",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        metavar="FILE",
        help="use this config file instead of searching for .devdust.toml",
    )
    parser.add_argument(
        "--no-config",
        action="store_true",
        help="ignore every config file and use the built-in defaults",
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
    config_source: Path | None = None,
) -> dict[str, Any]:
    counts = _summary_counts(matches)
    payload: dict[str, Any] = {
        "tool": PROG,
        "version": __version__,
        "config": str(config_source) if config_source else None,
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
        "summary": {
            "by_kind": {
                kind: {"size": size, "size_human": human_size(size)}
                for kind, size in sorted(counts["kind"].items(), key=lambda kv: -kv[1])
            },
            "by_confidence": {
                confidence: {"size": size, "size_human": human_size(size)}
                for confidence, size in counts["confidence"].items()
            },
        },
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

    roots = args.paths or list(getattr(args, "config_paths", ()) or ()) or ["."]
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

    _print_header(
        style, result, len(roots), elapsed, config_source=getattr(args, "config_source", None)
    )
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
    if getattr(args, "summary", False):
        _print_summary(style, shown)

    if args.delete:
        return _do_delete(style, result, shown, len(matches), args)

    print("\n  " + style.dim("Dry run — nothing deleted. Re-run with --delete to remove these."))
    return 0


def _print_header(
    style: Style,
    result: ScanResult,
    root_count: int,
    elapsed: float,
    *,
    config_source: Path | None = None,
) -> None:
    title = style.bold(f"{PROG} {__version__}")
    bits = [
        f"{root_count} root{'s' if root_count != 1 else ''}",
        human_count(result.scanned_dirs) + " dirs scanned",
        f"{elapsed:.2f}s",
    ]
    if config_source is not None:
        bits.append(_config_label(config_source))
    print(f"{title} · " + " · ".join(style.dim(bit) for bit in bits))


def _config_label(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(Path.cwd().resolve()))
    except (ValueError, OSError):
        return shorten_home(str(path))


def _print_summary(style: Style, shown: Sequence[Match]) -> None:
    """A compact "where the space goes" breakdown of the reported matches."""
    total = sum(match.size for match in shown)
    if not total:
        return
    by_kind: dict[str, int] = {}
    for match in shown:
        by_kind[match.kind] = by_kind.get(match.kind, 0) + match.size

    label_width = min(10, max(len(kind) for kind in by_kind))
    bar_width = 22
    print("\n  " + style.dim("where the space goes"))
    for kind, size in sorted(by_kind.items(), key=lambda kv: (-kv[1], kv[0])):
        share = size / total
        filled = round(share * bar_width)
        if size and filled == 0:
            filled = 1
        bar = style.cyan("█" * filled) + " " * (bar_width - filled)
        print(
            f"  {kind:<{label_width}}  {human_size(size):>8}  {bar}  "
            f"{style.dim(f'{share * 100:3.0f}%')}"
        )


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
    stashed = None
    if args.delete and matches:
        if getattr(args, "hard", False):
            removal = remove(matches, roots=result.roots, dry_run=False)
        else:
            try:
                stashed = stash_mod.stash(
                    matches,
                    roots=result.roots,
                    stash_dir=_stash_dir(args),
                    label=result_label(getattr(args, "config_source", None)),
                )
            except (stash_mod.StashError, SafetyError) as exc:
                print(f"{PROG}: {exc}", file=sys.stderr)
                return 1
    payload = _as_json(
        result,
        matches,
        elapsed=elapsed,
        removal=removal,
        config_source=getattr(args, "config_source", None),
    )
    if stashed is not None:
        payload["stash"] = stashed.as_dict()
    json.dump(payload, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")
    if removal is not None and removal.failures:
        for failure in removal.failures:
            print(
                f"{PROG}: could not remove {failure.match.path}: {failure.error}", file=sys.stderr
            )
        return 1
    return 0


def _stash_dir(args: argparse.Namespace) -> Path:
    chosen = getattr(args, "stash_dir", None)
    return Path(chosen).expanduser() if chosen else stash_mod.default_stash_dir()


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
    hard = bool(getattr(args, "hard", False))
    verb = "Delete" if hard else "Move to the stash"

    if not args.yes:
        if not sys.stdin.isatty():
            print(
                f"\n  {style.yellow('refusing to delete without confirmation')}: "
                "re-run with --yes for non-interactive use.",
                file=sys.stderr,
            )
            return 1
        hint = "" if hard else " — undoable with 'devdust undo'"
        sys.stdout.write(f"\n  {verb} {label}?{hint} [y/N] ")
        sys.stdout.flush()
        answer = sys.stdin.readline().strip().lower()
        if answer not in ("y", "yes"):
            print("  " + style.dim("aborted, nothing deleted."))
            return 0

    if hard:
        return _do_hard_delete(style, result, targets, shown, total)

    try:
        record = stash_mod.stash(
            targets,
            roots=result.roots,
            stash_dir=_stash_dir(args),
            label=result_label(getattr(args, "config_source", None)),
        )
    except (stash_mod.StashError, SafetyError) as exc:
        print(f"\n  {style.yellow('!')} {exc}", file=sys.stderr)
        return 1

    summary = (
        f"stashed {len(record.items)} of {len(targets)} directories "
        f"({human_size(record.total_size)}) as {record.id}"
    )
    print("\n  " + style.green("\u2713 " + summary))
    print("  " + style.dim(f"undo with: {PROG} undo {record.id}"))
    purged, freed = stash_mod.prune(_stash_dir(args), keep=STASH_KEEP)
    if purged:
        print(
            "  "
            + style.dim(
                f"purged {purged} older stash{'es' if purged != 1 else ''} "
                f"(keeps the newest {STASH_KEEP}) · {human_size(freed)} gone for good"
            )
        )
    if len(shown) != total:
        print(
            "  "
            + style.dim(
                f"only the {len(shown)} entries shown were moved; use --top 0 to cover the rest."
            )
        )
    return 0


def result_label(config_source: Path | None) -> str:
    return f"config:{config_source.name}" if config_source else ""


def _do_hard_delete(
    style: Style,
    result: ScanResult,
    targets: Sequence[Match],
    shown: Sequence[Match],
    total: int,
) -> int:
    removal = remove(targets, roots=result.roots, dry_run=False)
    for failure in removal.failures:
        print(
            f"  {style.yellow('!')} {failure.match.path}: {failure.error}",
            file=sys.stderr,
        )
    freed = human_size(removal.freed)
    summary = f"removed {removal.removed} of {len(targets)} directories · freed {freed} (permanent)"
    print(
        "\n  " + (style.green("\u2713 " + summary) if not removal.failures else style.bold(summary))
    )
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


# ---------------------------------------------------------------------- init


def _cmd_init(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(
        prog=f"{PROG} init",
        description=(
            "Write a starter .devdust.toml. Every setting is documented and "
            "commented out, so nothing changes until you edit it."
        ),
    )
    parser.add_argument("directory", nargs="?", default=".", help="where to write it")
    parser.add_argument("--force", action="store_true", help="overwrite an existing file")
    args = parser.parse_args(list(argv))

    target = Path(args.directory).expanduser() / config_mod.CONFIG_FILENAME
    if target.exists() and not args.force:
        print(
            f"{PROG}: {target} already exists (use --force to overwrite)",
            file=sys.stderr,
        )
        return 1
    try:
        target.write_text(config_mod.template(), encoding="utf-8")
    except OSError as exc:
        print(f"{PROG}: cannot write {target}: {exc.strerror or exc}", file=sys.stderr)
        return 1
    print(f"wrote {target}")
    print("  every setting is commented out — uncomment what you want, nothing is on by default")
    return 0


# ---------------------------------------------------------------------- stash


def _cmd_stash(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(
        prog=f"{PROG} stash",
        description=(
            "What --delete parked instead of destroying. Every record can be put "
            "back with 'devdust undo', or dropped for good with 'devdust purge'."
        ),
    )
    parser.add_argument("action", nargs="?", choices=("list", "show"), default="list")
    parser.add_argument("id", nargs="?", help="record id (a unique prefix is enough)")
    parser.add_argument("--stash-dir", type=Path, default=None, metavar="PATH")
    parser.add_argument(
        "--json", action="store_true", dest="as_json", help="machine readable output"
    )
    parser.add_argument("--color", choices=("auto", "always", "never"), default="auto")
    args = parser.parse_args(list(argv))
    style = Style(enabled=_use_color(args.color))
    root = Path(args.stash_dir).expanduser() if args.stash_dir else stash_mod.default_stash_dir()

    try:
        if args.action == "show":
            record = stash_mod.find_record(args.id, root)
            records = [record]
        else:
            records = stash_mod.list_records(root)
    except stash_mod.StashError as exc:
        print(f"{PROG}: {exc}", file=sys.stderr)
        return 1

    if args.as_json:
        json.dump([r.as_dict() for r in records], sys.stdout, indent=2, ensure_ascii=False)
        sys.stdout.write("\n")
        return 0

    if not records:
        print("  " + style.dim("stash is empty — nothing has been deleted yet."))
        print("  " + style.dim(f"stash directory: {shorten_home(str(root))}"))
        return 0

    rows = []
    for record in records:
        rows.append(
            [
                record.id,
                human_size(record.total_size),
                str(len(record.items)),
                human_age_from_string(record.created),
                shorten_home(str(record.items[0].original.parent)) if record.items else "",
            ]
        )
    print(
        render_styled_table(
            ["STASH", "SIZE", "DIRS", "WHEN", "WHERE"],
            rows,
            styler=lambda col, _row, cell: (
                style.paint(cell, "bold") if col == 0 else style.dim(cell)
            ),
            header_styler=lambda _c, cell: style.dim(cell),
        )
    )
    if len(records) == 1:
        print()
        for item in records[0].items:
            print(
                "  " + style.dim(f"· {shorten_home(str(item.original))}  ({human_size(item.size)})")
            )
    total = sum(r.total_size for r in records)
    print(
        "\n  "
        + style.dim(
            f"{len(records)} stash{'es' if len(records) != 1 else ''} · {human_size(total)} "
            f"in {shorten_home(str(root))}"
        )
    )
    print("  " + style.dim(f"put it back with: {PROG} undo"))
    return 0


def human_age_from_string(created: str) -> str:
    from datetime import datetime

    try:
        then = datetime.fromisoformat(created).timestamp()
    except ValueError:
        return "?"
    return human_age(max(0.0, time.time() - then))


# ----------------------------------------------------------------------- undo


def _cmd_undo(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(
        prog=f"{PROG} undo",
        description="Move stashed directories back where they came from.",
    )
    parser.add_argument("id", nargs="?", help="record id (default: the newest stash)")
    parser.add_argument(
        "--only",
        action="append",
        default=[],
        metavar="PATH",
        help="restore just this directory (repeatable)",
    )
    parser.add_argument("--force", action="store_true", help="replace whatever is there now")
    parser.add_argument("--dry-run", action="store_true", help="say what would happen")
    parser.add_argument("--stash-dir", type=Path, default=None, metavar="PATH")
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--color", choices=("auto", "always", "never"), default="auto")
    args = parser.parse_args(list(argv))
    style = Style(enabled=_use_color(args.color))
    root = Path(args.stash_dir).expanduser() if args.stash_dir else stash_mod.default_stash_dir()

    try:
        record = stash_mod.find_record(args.id, root)
        outcome = stash_mod.restore(record, only=args.only, force=args.force, dry_run=args.dry_run)
    except stash_mod.StashError as exc:
        print(f"{PROG}: {exc}", file=sys.stderr)
        return 1

    if args.as_json:
        json.dump(
            {
                "stash": record.id,
                "dry_run": args.dry_run,
                "restored": outcome.restored,
                "size": outcome.size,
                "results": [
                    {"path": str(r.item.original), "ok": r.ok, "error": r.error}
                    for r in outcome.restores
                ],
            },
            sys.stdout,
            indent=2,
            ensure_ascii=False,
        )
        sys.stdout.write("\n")
        return 0 if not outcome.failures else 1

    for failure in outcome.failures:
        print(
            f"  {style.yellow('!')} {shorten_home(str(failure.item.original))}: {failure.error}",
            file=sys.stderr,
        )
    if not outcome.restores:
        print("  " + style.dim(f"nothing matched in stash {record.id}"))
        return 1
    verb = "would restore" if args.dry_run else "restored"
    summary = (
        f"{verb} {outcome.restored} of {len(outcome.restores)} directories "
        f"({human_size(outcome.size)}) from {record.id}"
    )
    print(
        "  " + (style.green("\u2713 " + summary) if not outcome.failures else style.bold(summary))
    )
    return 0 if not outcome.failures else 1


# ---------------------------------------------------------------------- purge


def _cmd_purge(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(
        prog=f"{PROG} purge",
        description="Throw stash records away for good.",
    )
    parser.add_argument("id", nargs="?", help="record id (default: the newest stash)")
    parser.add_argument("--all", action="store_true", help="purge every record")
    parser.add_argument(
        "--keep",
        type=int,
        default=None,
        metavar="N",
        help="keep the N newest records and purge the rest",
    )
    parser.add_argument("--dry-run", action="store_true", help="say what would go")
    parser.add_argument("-y", "--yes", action="store_true", help="skip the confirmation")
    parser.add_argument("--stash-dir", type=Path, default=None, metavar="PATH")
    parser.add_argument("--color", choices=("auto", "always", "never"), default="auto")
    args = parser.parse_args(list(argv))
    style = Style(enabled=_use_color(args.color))
    root = Path(args.stash_dir).expanduser() if args.stash_dir else stash_mod.default_stash_dir()

    try:
        if args.keep is not None:
            records = stash_mod.list_records(root)[args.keep :]
        elif args.all:
            records = stash_mod.list_records(root)
        else:
            records = [stash_mod.find_record(args.id, root)]
    except stash_mod.StashError as exc:
        print(f"{PROG}: {exc}", file=sys.stderr)
        return 1

    if not records:
        print("  " + style.dim("nothing to purge."))
        return 0

    size = sum(r.total_size for r in records)
    label = f"{len(records)} stash{'es' if len(records) != 1 else ''} ({human_size(size)})"
    if args.dry_run:
        for record in records:
            print("  " + style.dim(f"would purge {record.id} · {human_size(record.total_size)}"))
        print("\n  " + style.dim(f"{label} — nothing deleted."))
        return 0
    if not args.yes:
        if not sys.stdin.isatty():
            print(
                f"\n  {style.yellow('refusing to purge without confirmation')}: re-run with --yes.",
                file=sys.stderr,
            )
            return 1
        sys.stdout.write(f"\n  Purge {label} for good? [y/N] ")
        sys.stdout.flush()
        if sys.stdin.readline().strip().lower() not in ("y", "yes"):
            print("  " + style.dim("aborted, nothing purged."))
            return 0

    failures = 0
    for record in records:
        try:
            stash_mod.purge(record)
        except stash_mod.StashError as exc:
            print(f"  {style.yellow('!')} {exc}", file=sys.stderr)
            failures += 1
    print(
        "\n  "
        + style.green(
            f"\u2713 purged {len(records) - failures} stashes · {human_size(size)} gone for good"
        )
    )
    return 0 if not failures else 1


# --------------------------------------------------------------------- config


def _prescan_config(argv: Sequence[str]) -> tuple[Path | None, bool]:
    """Find ``--config``/``--no-config`` before the real parse.

    The config file decides the parser's defaults, so it has to be located
    before ``parse_args`` runs.
    """
    explicit: Path | None = None
    disabled = False
    index = 0
    while index < len(argv):
        arg = argv[index]
        if arg == "--no-config":
            disabled = True
        elif arg == "--config":
            if index + 1 < len(argv):
                explicit = Path(argv[index + 1]).expanduser()
                index += 1
        elif arg.startswith("--config="):
            explicit = Path(arg.split("=", 1)[1]).expanduser()
        index += 1
    return explicit, disabled


def _load_config(argv: Sequence[str]) -> config_mod.Config:
    explicit, disabled = _prescan_config(argv)
    if disabled and explicit is not None:
        raise config_mod.ConfigError("--config and --no-config cannot be combined")
    if disabled:
        return config_mod.Config()
    if explicit is not None:
        if not explicit.is_file():
            raise config_mod.ConfigError(f"no such config file: {explicit}")
        return config_mod.load(explicit)
    found = config_mod.discover()
    return config_mod.load(found) if found is not None else config_mod.Config()


# --------------------------------------------------------------------- main


def main(argv: Sequence[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "rules":
        return _cmd_rules(argv[1:])
    if argv and argv[0] == "init":
        return _cmd_init(argv[1:])
    if argv and argv[0] == "stash":
        return _cmd_stash(argv[1:])
    if argv and argv[0] == "undo":
        return _cmd_undo(argv[1:])
    if argv and argv[0] == "purge":
        return _cmd_purge(argv[1:])

    parser = build_parser()
    try:
        config = _load_config(argv)
    except config_mod.ConfigError as exc:
        print(f"{PROG}: config: {exc}", file=sys.stderr)
        return 2
    if config.provided:
        parser.set_defaults(**config.as_defaults())
    args = parser.parse_args(argv)
    args.config_source = config.source
    args.config_paths = tuple(config.paths)

    try:
        return _cmd_scan(args)
    except KeyboardInterrupt:  # pragma: no cover - interactive only
        print("\naborted", file=sys.stderr)
        return 130


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
