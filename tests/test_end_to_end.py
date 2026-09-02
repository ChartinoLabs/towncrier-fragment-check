"""End to end tests that run the CLI against real git repositories."""

from __future__ import annotations

from pathlib import Path

from tests.conftest import (
    ADDED_FRAGMENT,
    API_PROJECT,
    CHANGELOG_NAME,
    EMPTY_FRAGMENT_CONTENT,
    FEATURE_BRANCH,
    MAIN_BRANCH,
    NON_NULL_REF,
    NULL_REF,
    TOWNCRIER_CONFIG_NAME,
    WEB_PROJECT,
    CliRunner,
    GitRepository,
)
from towncrier_fragment_check.check import (
    BASE_REF_HELP,
    ENV_GITHUB_BASE_REF,
    ENV_PRE_COMMIT_FROM_REF,
    EXIT_FAILURE,
    EXIT_OK,
    NEW_BRANCH_SKIP_MESSAGE,
    NO_FRAGMENT_HELP,
    NOT_A_GIT_REPOSITORY,
)

COMPARE_WITH_MAIN = ["--compare-with", MAIN_BRANCH]
TOWNCRIER_NO_FRAGMENTS = "No new newsfragments found on this branch."
SOURCE_FILE = "module.py"
SOURCE_CONTENT = "VALUE = 1\n"


def test_fragment_added_passes(
    single_project_repo: GitRepository, run_cli: CliRunner
) -> None:
    """A branch that adds a fragment passes and the fragment is named."""
    single_project_repo.add_fragment()
    single_project_repo.commit("Add fragment")

    result = run_cli(COMPARE_WITH_MAIN, cwd=single_project_repo.path)

    assert result.exit_code == EXIT_OK
    assert f".: fragment found (changes/{ADDED_FRAGMENT})" in result.output


def test_missing_fragment_fails_and_echoes_towncrier(
    single_project_repo: GitRepository, run_cli: CliRunner
) -> None:
    """A branch with no fragment fails and towncrier's output is echoed."""
    single_project_repo.write(SOURCE_FILE, SOURCE_CONTENT)
    single_project_repo.commit("Add code")

    result = run_cli(COMPARE_WITH_MAIN, cwd=single_project_repo.path)

    assert result.exit_code == EXIT_FAILURE
    assert ".: no fragment" in result.output
    assert TOWNCRIER_NO_FRAGMENTS in result.output
    assert NO_FRAGMENT_HELP in result.output


def test_verbose_echoes_output_on_success(
    single_project_repo: GitRepository, run_cli: CliRunner
) -> None:
    """--verbose prints towncrier's output even when the check passes."""
    single_project_repo.add_fragment()
    single_project_repo.commit("Add fragment")

    quiet = run_cli(COMPARE_WITH_MAIN, cwd=single_project_repo.path)
    verbose = run_cli([*COMPARE_WITH_MAIN, "--verbose"], cwd=single_project_repo.path)

    assert "Looking at these files:" not in quiet.output
    assert "Looking at these files:" in verbose.output


def test_passes_when_run_from_a_subdirectory(
    monorepo: GitRepository, run_cli: CliRunner
) -> None:
    """The check works from inside a project directory, not just the root."""
    monorepo.add_fragment(API_PROJECT)
    monorepo.commit("Add fragment")

    result = run_cli(
        [*COMPARE_WITH_MAIN, "--project", API_PROJECT],
        cwd=monorepo.project_path(API_PROJECT),
    )

    assert result.exit_code == EXIT_OK
    assert f"{API_PROJECT}: fragment found (changes/{ADDED_FRAGMENT})" in result.output


