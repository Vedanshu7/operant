"""Task runner for Operant: the single point of `invoke` (run as `i <task>`).

The coding standard is the vendored amp linter under
``src/operant/dev/linters``; ``i lint`` runs it, and it must be clean before
every commit.
"""

from __future__ import annotations

from typing import Any

import invoke

# The vendored linter and its helper library are third-party, maintained
# upstream, and excluded from linting rather than held to this repo's standard.
_SOURCE_DIRS = ("src/operant", "tests")
_EXCLUDED_DIRS = ("src/operant/dev/helpers", "src/operant/dev/linters")
_LINTER_ENTRY_POINT = "operant.dev.linters.base"


def _run(ctx: Any, cmd: str, **kwargs: Any) -> Any:
    return ctx.run(cmd, pty=True, **kwargs)


@invoke.task(
    help={"files": "Space separated files to lint; defaults to all source"}
)
def lint(ctx: Any, files: str | None = None) -> None:
    """Run the vendored linter, which must be clean before every commit."""
    if files is None:
        pathspecs = [f"'{d}/*.py'" for d in _SOURCE_DIRS] + [
            f"':!{d}'" for d in _EXCLUDED_DIRS
        ]
        result = ctx.run(
            f"git ls-files -- {' '.join(pathspecs)}", hide=True, warn=True
        )
        files = " ".join(result.stdout.split())
    if not files:
        print("No files to lint.")
        return
    _run(ctx, f"uv run python -m {_LINTER_ENTRY_POINT} -f {files}")


@invoke.task
def test(ctx: Any) -> None:
    """Run the unit test suite."""
    _run(ctx, "uv run pytest tests/unit")


ns = invoke.Collection(lint, test)
