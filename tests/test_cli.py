"""Tests for argument parsing and the console script entry point."""

from __future__ import annotations

import argparse
import subprocess
import sys

import pytest

from tests.conftest import API_PROJECT, WEB_PROJECT
from towncrier_fragment_check import __version__
from towncrier_fragment_check.check import (
    DEFAULT_PROJECT_DIRECTORY,
    EXIT_USAGE,
    Project,
)
from towncrier_fragment_check.cli import (
    PROGRAM_NAME,
    build_options,
    build_parser,
    main,
    parse_project,
)

WEB_CONFIG = f"{WEB_PROJECT}/towncrier.toml"


@pytest.mark.parametrize("value", ["", "   ", ":config.toml", f"{API_PROJECT}:"])
def test_parse_project_rejects_incomplete_values(value: str) -> None:
    """A missing directory or a dangling separator is a usage error."""
    with pytest.raises(argparse.ArgumentTypeError):
        parse_project(value)


def test_default_options_check_the_repository_root() -> None:
    """With no flags, a single project at the repository root is checked."""
    options = build_options(build_parser().parse_args([]))

    assert options.projects == (Project(directory=DEFAULT_PROJECT_DIRECTORY),)


def test_repeated_project_flags_are_collected() -> None:
    """--project can be given more than once, in order."""
    namespace = build_parser().parse_args(
        ["--project", API_PROJECT, "--project", f"{WEB_PROJECT}:{WEB_CONFIG}"]
    )

    assert build_options(namespace).projects == (
        Project(directory=API_PROJECT),
        Project(directory=WEB_PROJECT, config=WEB_CONFIG),
    )


@pytest.mark.parametrize(
    "arguments",
    [["--require", "some"], ["--unknown-flag"], ["--project", ":config.toml"]],
)
def test_usage_errors_exit_with_two(arguments: list[str]) -> None:
    """Invalid arguments, including a malformed --project, exit with the usage code."""
    with pytest.raises(SystemExit) as excinfo:
        main(arguments)

    assert excinfo.value.code == EXIT_USAGE


def test_runnable_as_a_module() -> None:
    """The package exposes a working `python -m towncrier_fragment_check` entry."""
    command = [sys.executable, "-m", "towncrier_fragment_check", "--version"]
    # S603: a fixed argument list built from the running interpreter.
    result = subprocess.run(  # noqa: S603
        command, capture_output=True, text=True, check=True
    )

    assert result.stdout.strip() == f"{PROGRAM_NAME} {__version__}"
