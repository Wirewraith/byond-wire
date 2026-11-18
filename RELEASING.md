# Packages and releases

- Package names below are configured publication targets; availability depends on the first successful release and registry ownership.
- Each implementation has an independent stable `major.minor.patch` version. C# library and tool versions move together. Prerelease tags are not supported yet.
- Shared protocol fixes can release several implementations from the same commit, with each package's own version and tag.
- Native manifests own versions; Go uses `go/VERSION`, and PHP uses `php/VERSION` for validation while Composer derives the public version from its Git tag.

| Implementation | Packages | Version source | Release tag | GitHub environment |
| --- | --- | --- | --- | --- |
| Python | PyPI `byond-wire` | `python/pyproject.toml` | `python/v0.1.0` | `pypi` |
| Node.js | npm `byond-wire` | `nodejs/package.json` | `nodejs/v0.1.0` | `npm` |
| Rust | crates.io `byond-wire` | `rust/Cargo.toml` | `rust/v0.1.0` | `crates` |
| PHP | Packagist `wirewraith/byond-wire` | `php/VERSION` | `v0.1.0` | `packagist` |
| PowerShell | Gallery `ByondWire` | `powershell/ByondWire.psd1` | `powershell/v0.1.0` | `psgallery` |
| C# | NuGet `ByondWire`, `ByondWire.Cli` | Both `.csproj` version fields | `csharp/v0.1.0` | `nuget` |
| Go | `github.com/Wirewraith/byond-wire/go` | `go/VERSION` | `go/v0.1.0` | `go` |

