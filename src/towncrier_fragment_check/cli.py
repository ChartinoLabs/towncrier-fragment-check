"""Command line interface for the towncrier fragment check."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from towncrier_fragment_check import __version__
from towncrier_fragment_check.check import (
    DEFAULT_PROJECT_DIRECTORY,
    PROJECT_CONFIG_SEPARATOR,
    REQUIRE_ANY,
    REQUIRE_CHOICES,
    CheckOptions,
    Project,
    run_check,
)

PROGRAM_NAME = "towncrier-fragment-check"
DESCRIPTION = (
    "Fail when a branch does not add a towncrier changelog fragment. "
    "Wraps towncrier check with monorepo support, subdirectory-safe "
    "behaviour, base-ref resolution for CI and pre-commit, and rejection "
    "of empty fragments."
)
EMPTY_PROJECT_ERROR = (
    "--project needs a directory, optionally followed by "
    f"'{PROJECT_CONFIG_SEPARATOR}' and a config file path"
)

PROJECT_HELP = (
    "Towncrier project to check, as DIR or DIR:CONFIG. Both paths are "
    "relative to the git toplevel. Repeatable. Defaults to a single project "
    "at the repository root."
)
REQUIRE_HELP = (
    "Pass rule across projects: 'any' accepts a fragment in one project, "
    "'all' requires a fragment in every project."
)
COMPARE_WITH_HELP = "Base ref to diff against."
STAGED_HELP = "Include staged files, for use at the pre-commit stage."
ALLOW_EMPTY_HELP = "Do not fail on empty or whitespace-only fragments."
SKIP_NEW_BRANCH_HELP = (
    "Exit 0 when PRE_COMMIT_FROM_REF is all zeros, which means the branch "
    "does not exist on the remote yet."
)
VERBOSE_HELP = "Always print the full towncrier output for every project."


def parse_project(value: str) -> Project:
    """Parse a ``--project`` value of the form ``DIR`` or ``DIR:CONFIG``.

    Args:
        value: Raw command line value.

    Returns:
        The parsed project.

    Raises:
        argparse.ArgumentTypeError: If the directory part is empty.
    """
    directory, separator, config = value.partition(PROJECT_CONFIG_SEPARATOR)
    directory = directory.strip()
    config = config.strip()
    if not directory or (separator and not config):
        raise argparse.ArgumentTypeError(EMPTY_PROJECT_ERROR)
    return Project(directory=directory, config=config or None)


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser for the console script."""
    parser = argparse.ArgumentParser(prog=PROGRAM_NAME, description=DESCRIPTION)
    parser.add_argument(
        "--project",
        dest="projects",
        action="append",
        type=parse_project,
        metavar="DIR[:CONFIG]",
        help=PROJECT_HELP,
    )
    parser.add_argument(
        "--require",
        choices=REQUIRE_CHOICES,
        default=REQUIRE_ANY,
        help=REQUIRE_HELP,
    )
    parser.add_argument(
        "--compare-with", metavar="BRANCH", default=None, help=COMPARE_WITH_HELP
    )
    parser.add_argument("--staged", action="store_true", help=STAGED_HELP)
    parser.add_argument("--allow-empty", action="store_true", help=ALLOW_EMPTY_HELP)
    parser.add_argument(
        "--skip-new-branch", action="store_true", help=SKIP_NEW_BRANCH_HELP
    )
    parser.add_argument("--verbose", "-v", action="store_true", help=VERBOSE_HELP)
    parser.add_argument(
        "--version", action="version", version=f"{PROGRAM_NAME} {__version__}"
    )
    return parser


def build_options(namespace: argparse.Namespace) -> CheckOptions:
    """Convert parsed arguments into the options the check consumes."""
    projects = tuple(
        namespace.projects or [Project(directory=DEFAULT_PROJECT_DIRECTORY)]
    )
    return CheckOptions(
        projects=projects,
        require=namespace.require,
        compare_with=namespace.compare_with,
        staged=namespace.staged,
        allow_empty=namespace.allow_empty,
        skip_new_branch=namespace.skip_new_branch,
        verbose=namespace.verbose,
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Run the fragment check.

    Args:
        argv: Command line arguments, defaulting to ``sys.argv[1:]``.

    Returns:
        ``0`` when the check passes and ``1`` when it fails. Usage errors exit
        with ``2`` by way of argparse.
    """
    namespace = build_parser().parse_args(argv)
    return run_check(
        build_options(namespace),
        cwd=Path.cwd(),
        environment=os.environ,
        stream=sys.stdout,
    )
