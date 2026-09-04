# Releasing ceteris

One artifact, many doors. PyPI holds the sdist and wheel; every other
channel wraps that sdist. Nothing is built by hand.

## Cutting a release

1. Move the top `CHANGELOG.md` section from `(unreleased)` to the version and
   date, and set `__version__` in `src/ceteris/__init__.py`. The release
   workflow refuses a tag that does not match `__version__`.
2. Commit, then tag and push the tag:

   ```sh
   git tag v0.3.0
   git push origin main v0.3.0
   ```

3. `.github/workflows/release.yml` builds from the tag, checks the
   distributions with twine, publishes to PyPI through trusted publishing,
   and opens a GitHub release with the changelog section as its notes and
   the files attached. Watch it under Actions; if the PyPI step fails, fix
   the trusted-publisher setup below and re-run the job, do not upload by
   hand into the same version.
4. On the GitHub release page tick *Publish this Action to the GitHub
   Marketplace* the first time, so `iemAnshuman/ceteris@v0.3.0` is
   discoverable there. Move the `v0` tag when a compatible release lands:

   ```sh
   git tag -f v0 v0.3.0 && git push -f origin v0
   ```

One-time setup on PyPI: project `ceteris`, *Publishing*, add a GitHub
publisher with owner `iemAnshuman`, repository `ceteris`, workflow
`release.yml`, environment `pypi`. After that the account token on this
laptop can be deleted.

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
