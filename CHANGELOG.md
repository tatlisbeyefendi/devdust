# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

_Nothing yet._

## [0.2.0] — 2026-10-30

The "this is a demo, and it grows" release: a config file you can commit, a
breakdown that answers "where is the space actually going?", and a smaller, more
honest dependency floor.

### Added

- **`.devdust.toml` configuration.** `paths`, `exclude`, `kinds`, `min_size`,
  `older_than`, `include_review`, `top`, `sort`, `color` and `summary` can be
  set once instead of retyping flags. The file is discovered in the current
  directory, then its parents (stopping at `$HOME`), then
  `$XDG_CONFIG_HOME/devdust/config.toml`. Unknown keys are rejected with a
  "did you mean …?" suggestion, and invalid values are reported with the file
  name and the reason.
- **`devdust init [DIR]`** writes a fully commented starter config; the result
  changes no behaviour until you uncomment something. `--force` overwrites.
- **`--config FILE` / `--no-config`** to point at a specific file or to ignore
  every config file. Command line flags always win over the file.
- **`--summary`** prints a "where the space goes" breakdown by ecosystem, with
  a bar and a percentage per kind.
- **JSON gains `summary`** (`by_kind`, `by_confidence`) and `config` (the file
  that was used, or `null`); the header line shows the active config file.
- Tests for config discovery, parsing, validation and the new CLI paths
  (162 tests total).

### Changed

- **Python 3.11+ is now required.** The config file is parsed with the standard
  library's `tomllib`, which keeps the promise of zero runtime dependencies
  instead of pulling in `tomli` for older interpreters. Python 3.10 reached
  end-of-life in October 2026.
- `--top` now also limits what `--delete` removes (it always did) and the
  summary is computed from exactly the entries shown.

### Security

- **`--delete` and `--yes` are explicitly not configurable.** A committed
  `.devdust.toml` can change what devdust reports, never whether it deletes;
  both keys are rejected as unknown, and a test pins that behaviour.

## [0.1.0] — 2026-10-30

### Added

- `devdust` scans one or more roots and reports every build artifact / cache
  directory it recognises, sorted by size, with file count and age.
- Rule table with 40+ patterns across `python`, `node`, `rust`, `java`,
  `dotnet`, `ios`, `swift`, `terraform` and `generic` ecosystems.
- Two confidence tiers: `safe` (deleted by default) and `review` (opt in with
  `--include-review`) for ambiguous names such as `build/`, `bin/`, `target/`
  and `vendor/`.
- Safety model: dry run by default, confirmation prompt for `--delete`, scan
  roots / `$HOME` / the working directory are never deleted, symlinks are never
  followed or removed, deletions are restricted to paths inside a scanned root,
  and read-only trees are unlocked and retried once.
- Filters: `--min-size`, `--older-than`, `--kinds`, `--exclude`, `--max-depth`,
  `--top`, `--sort`, plus `--include-review`.
- `--json` output with per-item sizes, ages, kinds, confidence and removal
  results, for scripting and CI.
- `devdust rules` subcommand to print the pattern table.
- Colour output with `NO_COLOR` / `FORCE_COLOR` support and a `--color` switch.
- Documentation in English and Turkish, with demo images rendered from real CLI
  output (`make demo`).
- Test suite covering rules, formatting, scanning, deletion guards
  and the CLI, plus GitHub Actions CI on Python 3.9–3.13.

[Unreleased]: https://github.com/tatlisbeyefendi/devdust/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/tatlisbeyefendi/devdust/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/tatlisbeyefendi/devdust/releases/tag/v0.1.0
