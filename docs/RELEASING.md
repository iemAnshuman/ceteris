# Releasing ceteris

One artifact, many doors. PyPI holds the sdist and wheel; every other
channel wraps that sdist. Nothing is built by hand.

## Cutting a release

1. Move the top `CHANGELOG.md` section from `(unreleased)` to the version and
   date, and set `__version__` in `src/ceteris/__init__.py`. The release
   workflow refuses a tag that does not match `__version__`.
2. Commit, then tag and push the tag:

   ```sh
   git tag v0.4.1
   git push origin main v0.4.1
   ```

3. `.github/workflows/release.yml` first runs the reusable Ubuntu/macOS ×
   Python 3.9–3.14 test workflow against the tagged commit. Only after all
   matrix jobs pass does it build from the tag and check the
   distributions with twine. It then installs the wheel in a fresh environment
   and runs `scripts/smoke_release.py`, checking real CLI passing and refusal
   paths before uploading any release assets. See [TESTING.md](TESTING.md).
   It publishes to PyPI when trusted publishing
   is enabled and opens a GitHub release with the changelog section as its
   notes and the files attached. Watch it under Actions; if the PyPI step fails, fix
   the trusted-publisher setup below and re-run the job, do not upload by
   hand into the same version.
4. On the GitHub release page tick *Publish this Action to the GitHub
   Marketplace* the first time, so `iemAnshuman/ceteris@v0.4.1` is
   discoverable there. Move the `v0` tag when a compatible release lands:

   ```sh
   previous_v0=$(git ls-remote origin refs/tags/v0 | cut -f1)
   git tag -f v0 v0.4.1
   git push --force-with-lease="refs/tags/v0:$previous_v0" origin refs/tags/v0
   ```

   Only full `vMAJOR.MINOR.PATCH` tags trigger publishing. Moving `v0` does
   not start a second release build or fail the full-version guard.

The 0.4 release supports the legacy capture/compare workflow. The planned
campaign runner, installed native profiles, the `v2/` Action, and schema-4
acceptance/availability verification are excluded from release claims. The
experimental commands must continue to fail unsupported assurance requests.
Consult [SUPPORT.md](SUPPORT.md) before expanding that scope.

One-time setup on PyPI: project `ceteris`, *Publishing*, add a GitHub
publisher with owner `iemAnshuman`, repository `ceteris`, workflow
`release.yml`, environment `pypi`, then set the repository variable
`PYPI_TRUSTED_PUBLISHING` to `true` so the publish job stops being skipped.
After that the account token on this laptop can be deleted.

Until then, wait for the tag's release workflow to finish successfully and
upload its attached distributions using local PyPI credentials:

```sh
gh release download v0.4.1 --repo iemAnshuman/ceteris --dir /tmp/ceteris-release-0.4.1
python -m twine check /tmp/ceteris-release-0.4.1/*
python -m twine upload --non-interactive /tmp/ceteris-release-0.4.1/*
```

Upload those exact files. Rebuilding the tag can change archive timestamps;
the GitHub release and PyPI must offer the same bytes. Check the published
SHA-256 digests against the downloaded files after upload.

`v0.3.0` used a local build and matching GitHub assets on 2026-09-04; sdist sha256
`f301e7a5ab746dec98307fce30d1096b063a70671b00eba98de59b88c0da0484`.

## What users run to update

```sh
pip install -U ceteris
pipx upgrade ceteris
uv tool upgrade ceteris
```

Records written by an older version keep loading; `ceteris compare` warns
when it sees mixed schema versions. Certificates are versioned separately
and a newer `ceteris verify` says which versions it accepts.

## Channels, in the order they pay off

| channel | who finds it there | state |
|---|---|---|
| PyPI (`pip`, `pipx`, `uv tool`) | everyone; the source of truth | live |
| GitHub Marketplace (the Action) | CI users | listed once a release is published from a tag |
| Zenodo DOI via `CITATION.cff` | papers and artifact appendices | connect the repository at zenodo.org once; every GitHub release then gets a DOI; paste the concept DOI into `CITATION.cff` |
| Spack `py-ceteris` | HPC clusters, where admins install by Spack | template below; open a pull request to spack/spack after the PyPI release |
| conda-forge | ML researchers living in conda | pure-Python `noarch` recipe against the PyPI sdist; pull request to conda-forge/staged-recipes |
| Homebrew | macOS and Linux developers | a personal tap now (`brew install iemAnshuman/ceteris/ceteris`); homebrew-core once the project is old and used enough to meet its notability bar |

Not worth doing yet: Debian, Fedora, Nix, Snap, Docker (a zero-dependency
Python package gains nothing from a container), and anything Windows.

### Spack

`var/spack/repos/builtin/packages/py-ceteris/package.py`:

```python
from spack.package import *


class PyCeteris(PythonPackage):
    """Wrap any benchmark; refuse the comparison unless it is valid."""

    homepage = "https://github.com/iemAnshuman/ceteris"
    pypi = "ceteris/ceteris-0.3.0.tar.gz"
    license("MIT")
    maintainers("iemAnshuman")

    version("0.3.0", sha256="<sha256 of the sdist on PyPI>")

    depends_on("python@3.9:", type=("build", "run"))
    depends_on("py-setuptools@77:", type="build")
```

### Homebrew tap

Repository `iemAnshuman/homebrew-ceteris`, file `Formula/ceteris.rb`:

```ruby
class Ceteris < Formula
  include Language::Python::Virtualenv

  desc "Wrap any benchmark; refuse the comparison unless it is valid"
  homepage "https://github.com/iemAnshuman/ceteris"
  url "https://files.pythonhosted.org/packages/source/c/ceteris/ceteris-0.3.0.tar.gz"
  sha256 "<sha256 of the sdist on PyPI>"
  license "MIT"

  depends_on "python@3.13"

  def install
    virtualenv_install_with_resources
  end

  test do
    assert_match "ceteris", shell_output("#{bin}/ceteris --version")
    system bin/"ceteris", "doctor"
  end
end
```

The sdist's sha256 is printed by `sha256sum dist/ceteris-0.3.0.tar.gz` after
the release workflow's build, and shown on the PyPI file page.
