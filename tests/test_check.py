"""Unit tests for the pure helpers in :mod:`towncrier_fragment_check.check`."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from tests.conftest import (
    ADDED_FRAGMENT,
    FEATURE_BRANCH,
    MAIN_BRANCH,
    NON_NULL_REF,
    NULL_REF,
    ROOT_PROJECT,
    GitRepository,
)
from towncrier_fragment_check.check import (
    ENV_COMPARE_WITH,
    ENV_GITHUB_BASE_REF,
    ENV_PRE_COMMIT_FROM_REF,
    FALLBACK_REFS,
    REQUIRE_ALL,
    REQUIRE_ANY,
    CheckOptions,
    GitError,
    Project,
    ProjectOutcome,
    compare_ref_candidates,
    describe_fragments,
    git_toplevel,
    is_empty_fragment,
    is_new_branch_push,
    outcomes_pass,
    parse_found_fragments,
    ref_exists,
    resolve_compare_ref,
    towncrier_command,
)

RELEASE_BRANCH_REF = "release/1.x"
FRAGMENT_ONE = "/repo/packages/api/changes/1.added"
FRAGMENT_TWO = "/repo/packages/api/changes/2.fixed"
API_ROOT = Path("/repo/packages/api")


def _options(*, staged: bool = False) -> CheckOptions:
    """Build a CheckOptions instance for a single root project."""
    return CheckOptions(projects=(Project(),), staged=staged)


def _outcome(*, passed: bool) -> ProjectOutcome:
    """Build a minimal outcome with the given pass state."""
    return ProjectOutcome(Project(), passed=passed, summary="summary", output="")


def test_project_label_is_the_directory() -> None:
    """A project reports its directory as its summary label."""
    assert Project(directory="packages/api").label == "packages/api"


@pytest.mark.parametrize(
    ("explicit", "environment", "expected_head"),
    [
        ("flag", {ENV_COMPARE_WITH: "env"}, ["flag", "env"]),
        (None, {ENV_COMPARE_WITH: "env"}, ["env"]),
        (None, {ENV_GITHUB_BASE_REF: MAIN_BRANCH}, ["origin/main"]),
        (None, {ENV_GITHUB_BASE_REF: RELEASE_BRANCH_REF}, [RELEASE_BRANCH_REF]),
        (None, {}, []),
        (None, {ENV_COMPARE_WITH: ""}, []),
    ],
)
def test_compare_ref_candidate_order(
    explicit: str | None,
    environment: dict[str, str],
    expected_head: list[str],
) -> None:
    """Candidates are ordered flag, environment, then the remote fallbacks."""
    candidates = compare_ref_candidates(explicit, environment)

    assert candidates == [*expected_head, *FALLBACK_REFS]


def test_resolve_compare_ref_prefers_the_first_resolvable_candidate(
    single_project_repo: GitRepository,
) -> None:
    """An unresolvable candidate is skipped in favour of the next one."""
    resolved = resolve_compare_ref(
        "does-not-exist",
        {ENV_COMPARE_WITH: MAIN_BRANCH},
        single_project_repo.path,
    )

    assert resolved == MAIN_BRANCH


def test_resolve_compare_ref_returns_none_when_nothing_resolves(
    single_project_repo: GitRepository,
) -> None:
    """Falling through every candidate defers to towncrier's own default."""
    assert resolve_compare_ref(None, {}, single_project_repo.path) is None


def test_ref_exists(single_project_repo: GitRepository) -> None:
    """Existing refs resolve and missing refs do not."""
    assert ref_exists(FEATURE_BRANCH, single_project_repo.path)
    assert not ref_exists("does-not-exist", single_project_repo.path)


def test_git_toplevel_outside_a_repository(tmp_path: Path) -> None:
    """Resolving a toplevel outside a repository raises GitError."""
    with pytest.raises(GitError):
        git_toplevel(tmp_path)


def test_git_toplevel_from_a_subdirectory(monorepo: GitRepository) -> None:
    """The toplevel is found from anywhere inside the working tree."""
    subdirectory = monorepo.project_path("packages/api")

    assert git_toplevel(subdirectory) == monorepo.path


