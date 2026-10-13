# Publishing a HACS integration release

## Distribution contract

Repository: `hiromo/ha-dji-power-bt`. Integration domain and directory:
`custom_components/dji_power_bt`. Keep these stable for existing installations.
HACS uses the standard repository layout with `hacs.json`; this repository does
not enable release ZIP assets. GitHub-generated source archives are sufficient.
Do not add `zip_release` without also implementing and validating that packaging.

Publish a normal GitHub release, not a draft or prerelease, for the regular
update channel. Match the numeric manifest version to the release tag without
its `v` prefix: manifest `0.7.33`, tag `v0.7.33`. Mark it as Latest.
A tag alone is not the complete release procedure.

## Procedure

1. Confirm the working tree and remote main contain the intended changes and
   inspect the latest published release to choose an unused increasing version.
2. Update `custom_components/dji_power_bt/manifest.json`, date the changelog
   using the release date, and update user-facing upgrade instructions where
   behavior changes. Do not change config-entry version or entity identifiers
   merely to publish a release.
3. Run `python -m pytest -q` and
   `python -m compileall -q custom_components tests`, plus `git diff --check`.
   Investigate failures. Record any pre-existing failures outside the shipped
   integration explicitly; never claim the complete suite passed if it did not.
4. Commit the reviewed release preparation and push main. Wait for the existing
   GitHub Actions HACS and Hassfest validation jobs on that exact commit.
5. Create an annotated tag on that validated commit and push only that tag:

   ```sh
   git tag -a v0.7.33 -m "Release v0.7.33" <validated-commit-sha>
   git push origin v0.7.33
   ```

   Substitute the new version on future releases. Do not move published tags.
6. On GitHub, open Releases, choose Draft a new release, select the existing
   tag, enter a title and release notes, leave prerelease unchecked, set the
   release as Latest, and publish. With authenticated GitHub CLI, the equivalent
   is `gh release create v0.7.33 --verify-tag --title "v0.7.33" --notes-file release-notes.md --latest`.
7. Verify the public release is neither draft nor prerelease, its tag resolves
   to the intended commit, and its source archive contains the matching
   manifest and complete integration directory.

## Existing users

HACS detects the release during its repository refresh; this is not an immediate
broadcast or automatic installation. Users install the offered update and
restart Home Assistant. Existing users retain their repository registration,
config entries, credentials, and entity IDs. If no update is visible yet,
refresh repository information in HACS and inspect the selected version.

## Version 0.7.33 validation scope

BLE startup and retry changes are covered by local behavioral tests. Improved
recovery on physical stations after these changes is not yet verified.
The repository also contains separate automation examples; failures in their
standalone tests must be reported separately from the integration tests.

## References

- [HACS integration requirements](https://www.hacs.xyz/docs/publish/integration/)
- [GitHub release creation](https://docs.github.com/en/repositories/releasing-projects-on-github/managing-releases-in-a-repository)
