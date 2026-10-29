# devdust

**Find the build artifacts and caches your projects leave behind — and sweep them away safely.**

[![Python](https://img.shields.io/badge/python-3.9%2B-3776ab?logo=python&logoColor=white)](https://www.python.org)
[![Zero dependencies](https://img.shields.io/badge/dependencies-0-brightgreen)](pyproject.toml)
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

Python 3.9+ on Linux and macOS. Windows is best-effort (path handling is
platform-neutral, but the test suite is only run on POSIX).

## Quick start

```console
$ devdust                     # dry run over the current directory
$ devdust ~/work ~/oss        # several roots at once
$ devdust --min-size 100MB    # only the heavy hitters
$ devdust --older-than 90d    # caches you have not touched in three months
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
3. **Scan roots are never candidates.** Pointing `devdust` at a
   `node_modules` directory does not offer to delete the directory itself.
   Neither is `$HOME`, the current directory or a filesystem root ever touched.
4. **Symlinks are never followed and never deleted.** A link into `/` cannot
   inflate your "reclaimable" number, and it cannot be turned into a data loss
   report either.
5. **Paths must live inside a scanned root.** Anything else is refused by the
   deletion guard, even if it somehow reached the list.
6. **Failures are per-directory.** One unwritable entry does not abort the run;
   it is reported on stderr and reflected in the exit code. Read-only trees are
   unlocked and retried once.

## Usage

```
devdust [PATH ...] [options]
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
| `--json` | Machine-readable output (never truncated by `--top`) |
| `--color {auto,always,never}` | Colour control; also honours `NO_COLOR` / `FORCE_COLOR` |
| `--version` | Print the version |
| `rules` (subcommand) | List every pattern `devdust` knows about |

Exit codes: `0` success, `1` a scan or deletion failed, `2` invalid usage.

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
`age_human`, `kind`, `confidence` and the `rule` that matched. With `--delete`
the payload also includes a `removed` block with the freed bytes and any
failures.

## Recipes

```bash
# monthly sweep of everything that has been idle for a quarter
devdust ~/code --min-size 50MB --older-than 90d --delete

# free space on CI runners before a build
devdust . --exclude .git --kinds node --delete --yes

# what exactly is eating the disk right now?
devdust ~ --top 0 --sort size --min-size 10MB

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
  scanner.py      walking, size accounting, safety guards, removal
  rules.py        the pattern table and confidence tiers
  formatting.py   sizes, ages, colours, table rendering
tests/            unit + end-to-end tests, no network and no fixtures on disk
```

Adding a pattern is a one-line change in `src/devdust/rules.py`; see
[CONTRIBUTING.md](CONTRIBUTING.md).

## FAQ

**Why not just `npkill` / `cargo clean` / `rm -rf`?**
Those cover one ecosystem at a time. `devdust` is one pass over a whole
workspace, with a safety model you can reason about, and machine-readable output
for scripting.

**Does it follow symlinks?**
No — never. Symlinked directories are skipped while measuring and refused by the
deletion guard.

**Does it respect `.gitignore`?**
No. `devdust` looks at directory names, not repository rules. Ignored paths that
look like caches are still reported (that is usually what you want) and
`.git/` is never entered.

**Are the sizes "apparent" or "on disk"?**
Apparent: the sum of `st_size` for every regular file, which is what `du
--apparent-size` reports. On filesystems with clones, reflinks or hardlinks
(APFS, Btrfs, `pnpm` stores) the space you actually get back can be smaller
than the number shown.

**Windows?**
It should work, but it is untested; bug reports with a failing test are welcome.

## License

MIT — see [LICENSE](LICENSE).

---

<sub>Türkçe doküman: [README.tr.md](README.tr.md)</sub>
