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
    REQUIRE_ANY,
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


def test_parse_project_directory_only() -> None:
    """A bare directory becomes a project with no explicit config."""
    assert parse_project(API_PROJECT) == Project(directory=API_PROJECT, config=None)


def test_parse_project_with_config() -> None:
    """A 'DIR:CONFIG' value carries the config path through."""
    parsed = parse_project(f"{WEB_PROJECT}:{WEB_CONFIG}")

    assert parsed == Project(directory=WEB_PROJECT, config=WEB_CONFIG)


@pytest.mark.parametrize("value", ["", "   ", ":config.toml", f"{API_PROJECT}:"])
def test_parse_project_rejects_incomplete_values(value: str) -> None:
    """A missing directory or a dangling separator is a usage error."""
    with pytest.raises(argparse.ArgumentTypeError):
        parse_project(value)


def test_default_options_check_the_repository_root() -> None:
    """With no flags, a single project at the repository root is checked."""
    options = build_options(build_parser().parse_args([]))

    assert options.projects == (Project(directory=DEFAULT_PROJECT_DIRECTORY),)
    assert options.require == REQUIRE_ANY
    assert options.compare_with is None
    assert not options.staged
    assert not options.allow_empty
    assert not options.skip_new_branch
    assert not options.verbose


def test_repeated_project_flags_are_collected() -> None:
    """--project can be given more than once, in order."""
    namespace = build_parser().parse_args(
        ["--project", API_PROJECT, "--project", f"{WEB_PROJECT}:{WEB_CONFIG}"]
    )

    assert build_options(namespace).projects == (
        Project(directory=API_PROJECT),
        Project(directory=WEB_PROJECT, config=WEB_CONFIG),
    )


def test_flags_are_forwarded_to_the_options() -> None:
    """Every boolean flag reaches the resolved options."""
    namespace = build_parser().parse_args(
        [
            "--require",
            "all",
            "--compare-with",
            "origin/develop",
            "--staged",
            "--allow-empty",
            "--skip-new-branch",
            "--verbose",
        ]
    )
    options = build_options(namespace)

    assert options.require == "all"
    assert options.compare_with == "origin/develop"
    assert options.staged
    assert options.allow_empty
    assert options.skip_new_branch
    assert options.verbose


def test_version_is_printed(capsys: pytest.CaptureFixture[str]) -> None:
    """--version prints the program name and version, then exits cleanly."""
    with pytest.raises(SystemExit) as excinfo:
        main(["--version"])

    assert excinfo.value.code == 0
    assert capsys.readouterr().out.strip() == f"{PROGRAM_NAME} {__version__}"


@pytest.mark.parametrize("arguments", [["--require", "some"], ["--unknown-flag"]])
def test_usage_errors_exit_with_two(arguments: list[str]) -> None:
    """Invalid arguments exit with the usage exit code."""
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
