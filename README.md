# towncrier-fragment-check

A [pre-commit](https://pre-commit.com) hook and CLI that fails when a branch does
not add a [towncrier](https://towncrier.readthedocs.io) changelog fragment. It is
a thin wrapper around `towncrier check` that keeps the same behaviour you already
know, and adds the pieces that a real repository tends to need: several towncrier
projects in one monorepo, correct results when the check is invoked from a
subdirectory, a base branch that is resolved the way CI and pre-commit expect,
and a hard failure on fragment files that were created but left empty.

## Why not just `towncrier check`?

`towncrier check` is the right tool and this project delegates all of the actual
fragment discovery to it. These are the gaps it closes around that call:

- **Multiple projects.** `towncrier check` checks one project per invocation.
  Pass `--project` more than once to check several, and choose whether a
  fragment in any one project is enough (`--require any`, the default) or every
  project needs its own (`--require all`).
- **Subdirectory safety.** `towncrier check` resolves the repository-relative
  paths that git reports against the process working directory. Running it
  inside `packages/api/` therefore looks for
  `packages/api/packages/api/changes/...` and never matches. This wrapper always
  runs towncrier with the git toplevel as the working directory and passes
  `--dir` and `--config` relative to that root, which works correctly. Verified
  against towncrier 25.8.0.
- **Base branch resolution.** The comparison ref is resolved from the flag, then
  the environment, then the usual remote defaults, skipping any candidate git
  cannot resolve. On a GitHub pull request the base branch is picked up from
  `GITHUB_BASE_REF` with no configuration.
- **Empty fragments.** A fragment file that exists but contains nothing, or only
  whitespace, satisfies `towncrier check` and produces an empty release note.
  This wrapper reads every fragment towncrier found and fails on the empty ones.
  Use `--allow-empty` to opt out.
- **New branches under pre-commit.** At the pre-push stage, pre-commit reports an
  all-zero `PRE_COMMIT_FROM_REF` for a branch that does not exist on the remote
  yet. `--skip-new-branch` exits 0 in that case, which is useful when fragment
  file names embed a pull request number that does not exist before the first
  push. CI remains the authoritative gate.

## Installation

Add the hook to `.pre-commit-config.yaml`:

```yaml
---
default_install_hook_types: [pre-commit, pre-push]
repos:
  - repo: https://github.com/ChartinoLabs/towncrier-fragment-check
    rev: v0.1.0
    hooks:
      - id: towncrier-fragment-check
        stages: [pre-push]
```

Then install both hook types:

```bash
pre-commit install
```

The `pre-push` stage is the recommended default. The check is a statement about a
whole branch rather than a single commit, so asking for a fragment on the first
commit of a branch is noisy, and fragment file names often embed a pull request
number that does not exist yet at that point. Running at push time asks once, at
the moment the branch becomes visible to reviewers.

To run it at the `pre-commit` stage instead, pass `--staged` so that fragments
staged in the current commit are counted:

```yaml
      - id: towncrier-fragment-check
        args: [--staged]
```

### Monorepo

Point the hook at each towncrier project. A project is a directory relative to
the git toplevel, optionally followed by `:` and the path to its towncrier
configuration file:

```yaml
      - id: towncrier-fragment-check
        stages: [pre-push]
        args:
          - --project
          - packages/api
          - --project
          - apps/web:apps/web/towncrier.toml
          - --require
          - any
```

With `--require any`, a fragment in either project satisfies the check. Use
`--require all` when every project must carry its own fragment.

## Continuous integration

On a GitHub pull request the base branch is available as `GITHUB_BASE_REF`, so no
base branch configuration is needed. A full history is required for the diff:

```yaml
---
jobs:
  check-changelog-fragment:
    if: github.event_name == 'pull_request'
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
        with:
          fetch-depth: 0
      - name: Check for a changelog fragment
        run: >-
          uvx --from
          git+https://github.com/ChartinoLabs/towncrier-fragment-check@v0.1.0
          towncrier-fragment-check --project packages/api --project apps/web
```

`pipx run` works the same way. If pre-commit already runs in CI, the configured
hook can be reused instead:

```yaml
      - run: pre-commit run --hook-stage pre-push towncrier-fragment-check --all-files
```

## Options

| Option | Description |
|---|---|
| `--project DIR[:CONFIG]` | Towncrier project to check. Repeatable. `DIR` is relative to the git toplevel, and the optional `CONFIG` is a path to a `towncrier.toml` or `pyproject.toml`, also relative to the toplevel. Defaults to a single project at the repository root with no explicit config, which lets towncrier auto-discover its configuration. |
| `--require {any,all}` | Pass rule across projects. Default `any`. |
| `--compare-with BRANCH` | Base ref to diff against. |
| `--staged` | Include staged files, for use at the `pre-commit` stage. |
| `--allow-empty` | Do not fail on empty or whitespace-only fragments. |
| `--skip-new-branch` | Exit 0 when `PRE_COMMIT_FROM_REF` is all zeros. |
| `--verbose`, `-v` | Always print the full towncrier output for every project. |
| `--version` | Print the version and exit. |

## How the base branch is resolved

Candidates are tried in this order, and any candidate that `git rev-parse
--verify` cannot resolve is skipped:

1. `--compare-with`
2. `TOWNCRIER_COMPARE_WITH`
3. `GITHUB_BASE_REF`, prefixed with `origin/` when it contains no `/`
4. `origin/main`
5. `origin/master`
6. towncrier's own default, by passing nothing

If none of those produce a usable ref, the check exits 1 and asks you to fetch
the base branch or pass `--compare-with`.

## Exit codes

| Code | Meaning |
|---|---|
| `0` | The check passed. |
| `1` | The check failed: no fragment, an empty fragment, or no resolvable base ref. |
| `2` | Usage error, such as an unknown option or an invalid `--require` value. |

## Development

```bash
uv sync --group dev
uv run pre-commit install
uv run pytest
```

## License

Apache-2.0. See [LICENSE](LICENSE).
