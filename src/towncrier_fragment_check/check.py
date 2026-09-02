"""Core logic for the towncrier fragment check.

The module wraps ``towncrier check`` and adds monorepo support, a base-ref
resolution order suited to CI and pre-commit, correct behaviour when invoked
from a subdirectory, and rejection of empty fragment files.

Both git and towncrier are driven as child processes with fixed argument lists,
which is why :mod:`subprocess` is imported here.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

# Process exit codes.
EXIT_OK = 0
EXIT_FAILURE = 1
EXIT_USAGE = 2

# Project defaults.
DEFAULT_PROJECT_DIRECTORY = "."
PROJECT_CONFIG_SEPARATOR = ":"

# Pass rules across projects.
REQUIRE_ANY = "any"
REQUIRE_ALL = "all"
REQUIRE_CHOICES = (REQUIRE_ANY, REQUIRE_ALL)

# Environment variables consulted while resolving the base ref.
ENV_COMPARE_WITH = "TOWNCRIER_COMPARE_WITH"
ENV_GITHUB_BASE_REF = "GITHUB_BASE_REF"
ENV_PRE_COMMIT_FROM_REF = "PRE_COMMIT_FROM_REF"

# Base-ref resolution details.
REMOTE_PREFIX = "origin/"
PATH_SEPARATOR = "/"
FALLBACK_REFS = ("origin/main", "origin/master")

# Markers and patterns found in towncrier's own output.
FOUND_HEADER = "Found:"
FOUND_ENTRY_PATTERN = re.compile(r"^\s*\d+\.\s+(?P<path>\S.*?)\s*$")
NO_DIFF_MARKER = "so no newsfragment required"
NEWS_FILE_SKIPPED_MARKER = "Checks SKIPPED:"
NO_DEFAULT_BRANCH_MARKER = "Could not detect default branch"
GIT_FAILURE_MARKER = "git produced output while failing"
BASE_REF_FAILURE_MARKERS = (NO_DEFAULT_BRANCH_MARKER, GIT_FAILURE_MARKER)

# A pre-push hook receives an all-zero "from" ref for a brand new branch.
NULL_REF_PATTERN = re.compile(r"0+")

# Summary fragments printed once per project.
SUMMARY_FRAGMENT_FOUND = "fragment found ({fragments})"
SUMMARY_EMPTY_FRAGMENT = "empty fragment ({fragments})"
SUMMARY_NO_FRAGMENT = "no fragment"
SUMMARY_NOT_REQUIRED = "no fragment required (no changes against the base ref)"
SUMMARY_NEWS_FILE_UPDATED = "changelog updated, check skipped"
SUMMARY_BASE_REF_UNRESOLVED = "could not resolve a base ref to compare against"
SUMMARY_SEPARATOR = ", "

# Messages written to the output stream.
NOT_A_GIT_REPOSITORY = (
    "{directory} is not inside a git repository, so there is nothing to compare."
)
NEW_BRANCH_SKIP_MESSAGE = (
    "Skipping the fragment check: this branch does not exist on the remote yet."
)
BASE_REF_HELP = (
    "Could not resolve a base ref to compare against. Fetch the base branch "
    "(for example, git fetch origin main) or pass --compare-with BRANCH."
)
NO_FRAGMENT_HELP = (
    "No towncrier changelog fragment was added on this branch. Add one to the "
    "fragment directory of the project you changed."
)
OUTPUT_HEADER = "--- towncrier output for {label} ---"


class GitError(RuntimeError):
    """Raised when a git command needed by the check cannot be completed."""


@dataclass(frozen=True)
class Project:
    """A single towncrier project to check.

    Attributes:
        directory: Project directory, relative to the git toplevel.
        config: Optional towncrier config file, relative to the git toplevel.
    """

    directory: str = DEFAULT_PROJECT_DIRECTORY
    config: str | None = None

    @property
    def label(self) -> str:
        """Return the short name used for this project in summary output."""
        return self.directory


@dataclass(frozen=True)
class CheckOptions:
    """Resolved command line options for a single run of the check."""

    projects: tuple[Project, ...]
    require: str = REQUIRE_ANY
    compare_with: str | None = None
    staged: bool = False
    allow_empty: bool = False
    skip_new_branch: bool = False
    verbose: bool = False


@dataclass(frozen=True)
class ProjectOutcome:
    """The result of checking one project.

    Attributes:
        project: The project that was checked.
        passed: Whether this project satisfied the check on its own.
        summary: One-line, human readable description of the result.
        output: Combined stdout and stderr produced by towncrier.
        base_ref_unresolved: Whether towncrier could not resolve a base ref.
    """

    project: Project
    passed: bool
    summary: str
    output: str
    base_ref_unresolved: bool = False


def _git_executable() -> str:
    """Return the git executable, preferring an absolute path when available."""
    return shutil.which("git") or "git"


def _run_git(arguments: Sequence[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    """Run a git command and capture its output without raising.

    Args:
        arguments: Arguments to pass to git, excluding the executable itself.
        cwd: Directory to run the command in.

    Returns:
        The completed process, including captured stdout and stderr.
    """
    command = [_git_executable(), *arguments]
    # S603: the command is a fixed argument list built from constants,
    # never a shell string, and the executable is resolved with shutil.which.
    return subprocess.run(  # noqa: S603
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


def git_toplevel(start: Path) -> Path:
    """Return the git toplevel directory containing ``start``.

    Args:
        start: Directory to resolve the toplevel from.

    Returns:
        The absolute path of the repository root.

    Raises:
        GitError: If ``start`` is not inside a git repository.
    """
    result = _run_git(["rev-parse", "--show-toplevel"], start)
    if result.returncode != 0:
        raise GitError(NOT_A_GIT_REPOSITORY.format(directory=start))
    return Path(result.stdout.strip())


def ref_exists(ref: str, toplevel: Path) -> bool:
    """Return whether git can resolve ``ref`` in the repository at ``toplevel``."""
    result = _run_git(["rev-parse", "--verify", "--quiet", ref], toplevel)
    return result.returncode == 0


def compare_ref_candidates(
    explicit: str | None, environment: Mapping[str, str]
) -> list[str]:
    """Build the ordered list of base refs to try.

    Args:
        explicit: Value of the ``--compare-with`` flag, if given.
        environment: Environment mapping to read fallback refs from.

    Returns:
        Candidate refs, most specific first.
    """
    candidates = [
        value
        for value in (explicit, environment.get(ENV_COMPARE_WITH))
        if value is not None and value != ""
    ]
    github_base_ref = environment.get(ENV_GITHUB_BASE_REF, "")
    if github_base_ref:
        candidates.append(_qualify_github_base_ref(github_base_ref))
    candidates.extend(FALLBACK_REFS)
    return candidates


def _qualify_github_base_ref(github_base_ref: str) -> str:
    """Prefix a bare ``GITHUB_BASE_REF`` branch name with the origin remote."""
    if PATH_SEPARATOR in github_base_ref:
        return github_base_ref
    return f"{REMOTE_PREFIX}{github_base_ref}"


def resolve_compare_ref(
    explicit: str | None, environment: Mapping[str, str], toplevel: Path
) -> str | None:
    """Return the first resolvable base ref, or ``None`` to use towncrier's default.

    Args:
        explicit: Value of the ``--compare-with`` flag, if given.
        environment: Environment mapping to read fallback refs from.
        toplevel: Repository root used to resolve candidate refs.

    Returns:
        The first candidate git can resolve, or ``None`` when none can be
        resolved, in which case towncrier is left to pick its own default.
    """
    for candidate in compare_ref_candidates(explicit, environment):
        if ref_exists(candidate, toplevel):
            return candidate
    return None


def towncrier_command(
    project: Project, compare_ref: str | None, options: CheckOptions
) -> list[str]:
    """Build the ``towncrier check`` command line for one project.

    Args:
        project: The project to check.
        compare_ref: Resolved base ref, or ``None`` to let towncrier decide.
        options: Options for this run of the check.

    Returns:
        The full argument list, starting with the running interpreter.
    """
    command = [sys.executable, "-m", "towncrier", "check"]
    if compare_ref is not None:
        command += ["--compare-with", compare_ref]
    command += ["--dir", project.directory]
    if project.config is not None:
        command += ["--config", project.config]
    if options.staged:
        command.append("--staged")
    return command


def run_towncrier(
    project: Project, toplevel: Path, compare_ref: str | None, options: CheckOptions
) -> tuple[int, str]:
    """Run ``towncrier check`` for one project from the repository root.

    Running with the repository root as the working directory is what makes the
    check behave correctly when it is invoked from a subdirectory: towncrier
    resolves the repo-root-relative paths reported by git against the process
    working directory.

    Args:
        project: The project to check.
        toplevel: Repository root, used as the working directory.
        compare_ref: Resolved base ref, or ``None`` to let towncrier decide.
        options: Options for this run of the check.

    Returns:
        A tuple of the towncrier exit code and its combined output.
    """
    command = towncrier_command(project, compare_ref, options)
    # S603: the command is a fixed argument list built from constants and
    # the running interpreter, never a shell string.
    result = subprocess.run(  # noqa: S603
        command,
        cwd=toplevel,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode, result.stdout + result.stderr


def parse_found_fragments(output: str) -> list[Path]:
    """Extract the fragment paths towncrier reported under its ``Found:`` header.

    Args:
        output: Combined towncrier output.

    Returns:
        Absolute paths of the fragments found on the branch, in the order
        towncrier printed them.
    """
    fragments: list[Path] = []
    in_found_block = False
    for line in output.splitlines():
        if line.strip() == FOUND_HEADER:
            in_found_block = True
            continue
        match = FOUND_ENTRY_PATTERN.match(line) if in_found_block else None
        if match is not None:
            fragments.append(Path(match.group("path")))
    return fragments


def is_empty_fragment(path: Path) -> bool:
    """Return whether a fragment file exists but holds no non-whitespace text."""
    return path.is_file() and not path.read_text(encoding="utf-8").strip()


def _fragment_label(fragment: Path, project_root: Path) -> str:
    """Return a fragment path relative to its project, when it lives inside it."""
    if fragment.is_relative_to(project_root):
        return fragment.relative_to(project_root).as_posix()
    return fragment.as_posix()


def describe_fragments(fragments: Iterable[Path], project_root: Path) -> str:
    """Render fragment paths relative to their project for the summary line.

    Args:
        fragments: Absolute fragment paths.
        project_root: Absolute path of the project directory.

    Returns:
        A comma separated list of project-relative fragment paths.
    """
    labels = [_fragment_label(fragment, project_root) for fragment in sorted(fragments)]
    return SUMMARY_SEPARATOR.join(labels)


def _passing_outcome(
    project: Project, toplevel: Path, output: str, options: CheckOptions
) -> ProjectOutcome:
    """Interpret a zero exit code from towncrier for one project.

    Args:
        project: The project that was checked.
        toplevel: Repository root.
        output: Combined towncrier output.
        options: Options for this run of the check.

    Returns:
        The outcome for this project, which may still be a failure when an
        empty fragment was found.
    """
    if NEWS_FILE_SKIPPED_MARKER in output:
        return ProjectOutcome(
            project, passed=True, summary=SUMMARY_NEWS_FILE_UPDATED, output=output
        )
    if NO_DIFF_MARKER in output:
        return ProjectOutcome(
            project, passed=True, summary=SUMMARY_NOT_REQUIRED, output=output
        )

    fragments = parse_found_fragments(output)
    project_root = (toplevel / project.directory).resolve()
    if not options.allow_empty:
        empty = [fragment for fragment in fragments if is_empty_fragment(fragment)]
        if empty:
            summary = SUMMARY_EMPTY_FRAGMENT.format(
                fragments=describe_fragments(empty, project_root)
            )
            return ProjectOutcome(project, passed=False, summary=summary, output=output)

    summary = SUMMARY_FRAGMENT_FOUND.format(
        fragments=describe_fragments(fragments, project_root)
    )
    return ProjectOutcome(project, passed=True, summary=summary, output=output)


def check_project(
    project: Project, toplevel: Path, compare_ref: str | None, options: CheckOptions
) -> ProjectOutcome:
    """Run and interpret the towncrier check for a single project.

    Args:
        project: The project to check.
        toplevel: Repository root.
        compare_ref: Resolved base ref, or ``None`` to let towncrier decide.
        options: Options for this run of the check.

    Returns:
        The outcome for this project.
    """
    returncode, output = run_towncrier(project, toplevel, compare_ref, options)
    if returncode == EXIT_OK:
        return _passing_outcome(project, toplevel, output, options)
    if any(marker in output for marker in BASE_REF_FAILURE_MARKERS):
        return ProjectOutcome(
            project,
            passed=False,
            summary=SUMMARY_BASE_REF_UNRESOLVED,
            output=output,
            base_ref_unresolved=True,
        )
    return ProjectOutcome(
        project, passed=False, summary=SUMMARY_NO_FRAGMENT, output=output
    )


def outcomes_pass(outcomes: Sequence[ProjectOutcome], require: str) -> bool:
    """Apply the configured pass rule across every project outcome.

    Args:
        outcomes: One outcome per configured project.
        require: Either ``all`` or ``any``.

    Returns:
        Whether the overall check passes.
    """
    if require == REQUIRE_ALL:
        return all(outcome.passed for outcome in outcomes)
    return any(outcome.passed for outcome in outcomes)


def is_new_branch_push(environment: Mapping[str, str]) -> bool:
    """Return whether pre-commit reported an all-zero "from" ref.

    An all-zero ref means the branch being pushed does not exist on the remote
    yet, so there is no meaningful diff for a pre-push hook to inspect.

    Args:
        environment: Environment mapping to read ``PRE_COMMIT_FROM_REF`` from.

    Returns:
        Whether the current push creates a new remote branch.
    """
    from_ref = environment.get(ENV_PRE_COMMIT_FROM_REF, "")
    return bool(from_ref) and NULL_REF_PATTERN.fullmatch(from_ref) is not None


def _emit(stream: TextIO, text: str) -> None:
    """Write one line of output to the given stream."""
    stream.write(f"{text}\n")


def _report(
    outcomes: Sequence[ProjectOutcome],
    options: CheckOptions,
    stream: TextIO,
    *,
    passed: bool,
) -> None:
    """Print the per-project summary and, when useful, towncrier's own output.

    The summary is always printed, one line per project. Towncrier's own output
    is echoed only when the overall check failed, so that the user can see what
    towncrier saw, or when ``--verbose`` asks for it unconditionally.

    Args:
        outcomes: One outcome per configured project.
        options: Options for this run of the check.
        stream: Stream to write the report to.
        passed: Whether the configured pass rule was satisfied.
    """
    for outcome in outcomes:
        _emit(stream, f"{outcome.project.label}: {outcome.summary}")

    if passed and not options.verbose:
        return

    for outcome in outcomes:
        if outcome.output.strip():
            _emit(stream, "")
            _emit(stream, OUTPUT_HEADER.format(label=outcome.project.label))
            _emit(stream, outcome.output.rstrip())


def _finalize(
    outcomes: Sequence[ProjectOutcome], stream: TextIO, *, passed: bool
) -> int:
    """Emit closing guidance and return the process exit code.

    Args:
        outcomes: One outcome per configured project.
        stream: Stream to write guidance to.
        passed: Whether the configured pass rule was satisfied.

    Returns:
        The process exit code.
    """
    if any(outcome.base_ref_unresolved for outcome in outcomes):
        _emit(stream, BASE_REF_HELP)
        return EXIT_FAILURE
    if not passed:
        _emit(stream, NO_FRAGMENT_HELP)
        return EXIT_FAILURE
    return EXIT_OK


def run_check(
    options: CheckOptions,
    *,
    cwd: Path,
    environment: Mapping[str, str],
    stream: TextIO,
) -> int:
    """Run the fragment check for every configured project.

    Args:
        options: Options for this run of the check.
        cwd: Directory the check was invoked from.
        environment: Environment mapping used for base-ref resolution.
        stream: Stream to write the report to.

    Returns:
        ``EXIT_OK`` when the check passes, ``EXIT_FAILURE`` otherwise.
    """
    if options.skip_new_branch and is_new_branch_push(environment):
        _emit(stream, NEW_BRANCH_SKIP_MESSAGE)
        return EXIT_OK

    try:
        toplevel = git_toplevel(cwd)
    except GitError as error:
        _emit(stream, str(error))
        return EXIT_FAILURE

    compare_ref = resolve_compare_ref(options.compare_with, environment, toplevel)
    outcomes = [
        check_project(project, toplevel, compare_ref, options)
        for project in options.projects
    ]
    passed = outcomes_pass(outcomes, options.require)
    _report(outcomes, options, stream, passed=passed)
    return _finalize(outcomes, stream, passed=passed)