def test_monorepo_any_passes_with_one_fragment(
    monorepo: GitRepository, run_cli: CliRunner
) -> None:
    """With the default 'any' rule, one project carrying a fragment is enough."""
    monorepo.add_fragment(API_PROJECT)
    monorepo.commit("Add fragment")

    result = run_cli(
        [
            *COMPARE_WITH_MAIN,
            "--project",
            API_PROJECT,
            "--project",
            f"{WEB_PROJECT}:{WEB_PROJECT}/{TOWNCRIER_CONFIG_NAME}",
        ],
        cwd=monorepo.path,
    )

    assert result.exit_code == EXIT_OK
    assert f"{API_PROJECT}: fragment found" in result.output
    assert f"{WEB_PROJECT}: no fragment" in result.output
    # A project that did not carry a fragment is summarised, but its towncrier
    # output is not echoed while the overall run still passes.
    assert TOWNCRIER_NO_FRAGMENTS not in result.output


def test_monorepo_all_fails_with_one_fragment(
    monorepo: GitRepository, run_cli: CliRunner
) -> None:
    """With '--require all', a project without a fragment fails the run."""
    monorepo.add_fragment(API_PROJECT)
    monorepo.commit("Add fragment")

    result = run_cli(
        [
            *COMPARE_WITH_MAIN,
            "--project",
            API_PROJECT,
            "--project",
            WEB_PROJECT,
            "--require",
            "all",
        ],
        cwd=monorepo.path,
    )

    assert result.exit_code == EXIT_FAILURE


def test_monorepo_all_passes_with_every_fragment(
    monorepo: GitRepository, run_cli: CliRunner
) -> None:
    """With '--require all', a fragment in every project passes."""
    monorepo.add_fragment(API_PROJECT)
    monorepo.add_fragment(WEB_PROJECT)
    monorepo.commit("Add fragments")

    result = run_cli(
        [
            *COMPARE_WITH_MAIN,
            "--project",
            API_PROJECT,
            "--project",
            WEB_PROJECT,
            "--require",
            "all",
        ],
        cwd=monorepo.path,
    )

    assert result.exit_code == EXIT_OK


def test_staged_fragment_needs_the_staged_flag(
    single_project_repo: GitRepository, run_cli: CliRunner
) -> None:
    """A staged but uncommitted fragment only counts with --staged."""
    single_project_repo.write(SOURCE_FILE, SOURCE_CONTENT)
    single_project_repo.commit("Add code")
    single_project_repo.add_fragment()
    single_project_repo.git("add", "-A")

    without_flag = run_cli(COMPARE_WITH_MAIN, cwd=single_project_repo.path)
    with_flag = run_cli([*COMPARE_WITH_MAIN, "--staged"], cwd=single_project_repo.path)

    assert without_flag.exit_code == EXIT_FAILURE
    assert with_flag.exit_code == EXIT_OK


def test_empty_fragment_fails(
    single_project_repo: GitRepository, run_cli: CliRunner
) -> None:
    """A whitespace-only fragment fails, and --allow-empty opts out."""
    single_project_repo.add_fragment(content=EMPTY_FRAGMENT_CONTENT)
    single_project_repo.commit("Add empty fragment")

    strict = run_cli(COMPARE_WITH_MAIN, cwd=single_project_repo.path)
    permissive = run_cli(
        [*COMPARE_WITH_MAIN, "--allow-empty"], cwd=single_project_repo.path
    )

    assert strict.exit_code == EXIT_FAILURE
    assert f".: empty fragment (changes/{ADDED_FRAGMENT})" in strict.output
    assert permissive.exit_code == EXIT_OK


def test_changelog_edit_skips_the_check(
    single_project_repo: GitRepository, run_cli: CliRunner
) -> None:
    """Editing the news file itself, as a release commit does, passes."""
    single_project_repo.write(CHANGELOG_NAME, "# Changelog\n\n## 1.0.0\n")
    single_project_repo.commit("Release 1.0.0")

    result = run_cli(COMPARE_WITH_MAIN, cwd=single_project_repo.path)

    assert result.exit_code == EXIT_OK
    assert ".: changelog updated, check skipped" in result.output


