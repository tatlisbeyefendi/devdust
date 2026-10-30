# devdust

**Find the build artifacts and caches your projects leave behind — and sweep them away safely.**

[![Python](https://img.shields.io/badge/python-3.11%2B-3776ab?logo=python&logoColor=white)](https://www.python.org)
[![Zero dependencies](https://img.shields.io/badge/dependencies-0-brightgreen)](pyproject.toml)
[![Status: demo](https://img.shields.io/badge/status-working%20demo-orange)](#project-status)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue)](LICENSE)

<img src="docs/demo.svg" alt="devdust listing reclaimable directories in a demo workspace" width="720">

`devdust` walks your projects, reports every `node_modules`, `__pycache__`,
`.next`, `target` and `.venv` it finds, tells you how many gigabytes they eat —
and deletes them only when you ask, and only the ones you were shown.

- **Dry run by default.** Nothing is ever deleted without `--delete`.
- **Two confidence tiers.** Cheap-to-rebuild caches are `safe`; ambiguous names
  like `build/`, `bin/` or `vendor/` are `review` and stay out of the way
  unless you opt in.
- **Prunes smartly.** A match is measured once and its subtree is skipped, so
  the totals are honest and the walk stays fast.
- **No dependencies.** One `pip install`, no supply chain to audit.

## Project status

> **This is a working demo, and it is going to keep growing.** 🚧
>
> `devdust` is a small, complete tool — it scans, filters, reports, deletes and
> has a test suite and CI to keep it honest — but it is a **demo of the idea**,
> not a mature product. Version **0.2.0** is an early preview: expect the CLI,
> the output and the rule table to change between releases, and treat deletion
> as permanent (there is no undo yet).
>
> The point of shipping it as a demo is to make the shape of the final tool
> visible and testable early. Feedback, bug reports and "please teach it about
> my ecosystem" issues are exactly what moves the roadmap along.

### Roadmap

| | Item |
| --- | --- |
| ✅ 0.1.0 | Scan, filter, two confidence tiers, safe delete, JSON output |
| ✅ 0.2.0 | `.devdust.toml` + `devdust init`, `--summary` breakdown, Python 3.11+ only |
| 🔜 0.3.0 | Undo: move to the OS trash (or a `--stash` directory) instead of `rm -rf` |
| 🔜 | Parallel scanning (`--jobs`) for very large trees |
| 🔜 | `.gitignore`-aware mode, and per-project overrides in one config |
| 🔜 | Interactive review screen: pick directories one by one |
| 💭 | Editor / CI integrations, JSON schema, `devdust doctor`, shell completions |

Priorities are shaped by real usage — if something is missing for your
workflow, open an issue.

---

## Install

```console
$ pipx install devdust        # recommended: isolated, always on PATH
$ uv tool install devdust     # or with uv
$ pip install devdust         # or into the current environment
```

From a checkout:

```console
$ git clone https://github.com/OWNER/devdust.git
$ cd devdust
$ pipx install .
```

Python 3.11+ on Linux and macOS. Windows is best-effort (path handling is
platform-neutral, but the test suite is only run on POSIX). Python 3.11 is the
floor so that the config file can be parsed with the standard library's
`tomllib` — keeping the zero-dependency promise.

## Quick start

```console
$ devdust                     # dry run over the current directory
$ devdust ~/work ~/oss        # several roots at once
$ devdust --min-size 100MB    # only the heavy hitters
$ devdust --older-than 90d    # caches you have not touched in three months
$ devdust --summary           # where is the space actually going?
$ devdust --delete            # remove what you saw (asks for confirmation)
```

Everything is a report until you pass `--delete`:

<img src="docs/demo-delete.svg" alt="devdust deleting directories" width="720">

## What it finds

| Kind | Examples |
| --- | --- |
| `python` | `__pycache__`, `.venv`, `venv`, `.pytest_cache`, `.mypy_cache`, `.ruff_cache`, `.tox`, `.nox`, `*.egg-info`, `.hypothesis` |
| `node` | `node_modules`, `.next`, `.nuxt`, `.svelte-kit`, `.turbo`, `.parcel-cache`, `.vite`, `.angular`, `bower_components` |
| `rust` | `target` |
| `java` | `.gradle`, `out` |
| `dotnet` | `bin`, `obj` |
| `ios` / `swift` | `Pods`, `DerivedData`, `.build` |
| `terraform` | `.terraform`, `.terragrunt-cache` |
| `generic` | `build`, `dist`, `vendor`, `.cache` |

Run `devdust rules` for the authoritative, always-current list:

```console
$ devdust rules
  PATTERN           KIND   CONF    WHAT IT IS
  ----------------  -----  ------  ---------------------------------
  __pycache__       python safe    Compiled bytecode
  .pytest_cache     python safe    pytest cache
  node_modules      node   safe    npm / yarn / pnpm packages
  target            rust   review  Cargo build artifacts
  build             generic review Build output (also a common scripts dir)
  ...
```

## The safety model

Deleting directories deserves paranoia, so `devdust` has a few rules of its own:

1. **Dry run by default.** `--delete` is required, and it only removes the
   entries that were actually printed (`--top 25` prints 25, so it deletes 25 —
   use `--top 0` to cover everything).
2. **Ambiguous names need a second opinion.** `build/`, `bin/`, `obj/`,
   `target/`, `vendor/` and friends are `review` tier: visible with
   `--include-review`, invisible otherwise.
3. **Destructive flags are not configurable.** A `.devdust.toml` can change
   what gets *reported*; it can never turn on `--delete` or `--yes`. Deleting
   files stays an explicit decision on the command line, every time.
4. **Scan roots are never candidates.** Pointing `devdust` at a
   `node_modules` directory does not offer to delete the directory itself.
   Neither is `$HOME`, the current directory or a filesystem root ever touched.
5. **Symlinks are never followed and never deleted.** A link into `/` cannot
   inflate your "reclaimable" number, and it cannot be turned into a data loss
   report either.
6. **Paths must live inside a scanned root.** Anything else is refused by the
   deletion guard, even if it somehow reached the list.
7. **Failures are per-directory.** One unwritable entry does not abort the run;
   it is reported on stderr and reflected in the exit code. Read-only trees are
   unlocked and retried once.

There is **no undo** yet — restoring a deleted `node_modules` means reinstalling
it. That is exactly what the 0.3.0 roadmap item is about.

## Configuration

Preferences can live in a `.devdust.toml` file, so you do not have to retype the
same flags:

```console
$ devdust init          # writes a starter file, everything commented out
```

```toml
# .devdust.toml
[devdust]
paths = ["~/code", "~/oss"]     # default roots
min_size = "20MB"               # ignore the small stuff
older_than = "30d"              # only things nobody has touched
kinds = ["node", "python"]      # stay in your lane
exclude = ["vendor", "*-backup"]
summary = true                  # always show the breakdown
```

Where it is looked up:

1. `--config FILE` if you pass one,
2. `.devdust.toml` in the current directory, then in each parent directory
   (the search stops at `$HOME`),
3. `$XDG_CONFIG_HOME/devdust/config.toml` (default `~/.config/devdust/config.toml`).

Command line flags always win over the file, `--no-config` ignores every config
file, and unknown keys are rejected with a suggestion:

```console
$ devdust
devdust: config: /home/dev/.devdust.toml: unknown key(s) in [devdust]:
  'min_sizes' (did you mean 'min_size'?). Known keys: paths, exclude, kinds,
  min_size, older_than, include_review, top, sort, color, summary
```

`devdust init` changes nothing by default: every setting is commented out, so
the file is documentation first and configuration second.

## Usage

```
devdust [PATH ...] [options]
devdust rules            # every known directory pattern
devdust init [DIR]       # write a starter .devdust.toml
```

| Option | What it does |
| --- | --- |
| `--delete` | Remove the directories shown instead of only reporting them |
| `-y`, `--yes` | Skip the confirmation prompt (required when stdin is not a TTY) |
| `--include-review` | Also consider ambiguous names such as `build/`, `bin/`, `target/` |
| `--kinds LIST` | Restrict to ecosystems, e.g. `--kinds node,python` |
| `--exclude GLOB` | Skip directories matching a glob (repeatable) |
| `--min-size SIZE` | Ignore matches smaller than `SIZE` (`50MB`, `1.5g`, `512`) |
| `--older-than AGE` | Only matches untouched for `AGE` (`30d`, `12h`, `2w`) |
| `--max-depth N` | Do not descend more than `N` levels below each root |
| `--top N` | Show at most `N` entries; `0` shows everything (default `25`) |
| `--sort {size,age,path,kind}` | Entry order (default: biggest first) |
| `--summary` | Add a "where the space goes" breakdown by ecosystem |
| `--config FILE` | Use this config file instead of searching for one |
| `--no-config` | Ignore every config file |
| `--json` | Machine-readable output (never truncated by `--top`) |
| `--color {auto,always,never}` | Colour control; also honours `NO_COLOR` / `FORCE_COLOR` |
| `--version` | Print the version |

Exit codes: `0` success, `1` a scan or deletion failed, `2` invalid usage.

### The `--summary` breakdown

```console
$ devdust ~ --summary
  ...
  where the space goes
  node      152 MB  ███████████████             66%
  rust     64.6 MB  ██████                      28%
  java     10.4 MB  █                            5%
  python   1.81 MB  █                            1%
```

### JSON output

```console
$ devdust ~/work --json | jq '.totals'
{
  "size": 812345678,
  "size_human": "775 MB",
  "files": 43120,
  "directories": 12
}
```

Every item carries `path`, `size`, `size_human`, `files`, `age_seconds`,
`age_human`, `kind`, `confidence` and the `rule` that matched. The payload also
contains `summary.by_kind` / `summary.by_confidence` totals and the config file
that was used (`null` when there is none). With `--delete` it gains a `removed`
block with the freed bytes and any failures.

## Recipes

```bash
# monthly sweep of everything that has been idle for a quarter
devdust ~/code --min-size 50MB --older-than 90d --delete

# free space on CI runners before a build
devdust . --exclude .git --kinds node --delete --yes

# what exactly is eating the disk right now?
devdust ~ --summary --top 0 --sort size --min-size 10MB

# time machine: which projects have not been touched since last year?
devdust ~/code --sort age --top 10
```

A shell alias makes the common case a two-letter command:

```bash
alias dd='devdust ~/code --min-size 20MB'
```

## Development

```console
$ make install     # editable install plus dev extras
$ make test        # pytest
$ make lint        # ruff check + ruff format --check
$ make demo        # regenerate docs/demo*.svg from the CLI's real output
```

The demo images are rendered from real program output by
`scripts/render_demo_svg.py`, so they cannot drift out of date, and
`scripts/make_demo_tree.py` builds the fake workspace they are generated from.

Layout:

```
src/devdust/
  cli.py          argument parsing, output, exit codes
  config.py       .devdust.toml discovery, parsing and validation
  scanner.py      walking, size accounting, safety guards, removal
  rules.py        the pattern table and confidence tiers
  formatting.py   sizes, ages, colours, table rendering
tests/            unit + end-to-end tests, no network and no fixtures on disk
```

Adding a pattern is a one-line change in `src/devdust/rules.py`; adding a config
key means touching `KNOWN_KEYS`, the parser, `template()` and the docs together.
See [CONTRIBUTING.md](CONTRIBUTING.md).

## FAQ

**Why not just `npkill` / `cargo clean` / `rm -rf`?**
Those cover one ecosystem at a time. `devdust` is one pass over a whole
workspace, with a safety model you can reason about, and machine-readable output
for scripting.

**Does it follow symlinks?**
No — never. Symlinked directories are skipped while measuring and refused by the
deletion guard.

**Does it respect `.gitignore`?**
Not yet (it is on the [roadmap](#roadmap)). `devdust` looks at directory names,
not repository rules; ignored paths that look like caches are still reported
(that is usually what you want) and `.git/` is never entered.

**Are the sizes "apparent" or "on disk"?**
Apparent: the sum of `st_size` for every regular file, which is what `du
--apparent-size` reports. On filesystems with clones, reflinks or hardlinks
(APFS, Btrfs, `pnpm` stores) the space you actually get back can be smaller than
the number shown.

**Can I undo a deletion?**
Not in 0.2.0 — deletion is permanent. Trash/stash support is the next milestone.

**Windows?**
It should work, but it is untested; bug reports with a failing test are welcome.

## License

MIT — see [LICENSE](LICENSE).

---

<sub>Türkçe doküman: [README.tr.md](README.tr.md)</sub>
