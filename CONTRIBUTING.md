# Contributing to devdust

Thanks for wanting to help! This project is deliberately small: no runtime
dependencies, no clever abstractions, and a hard rule that nothing gets deleted
without an explicit request.

## Getting set up

```console
$ git clone https://github.com/OWNER/devdust.git
$ cd devdust
$ python3 -m venv .venv && source .venv/bin/activate
$ make install     # editable install + dev extras
$ make test        # the whole suite runs in well under a second
$ make lint        # ruff check + ruff format --check
```

Optional: `pre-commit install` to run the same checks on every commit.

## Adding a new directory pattern

Most contributions are one line in [`src/devdust/rules.py`](src/devdust/rules.py):

```python
(Rule(".sass-cache", "node", "Sass compiler cache"),)
```

Guidelines:

- **Pick the right tier.** Use `SAFE` only when the directory is pure,
  cheap-to-regenerate output (a cache, a compiler's scratch space). Anything
  whose name could also be a source directory — `build`, `bin`, `vendor`,
  `docs/_build` — belongs in `REVIEW`.
- **One line per pattern**, with a short description a stranger understands.
- **Name the ecosystem** in `kind`; reuse an existing one unless a genuinely new
  ecosystem arrives.
- **Add a test** in `tests/test_rules.py` if the pattern is interesting
  (globs, casing, near-miss names).

Then update the table in `README.md` (and `README.tr.md`) if the new kind is not
already listed, and add a `CHANGELOG.md` entry.

## Adding a configuration key

The config file is intentionally boring: one flat `[devdust]` table. A new key
means four small edits in one commit:

1. `KNOWN_KEYS` and the `Config` dataclass in `src/devdust/config.py`,
2. a `_parse` branch in `load()` (reuse the existing validators when possible),
3. the corresponding `parser.add_argument` in `src/devdust/cli.py`, if the flag
   does not exist yet,
4. the commented example in `config.template()` plus the README tables.

Add tests to `tests/test_config.py` for the happy path *and* for the error
message — a config file that fails silently is worse than no config file.

**Never add a key that can turn on `--delete` or `--yes`.** `tests/test_config.py`
asserts that those keys are rejected as unknown.

## Changing the safety model

The guards in `src/devdust/scanner.py` exist to make `--delete` boring. If you
touch them, the change needs:

1. a test that shows what is *refused* as well as what is allowed,
2. a note in the README's "safety model" section,
3. an entry in the changelog under `### Changed` or `### Security`.

## Reporting bugs

Please include:

- `devdust --version`, your OS and Python version,
- the command you ran (redact anything private),
- what you expected and what happened — for anything destructive, the output of
  the dry run is usually enough to reproduce it.

Use the issue templates; they ask for exactly this.

## Pull requests

- Keep them focused; one topic per PR.
- `make lint` and `make test` must be green.
- Add a changelog entry.
- Write commit messages in the imperative mood (`Add pnpm store rule`), and keep
  the first line under 72 characters.

## Code style

- Formatted by `ruff format` (100 column limit), linted by `ruff check`.
- Type hints everywhere; `from __future__ import annotations` at the top.
- Standard library only. A dependency needs a very good reason — this tool is
  installed on developer machines and on CI runners.
- No `print` in library code: `cli.py` owns all output.

## Regenerating the demo images

`docs/demo.svg` and `docs/demo-delete.svg` are generated from real CLI output:

```console
$ make demo
```

Never edit them by hand — the whole point is that they cannot lie.

## Code of conduct

Be decent to each other. Harassment or dismissive behaviour is not welcome; the
maintainers may remove comments and contributions that make the project a worse
place to be.