- PHP reserves plain `v*` tags. Its publisher copies the tested Composer archive to [`byond-wire-php`](https://github.com/Wirewraith/byond-wire-php), commits it on `main`, and atomically pushes `main` and the same version tag. Packagist indexes that distribution repository. Development and version tags remain in this monorepo; keep its Composer manifest at the root for builds.
- Go requires the `go/` tag prefix for its subdirectory module. Go v2 will require a `/v2` module/import migration before release.
- `tests/text-vectors.tsv` is authoritative. The Go module includes a generated copy for tests outside the checkout; refresh it with `python3 packaging/release.py --sync-go-fixture`. CI checks equality. Other package fixtures are generated during staging.
- Runtime libraries have no third-party dependencies. Build and publishing tools are development-only dependencies.

## Build and validate

- [CI](.github/workflows/ci.yml) tests all packages on pushes and pull requests, with additional PowerShell tests on Windows. It also lints workflows, runs shell and benchmark regressions, and tests Python 3.9, Node.js 18, PHP 8.0, and PowerShell 7.4. Native builds cover Go 1.22 and .NET 10.
- [Native builds](.github/workflows/build.yml) stage only the selected implementation, shared protocol documentation, MIT license, and applicable test assets. They run regression tests, build native artifacts, then install them into temporary consumer projects outside the checkout to check SDK imports, decoded results, raw CLI bytes, null/number/empty results, and exit codes.
- Python builds a wheel and source distribution; npm builds a tarball; Rust builds a crate; PHP builds a Composer zip; PowerShell builds a module package; C# builds library and tool NuGet packages; Go builds a source zip and checks a clean consumer module.
- Artifacts are retained as `package-<implementation>`, including `release.json` with the source commit and version: seven days for CI, the repository default for tagged builds. Go publishes through its Git tag. PHP publishes the tested Composer archive's contents to its distribution repository, giving Packagist and Composer the PHP-only README and sources. Distribution commit messages link to the original source commit.
- To stage a package locally: `python3 packaging/release.py python --output /tmp/byond-python`. Use a new directory. Build with native tools there; for Python, `python3 -m build --outdir /tmp/byond-python-dist /tmp/byond-python` (requires `build`). Staging supplies shared files referenced by the manifests.
- Release tooling tests: `python3 -m unittest discover -s packaging`.

## Configure publishing once

- Push this checkout to `https://github.com/Wirewraith/byond-wire` and verify ownership/availability of each registry package name. No registry accounts or package reservations are created by these workflows.
- Create the environments listed above. Configure their allowed deployment tags to match the table; also allow the default branch for manual publishing with updated workflows. Publisher credentials belong in their matching environments.
- PyPI: configure a pending or existing trusted publisher for owner `Wirewraith`, repository `byond-wire`, workflow `publish.yml`, environment `pypi`.
- npm: create the initial package if required, then configure its GitHub Actions trusted publisher with owner `Wirewraith`, repository `byond-wire`, workflow filename `publish.yml`, and environment `npm` (all case-sensitive). Allow direct `npm publish`; new publisher configurations default to staged publishing only. The workflow uses Node 24 and npm OIDC (npm 11.5.1 or later); no stored npm token is required. For `ENEEDAUTH`, check these registry settings first. See [npm trusted publishing](https://docs.npmjs.com/trusted-publishers/).
- crates.io: configure a trusted publisher for `byond-wire` on crates.io with GitHub owner `Wirewraith`, repository `byond-wire`, workflow filename `publish.yml` (not the display name `Publish package` or `release.yml`), and environment `crates`. Creating the GitHub environment alone does not configure registry trust. `No Trusted Publishing config found` means this registry configuration is missing or does not match. If an initial manual publication is required, download `package-rust` from the failed Publish package run, extract its tested `.crate` into a new directory, and run `cargo publish --manifest-path <directory>/Cargo.toml` using a local crates.io login; then configure trust. See [crates.io trusted publishing](https://crates.io/docs/trusted-publishing) and the [authentication action](https://github.com/rust-lang/crates-io-auth-action).
- NuGet: configure trusted publishing for the same repository/workflow and environment `nuget`, covering both package IDs. Set the environment's GitHub Actions configuration variable `NUGET_USER` to your NuGet profile name. See [NuGet trusted publishing](https://learn.microsoft.com/en-us/nuget/nuget-org/trusted-publishing).
- PowerShell Gallery: set environment secret `PSGALLERY_API_KEY` to a key permitted to publish `ByondWire`.
- Packagist: create public `Wirewraith/byond-wire-php` with default branch `main`, without initializing files, and disable Actions in that generated repository. Add a write-enabled SSH deploy key to it. In the monorepo's `packagist` environment, store the private key as secret `PHP_DISTRIBUTION_SSH_KEY` and GitHub's SSH host keys as variable `PHP_DISTRIBUTION_KNOWN_HOSTS` (`gh api meta --jq '.ssh_keys[] | "github.com " + .'`). Keep `PACKAGIST_USERNAME` and `PACKAGIST_API_TOKEN` (the update/read-only token). The publish job pushes tested contents before requesting a registry refresh. It rejects changed contents under an existing tag and unpublished versions older than the latest distribution tag; identical retries leave Git refs unchanged.
- To migrate the existing Packagist listing, first preserve all published PHP tags and their original commits: fetch the monorepo tags, then run `git push https://github.com/Wirewraith/byond-wire-php.git 'refs/tags/v*:refs/tags/v*'` (never force). Release a new PHP patch version through the updated workflow. Once its distribution `main` and tag exist, edit the existing `wirewraith/byond-wire` package's repository URL on Packagist to `https://github.com/Wirewraith/byond-wire-php`, then retry its publisher to refresh. Keep the package name and old tags; do not delete and resubmit the listing. Old versions retain their original monorepo contents; new versions contain only PHP. Configure the distribution repository's Packagist webhook for automatic updates.
- Go: the repository must be public and reachable by the Go proxy. No registry secret is required.

## Release or retry

1. Commit and push the implementation changes, and let CI pass on the default branch.
2. Open **Actions → Release → Run workflow** on the default branch. Choose `all` or one implementation, then `patch`, `minor`, or `major`. Choose `current` for an initial publication without a version bump.
3. Release reruns full CI on the selected default-branch commit before changing versions or creating tags. If validation fails or the branch advances, no release is pushed; start a new run after resolving the failure. After validation, it updates the selected native versions, keeps the C# pair and Rust lockfile consistent, commits the changes, and atomically pushes the branch and release tags. Each implementation retains its own version; `all` applies the chosen increment to each current version.
4. A separate **Publish package** run builds, tests, and publishes each tag. The Release workflow finishes after dispatching those runs; check their results for publication status.
5. Retry a failed publisher from its Actions run. To use updated workflows, open **Actions → Publish package → Run workflow**, select `main`, and enter the existing release tag, or run `gh workflow run publish.yml --ref main -f tag=python/v0.1.1`. Validation and builds check out that tag. Rerun only failed dispatch jobs if Release could not start a publisher. Running Release again with `patch` creates another version.

- Registry configuration fixes apply to retries on existing tags. Rerunning an old tag uses its old workflow. After pushing workflow fixes to `main`, dispatch from `main` with the existing tag input to use the updated workflows without creating another version.

```sh
# Equivalent to the Release form; no local version edits or tags required.
gh workflow run release.yml -f package=all -f bump=patch

# Read-only local preview of the next versions and tags.
python3 packaging/bump.py --package all --bump patch
```

- The Release workflow needs permission to push to the default branch and create the release tags. Repository rules must allow the Actions bot to do so; it does not bypass branch/tag protection. A rejected atomic push changes neither the remote branch nor its tags.
- The workflow uses the built-in `GITHUB_TOKEN` with `contents: write` to push and `actions: write` to dispatch publishers. GitHub suppresses push-triggered runs from that token, so it explicitly dispatches each publisher on its release tag. No personal access token is required. See [GitHub token event behavior](https://docs.github.com/en/actions/concepts/security/github_token).
- Existing selected tags cause Release to stop before editing versions. Use **Publish package** on an existing tag to retry. Never move a published tag or overwrite a version.
- Automated Go v2 releases are rejected until its module/import migration and release tooling support are implemented.
- Manual releases remain supported: update the affected version sources, commit, then create and push the corresponding tags individually. The tag/version validation in **Publish package** is unchanged.

