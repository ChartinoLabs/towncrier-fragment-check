"""Shared fixtures for the towncrier-fragment-check test suite.

The fixtures build real git repositories in ``tmp_path`` so that the tests
exercise the same git and towncrier behaviour the tool sees in practice.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

import pytest

from towncrier_fragment_check.cli import main

MAIN_BRANCH = "main"
FEATURE_BRANCH = "feature"
GIT_USER_NAME = "Fragment Check Tests"
GIT_USER_EMAIL = "tests@example.com"
REMOTE_NAME = "origin"
NULL_REF = "0" * 40
NON_NULL_REF = "1" * 40

ROOT_PROJECT = "."
API_PROJECT = "packages/api"
WEB_PROJECT = "apps/web"

PYPROJECT_NAME = "pyproject.toml"
TOWNCRIER_CONFIG_NAME = "towncrier.toml"
CHANGELOG_NAME = "CHANGELOG.md"
FRAGMENT_DIRECTORY = "changes"
FRAGMENT_KEEP_FILE = ".gitkeep"

CHANGELOG_CONTENT = "# Changelog\n"
FRAGMENT_CONTENT = "Added a thing.\n"
EMPTY_FRAGMENT_CONTENT = "   \n\t\n"
ADDED_FRAGMENT = "123.added"

TOWNCRIER_CONFIG = """\
[tool.towncrier]
directory = "changes"
filename = "CHANGELOG.md"

[[tool.towncrier.type]]
directory = "added"
name = "Added"
showcontent = true

[[tool.towncrier.type]]
directory = "fixed"
name = "Fixed"
showcontent = true
"""

# Environment variables the tool reads. They are cleared before every CLI run so
# that the suite behaves the same locally and inside a CI pull request build.
MANAGED_ENVIRONMENT_VARIABLES = (
    "TOWNCRIER_COMPARE_WITH",
    "GITHUB_BASE_REF",
    "PRE_COMMIT_FROM_REF",
)


def _git_executable() -> str:
    """Return the git executable, preferring an absolute path when available."""
    return shutil.which("git") or "git"


@dataclass(frozen=True)
class GitRepository:
    """A throwaway git repository used by the tests.

    Attributes:
        path: Absolute path of the working tree.
    """

    path: Path

    def git(self, *arguments: str) -> str:
        """Run a git command in the repository and return its stdout."""
        command = [_git_executable(), *arguments]
        # S603: a fixed argument list, never a shell string.
        result = subprocess.run(  # noqa: S603
            command,
            cwd=self.path,
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout

    def write(self, relative_path: str, content: str) -> Path:
        """Write a file inside the repository, creating parent directories."""
        target = self.path / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return target

    def project_path(self, directory: str) -> Path:
        """Return the absolute path of a project directory."""
        return self.path / directory

    def create_project(self, directory: str, config_name: str = PYPROJECT_NAME) -> Path:
        """Create a towncrier project inside the repository.

        Args:
            directory: Project directory relative to the repository root.
            config_name: Name of the towncrier config file to write.

        Returns:
            The path of the written config file, relative to the repository.
        """
        base = Path(directory)
        config_path = base / config_name
        self.write(str(config_path), TOWNCRIER_CONFIG)
        self.write(str(base / CHANGELOG_NAME), CHANGELOG_CONTENT)
        self.write(str(base / FRAGMENT_DIRECTORY / FRAGMENT_KEEP_FILE), "")
        return config_path

    def add_fragment(
        self,
        directory: str = ROOT_PROJECT,
        name: str = ADDED_FRAGMENT,
        content: str = FRAGMENT_CONTENT,
    ) -> Path:
        """Write a changelog fragment into a project's fragment directory."""
        return self.write(
            str(Path(directory) / FRAGMENT_DIRECTORY / name),
            content,
        )

    def commit(self, message: str) -> None:
        """Stage everything in the working tree and record a commit."""
        self.git("add", "-A")
        self.git("commit", "-m", message)

    def checkout(self, branch: str, *, create: bool = False) -> None:
        """Check out a branch, optionally creating it first."""
        if create:
            self.git("checkout", "-b", branch)
        else:
            self.git("checkout", branch)

    def add_remote(self, remote_path: Path) -> None:
        """Create a bare remote, register it as origin, and push ``main``."""
        bare = GitRepository(remote_path)
        bare.path.mkdir(parents=True, exist_ok=True)
        bare.git("init", "--bare", "-b", MAIN_BRANCH, ".")
        self.git("remote", "add", REMOTE_NAME, str(remote_path))
        self.git("push", REMOTE_NAME, MAIN_BRANCH)


@dataclass(frozen=True)
class CliResult:
    """The captured result of an in-process CLI run.

    Attributes:
        exit_code: The integer the CLI returned.
        output: Everything the CLI wrote to stdout.
    """

    exit_code: int
    output: str


@pytest.fixture
def repo(tmp_path: Path) -> GitRepository:
    """Return an initialised but otherwise empty git repository."""
    repository = GitRepository(tmp_path / "repo")
    repository.path.mkdir(parents=True)
    repository.git("init", "-b", MAIN_BRANCH, ".")
    repository.git("config", "user.name", GIT_USER_NAME)
    repository.git("config", "user.email", GIT_USER_EMAIL)
    return repository


@pytest.fixture
def single_project_repo(repo: GitRepository) -> GitRepository:
    """Return a repository with one root project, checked out on a branch."""
    repo.create_project(ROOT_PROJECT)
    repo.commit("Initial commit")
    repo.checkout(FEATURE_BRANCH, create=True)
    return repo


@pytest.fixture
def monorepo(repo: GitRepository) -> GitRepository:
    """Return a repository with two projects, checked out on a branch."""
    repo.create_project(API_PROJECT)
    repo.create_project(WEB_PROJECT, config_name=TOWNCRIER_CONFIG_NAME)
    repo.commit("Initial commit")
    repo.checkout(FEATURE_BRANCH, create=True)
    return repo


@dataclass
class CliRunner:
    """Callable helper that runs the CLI in-process from a chosen directory."""

    monkeypatch: pytest.MonkeyPatch
    read_output: Callable[[], str]

    def __call__(
        self,
        arguments: Iterable[str],
        *,
        cwd: Path,
        environment: Mapping[str, str] | None = None,
    ) -> CliResult:
        """Run the CLI and capture its exit code and stdout."""
        self.monkeypatch.chdir(cwd)
        for name in MANAGED_ENVIRONMENT_VARIABLES:
            self.monkeypatch.delenv(name, raising=False)
        for name, value in (environment or {}).items():
            self.monkeypatch.setenv(name, value)
        exit_code = main(list(arguments))
        return CliResult(exit_code=exit_code, output=self.read_output())


@pytest.fixture
def run_cli(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> CliRunner:
    """Return a helper that runs the CLI in-process and captures its output."""
    return CliRunner(
        monkeypatch=monkeypatch, read_output=lambda: capsys.readouterr().out
    )
