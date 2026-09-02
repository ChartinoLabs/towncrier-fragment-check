# towncrier-fragment-check

A [pre-commit](https://pre-commit.com) hook and CLI that fails when a branch does
not add a [towncrier](https://towncrier.readthedocs.io) changelog fragment. It
wraps `towncrier check` and fills the gaps around it.

## What it adds to `towncrier check`

- **Monorepos.** Check several towncrier projects in one run with `--project`,
  passing when any one of them has a fragment (`--require any`) or only when
  they all do (`--require all`).
- **Subdirectories.** `towncrier check` resolves git's repository-relative paths
  against the working directory, so it never matches when run inside
  `packages/api/`. This tool always runs it from the git toplevel.
- **Base branch.** Resolved from the flag, the environment, or `origin/main`,
  whichever git can find first. GitHub pull requests need no configuration.
- **Empty fragments.** A blank fragment file satisfies `towncrier check` and
  yields a blank release note. It fails here unless you pass `--allow-empty`.
- **New branches.** `--skip-new-branch` passes a branch's first push, when the
  pull request number that fragment names often embed does not exist yet.

## Installation

```yaml
default_install_hook_types: [pre-commit, pre-push]
repos:
  - repo: https://github.com/ChartinoLabs/towncrier-fragment-check
    rev: v0.1.0
    hooks:
      - id: towncrier-fragment-check
        stages: [pre-push]
```

Then run `pre-commit install`.

The check describes a whole branch, not one commit, so `pre-push` is the
recommended stage: it asks once, when the branch becomes visible to reviewers.
To run at the `pre-commit` stage instead, set `stages: [pre-commit]` and pass
`args: [--staged]` so fragments staged in the current commit count.

### Monorepos

Each independently released package in a monorepo usually has its own towncrier
configuration, fragment directory, and changelog. Name each one with
`--project DIR`, or `--project DIR:CONFIG` when the configuration is not in
that directory's `pyproject.toml` or `towncrier.toml`:

```yaml
      - id: towncrier-fragment-check
        stages: [pre-push]
        args:
          - --project
          - packages/api
          - --project
          - apps/web:apps/web/towncrier.toml
```

By default a fragment in any one project passes, which suits a pull request that
changes only one package. Add `--require all` when every project must carry its
own.

## Continuous integration

On a GitHub pull request the base branch comes from `GITHUB_BASE_REF`. Check out
the full history so the diff is available:

```yaml
jobs:
  check-changelog-fragment:
    if: github.event_name == 'pull_request'
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
        with:
          fetch-depth: 0
      - run: uvx towncrier-fragment-check==0.1.0 --project packages/api --project apps/web
```

The package is on [PyPI](https://pypi.org/project/towncrier-fragment-check/), so
`pipx run` and `pip install` work too. If pre-commit already runs in CI, reuse
the configured hook with
`pre-commit run --hook-stage pre-push towncrier-fragment-check --all-files`.

## Options

| Option | Description |
|---|---|
| `--project DIR[:CONFIG]` | Towncrier project to check, relative to the git toplevel. Repeat once per project. Defaults to the repository root. |
| `--require {any,all}` | Pass rule across projects. Default `any`. |
| `--compare-with BRANCH` | Base ref to diff against. |
| `--staged` | Include staged files, for the `pre-commit` stage. |
| `--allow-empty` | Do not fail on empty or whitespace-only fragments. |
| `--skip-new-branch` | Exit 0 when `PRE_COMMIT_FROM_REF` is all zeros. |
| `--verbose`, `-v` | Always print towncrier's full output. |
| `--version` | Print the version and exit. |

## Base branch resolution

The first candidate git can resolve wins:

1. `--compare-with`
2. `TOWNCRIER_COMPARE_WITH`
3. `GITHUB_BASE_REF`, prefixed with `origin/` when it contains no `/`
4. `origin/main`
5. `origin/master`
6. towncrier's own default

## Exit codes

| Code | Meaning |
|---|---|
| `0` | Passed. |
| `1` | No fragment, an empty fragment, or no resolvable base ref. |
| `2` | Usage error. |

## Development

```bash
uv sync --group dev
uv run pre-commit install
uv run pytest
```

## License

Apache-2.0. See [LICENSE](LICENSE).