def test_no_diff_against_base_passes(
    single_project_repo: GitRepository, run_cli: CliRunner
) -> None:
    """Sitting on the base branch, with no diff, requires no fragment."""
    single_project_repo.checkout(MAIN_BRANCH)

    result = run_cli(COMPARE_WITH_MAIN, cwd=single_project_repo.path)

    assert result.exit_code == EXIT_OK
    assert ".: no fragment required" in result.output


def test_github_base_ref_is_prefixed_with_origin(
    single_project_repo: GitRepository, tmp_path: Path, run_cli: CliRunner
) -> None:
    """A bare GITHUB_BASE_REF branch name resolves against the origin remote."""
    single_project_repo.checkout(MAIN_BRANCH)
    single_project_repo.add_remote(tmp_path / "remote.git")
    single_project_repo.checkout(FEATURE_BRANCH)
    single_project_repo.add_fragment()
    single_project_repo.commit("Add fragment")

    result = run_cli(
        [],
        cwd=single_project_repo.path,
        environment={ENV_GITHUB_BASE_REF: MAIN_BRANCH},
    )

    assert result.exit_code == EXIT_OK


def test_origin_main_is_the_final_fallback(
    single_project_repo: GitRepository, tmp_path: Path, run_cli: CliRunner
) -> None:
    """With no flag and no environment, origin/main is used when it exists."""
    single_project_repo.checkout(MAIN_BRANCH)
    single_project_repo.add_remote(tmp_path / "remote.git")
    single_project_repo.checkout(FEATURE_BRANCH)
    single_project_repo.write(SOURCE_FILE, SOURCE_CONTENT)
    single_project_repo.commit("Add code")

    result = run_cli([], cwd=single_project_repo.path)

    assert result.exit_code == EXIT_FAILURE
    assert TOWNCRIER_NO_FRAGMENTS in result.output


def test_unresolvable_base_ref_reports_guidance(
    single_project_repo: GitRepository, run_cli: CliRunner
) -> None:
    """When no candidate ref resolves, the run fails with actionable guidance."""
    single_project_repo.add_fragment()
    single_project_repo.commit("Add fragment")

    result = run_cli(["--compare-with", "does-not-exist"], cwd=single_project_repo.path)

    assert result.exit_code == EXIT_FAILURE
    assert ".: could not resolve a base ref" in result.output
    assert BASE_REF_HELP in result.output


def test_skip_new_branch_with_null_from_ref(
    single_project_repo: GitRepository, run_cli: CliRunner
) -> None:
    """--skip-new-branch exits 0 when pre-commit reports an all-zero from ref."""
    single_project_repo.write(SOURCE_FILE, SOURCE_CONTENT)
    single_project_repo.commit("Add code")

    result = run_cli(
        [*COMPARE_WITH_MAIN, "--skip-new-branch"],
        cwd=single_project_repo.path,
        environment={ENV_PRE_COMMIT_FROM_REF: NULL_REF},
    )

    assert result.exit_code == EXIT_OK
    assert NEW_BRANCH_SKIP_MESSAGE in result.output


def test_skip_new_branch_with_real_from_ref(
    single_project_repo: GitRepository, run_cli: CliRunner
) -> None:
    """--skip-new-branch has no effect when the from ref is a real sha."""
    single_project_repo.write(SOURCE_FILE, SOURCE_CONTENT)
    single_project_repo.commit("Add code")

    result = run_cli(
        [*COMPARE_WITH_MAIN, "--skip-new-branch"],
        cwd=single_project_repo.path,
        environment={ENV_PRE_COMMIT_FROM_REF: NON_NULL_REF},
    )

    assert result.exit_code == EXIT_FAILURE


def test_outside_a_git_repository(tmp_path: Path, run_cli: CliRunner) -> None:
    """Running outside a git repository fails with a clear message."""
    workspace = tmp_path / "not-a-repo"
    workspace.mkdir()

    result = run_cli([], cwd=workspace)

    assert result.exit_code == EXIT_FAILURE
    assert NOT_A_GIT_REPOSITORY.format(directory=workspace) in result.output
