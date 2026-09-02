"""Unit tests for the pure helpers in :mod:`towncrier_fragment_check.check`."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.conftest import (
    MAIN_BRANCH,
    NON_NULL_REF,
    NULL_REF,
    GitRepository,
)
from towncrier_fragment_check.check import (
    ENV_COMPARE_WITH,
    ENV_GITHUB_BASE_REF,
    ENV_PRE_COMMIT_FROM_REF,
    FALLBACK_REFS,
    compare_ref_candidates,
    describe_fragments,
    is_new_branch_push,
    parse_found_fragments,
    resolve_compare_ref,
)

RELEASE_BRANCH_REF = "release/1.x"
FRAGMENT_ONE = "/repo/packages/api/changes/1.added"
FRAGMENT_TWO = "/repo/packages/api/changes/2.fixed"
API_ROOT = Path("/repo/packages/api")


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


def test_parse_found_fragments_reads_the_found_block() -> None:
    """Only the numbered entries after 'Found:' count, not the earlier file list."""
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


def test_describe_fragments_uses_project_relative_paths() -> None:
    """Fragment paths are shortened relative to their own project."""
    described = describe_fragments([Path(FRAGMENT_TWO), Path(FRAGMENT_ONE)], API_ROOT)

    assert described == "changes/1.added, changes/2.fixed"


def test_describe_fragments_falls_back_to_absolute_paths() -> None:
    """A fragment outside the project directory keeps its absolute path."""
    outside = Path("/elsewhere/changes/9.added")

    assert describe_fragments([outside], API_ROOT) == outside.as_posix()


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
