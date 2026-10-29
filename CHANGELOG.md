# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

_Nothing yet._

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
- Test suite (106 tests) covering rules, formatting, scanning, deletion guards
  and the CLI, plus GitHub Actions CI on Python 3.9–3.13.

[Unreleased]: https://github.com/OWNER/devdust/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/OWNER/devdust/releases/tag/v0.1.0
