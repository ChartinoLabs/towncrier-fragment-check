# Releasing

Releases are cut from `main` and driven entirely by a git tag. Pushing a
`vX.Y.Z` tag runs [`.github/workflows/release.yaml`](.github/workflows/release.yaml),
which validates the tag, runs the test suite, builds the distributions, and
creates a GitHub Release with the changelog section for that version and the
built artifacts attached.

There is no PyPI publish step. pre-commit installs hooks straight from a git
tag, so a tagged GitHub Release is everything a consumer needs.

## Steps

1. Make sure `main` is green and up to date.

2. Compile the changelog fragments in `changes/` into `CHANGELOG.md`:

   ```bash
   uv run towncrier build --version X.Y.Z --yes
   ```

   Preview it first with `uv run towncrier build --draft --version X.Y.Z` if you
   want to see the rendered notes without consuming the fragments.

3. Review the new `## X.Y.Z` section in `CHANGELOG.md` and edit the wording if
   needed.

4. Commit the changelog and the consumed fragments:

   ```bash
   git add CHANGELOG.md changes/
   git commit -m "Release X.Y.Z"
   git push origin main
   ```

5. Wait for CI to pass on `main`.

6. Tag and push:

   ```bash
   git tag vX.Y.Z
   git push origin vX.Y.Z
   ```

7. Confirm the release workflow finished and that the GitHub Release contains
   the expected notes and artifacts.

8. Update the `rev:` in the README installation snippet if the example should
   point at the new tag.

## Versioning

The package version comes from the git tag by way of `hatch-vcs`, so there is no
version string to bump by hand. The release workflow verifies that the built
wheel's version matches the tag before it publishes anything.