def test_parse_found_fragments_reads_the_found_block() -> None:
    """Numbered entries under the 'Found:' header are collected in order."""
    output = (
        "Looking at these files:\n"
        "----\n"
        f"1. {FRAGMENT_ONE}\n"
        "----\n"
        "Found:\n"
        f"1. {FRAGMENT_ONE}\n"
        f"2. {FRAGMENT_TWO}\n"
    )

    assert parse_found_fragments(output) == [Path(FRAGMENT_ONE), Path(FRAGMENT_TWO)]


def test_parse_found_fragments_stops_at_the_first_other_line() -> None:
    """Trailing prose after the found block is not treated as a fragment."""
    output = f"Found:\n1. {FRAGMENT_ONE}\nSomething else entirely\n2. {FRAGMENT_TWO}\n"

    assert parse_found_fragments(output) == [Path(FRAGMENT_ONE)]


def test_parse_found_fragments_without_a_header() -> None:
    """Output with no 'Found:' header yields no fragments."""
    assert parse_found_fragments("No new newsfragments found on this branch.") == []


@pytest.mark.parametrize(
    ("content", "expected"),
    [("", True), ("   \n\t\n", True), ("A note.\n", False)],
)
def test_is_empty_fragment(
    tmp_path: Path,
    content: str,
    expected: bool,  # noqa: FBT001
) -> None:
    """Fragments holding no non-whitespace text are reported as empty."""
    fragment = tmp_path / ADDED_FRAGMENT
    fragment.write_text(content, encoding="utf-8")

    assert is_empty_fragment(fragment) is expected


def test_is_empty_fragment_ignores_missing_files(tmp_path: Path) -> None:
    """A path that is not a file is never reported as an empty fragment."""
    assert is_empty_fragment(tmp_path / "missing") is False


def test_describe_fragments_uses_project_relative_paths() -> None:
    """Fragment paths are shortened relative to their own project."""
    described = describe_fragments([Path(FRAGMENT_TWO), Path(FRAGMENT_ONE)], API_ROOT)

    assert described == "changes/1.added, changes/2.fixed"


def test_describe_fragments_falls_back_to_absolute_paths() -> None:
    """A fragment outside the project directory keeps its absolute path."""
    outside = Path("/elsewhere/changes/9.added")

    assert describe_fragments([outside], API_ROOT) == outside.as_posix()


@pytest.mark.parametrize(
    ("require", "passes", "expected"),
    [
        (REQUIRE_ANY, [True, False], True),
        (REQUIRE_ANY, [False, False], False),
        (REQUIRE_ALL, [True, False], False),
        (REQUIRE_ALL, [True, True], True),
    ],
)
def test_outcomes_pass(
    require: str,
    passes: list[bool],
    expected: bool,  # noqa: FBT001
) -> None:
    """The pass rule is applied across every project outcome."""
    outcomes = [_outcome(passed=passed) for passed in passes]

    assert outcomes_pass(outcomes, require) is expected


@pytest.mark.parametrize(
    ("environment", "expected"),
    [
        ({}, False),
        ({ENV_PRE_COMMIT_FROM_REF: NULL_REF}, True),
        ({ENV_PRE_COMMIT_FROM_REF: NON_NULL_REF}, False),
        ({ENV_PRE_COMMIT_FROM_REF: ""}, False),
    ],
)
def test_is_new_branch_push(
    environment: dict[str, str],
    expected: bool,  # noqa: FBT001
) -> None:
    """An all-zero PRE_COMMIT_FROM_REF marks a branch new to the remote."""
    assert is_new_branch_push(environment) is expected


def test_towncrier_command_minimal() -> None:
    """Without a base ref or extra flags, only the project directory is passed."""
    command = towncrier_command(Project(), None, _options())

    assert command == [
        sys.executable,
        "-m",
        "towncrier",
        "check",
        "--dir",
        ROOT_PROJECT,
    ]


def test_towncrier_command_with_every_option() -> None:
    """The base ref, config path, and staged flag are all forwarded."""
    project = Project(directory="apps/web", config="apps/web/towncrier.toml")

    command = towncrier_command(project, MAIN_BRANCH, _options(staged=True))

    assert command == [
        sys.executable,
        "-m",
        "towncrier",
        "check",
        "--compare-with",
        MAIN_BRANCH,
        "--dir",
        "apps/web",
        "--config",
        "apps/web/towncrier.toml",
        "--staged",
    ]
