"""The rule table: which directories are considered build output / caches.

Every rule carries a *confidence* level:

``SAFE``
    Pure caches or artifacts that are cheap to regenerate (``__pycache__``,
    ``node_modules``, ``.pytest_cache`` ...). Deletable by default.

``REVIEW``
    Names that are *usually* build output but can also be meaningful source
    directories (``build``, ``bin``, ``vendor`` ...). They are reported, but
    only deleted when you explicitly opt in.

Keeping this table in one place means the scanner, the CLI and the docs all
agree on what devdust knows about.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from fnmatch import fnmatchcase

SAFE = "safe"
REVIEW = "review"

CONFIDENCES = (SAFE, REVIEW)


@dataclass(frozen=True)
class Rule:
    """A single pattern -> category mapping."""

    pattern: str
    """Directory basename to match. Supports shell-style globs (``*.egg-info``)."""

    kind: str
    """Coarse ecosystem bucket, used by ``--kinds`` filtering."""

    description: str
    """Short human readable explanation, shown by ``devdust rules``."""

    confidence: str = SAFE

    def matches(self, name: str) -> bool:
        return fnmatchcase(name, self.pattern)


# Ordered: the first matching rule wins.
RULES: tuple[Rule, ...] = (
    # ---------------------------------------------------------------- Python
    Rule("__pycache__", "python", "Compiled bytecode"),
    Rule(".pytest_cache", "python", "pytest cache"),
    Rule(".mypy_cache", "python", "mypy incremental cache"),
    Rule(".ruff_cache", "python", "Ruff cache"),
    Rule(".pytype", "python", "pytype cache"),
    Rule(".hypothesis", "python", "Hypothesis example database"),
    Rule(".ipynb_checkpoints", "python", "Jupyter autosave copies"),
    Rule("htmlcov", "python", "Coverage HTML report"),
    Rule("coverage", "python", "Coverage data / reports"),
    Rule(".tox", "python", "tox environments"),
    Rule(".nox", "python", "nox environments"),
    Rule(".venv", "python", "Virtual environment"),
    Rule("venv", "python", "Virtual environment"),
    Rule("*.egg-info", "python", "Setuptools metadata"),
    Rule(".eggs", "python", "Setuptools eggs"),
    Rule("build", "generic", "Build output (also a common scripts dir)", REVIEW),
    Rule("dist", "generic", "Packaged distribution artifacts", REVIEW),
    # ------------------------------------------------------------- JavaScript
    Rule("node_modules", "node", "npm / yarn / pnpm packages"),
    Rule(".next", "node", "Next.js build output"),
    Rule(".nuxt", "node", "Nuxt build output"),
    Rule(".svelte-kit", "node", "SvelteKit build output"),
    Rule(".turbo", "node", "Turborepo cache"),
    Rule(".parcel-cache", "node", "Parcel cache"),
    Rule(".vite", "node", "Vite cache"),
    Rule(".angular", "node", "Angular build cache"),
    Rule(".output", "node", "Nitro / Nuxt output"),
    Rule(".expo", "node", "Expo cache"),
    Rule("bower_components", "node", "Bower packages"),
    Rule(".storybook", "node", "Storybook static build", REVIEW),
    # ------------------------------------------------------------------ Rust
    Rule("target", "rust", "Cargo build artifacts", REVIEW),
    # ------------------------------------------------------------------ Java
    Rule(".gradle", "java", "Gradle project cache", REVIEW),
    Rule("out", "java", "IntelliJ / Kotlin output", REVIEW),
    # ------------------------------------------------------------------ .NET
    Rule("bin", "dotnet", "Compiled binaries", REVIEW),
    Rule("obj", "dotnet", "Intermediate build objects", REVIEW),
    # ------------------------------------------------------- Apple platforms
    Rule("Pods", "ios", "CocoaPods dependencies", REVIEW),
    Rule("DerivedData", "ios", "Xcode derived data"),
    Rule(".build", "swift", "Swift Package Manager build", REVIEW),
    # ------------------------------------------------------------- Terraform
    Rule(".terraform", "terraform", "Terraform providers & modules"),
    Rule(".terragrunt-cache", "terraform", "Terragrunt cache"),
    # --------------------------------------------------- Language-agnostic
    Rule("vendor", "generic", "Vendored dependencies (often committed!)", REVIEW),
    Rule(".cache", "generic", "Project-level cache", REVIEW),
)

RULE_COUNT = len(RULES)


def iter_rules() -> Iterator[Rule]:
    return iter(RULES)


def kinds() -> tuple[str, ...]:
    """Sorted list of every ecosystem name mentioned in the table."""
    return tuple(sorted({rule.kind for rule in RULES}))


def match(name: str) -> Rule | None:
    """Return the first rule matching a directory basename, if any."""
    for rule in RULES:
        if rule.matches(name):
            return rule
    return None


def select(
    *,
    kinds_in: Sequence[str] | None = None,
    include_review: bool = False,
    rules: Iterable[Rule] = RULES,
) -> tuple[Rule, ...]:
    """Filter the table down to the enabled subset."""
    wanted = {k.strip().lower() for k in kinds_in} if kinds_in else None
    out = []
    for rule in rules:
        if wanted is not None and rule.kind not in wanted:
            continue
        if rule.confidence == REVIEW and not include_review:
            continue
        out.append(rule)
    return tuple(out)


__all__ = [
    "CONFIDENCES",
    "REVIEW",
    "RULES",
    "RULE_COUNT",
    "SAFE",
    "Rule",
    "iter_rules",
    "kinds",
    "match",
    "select",
]
