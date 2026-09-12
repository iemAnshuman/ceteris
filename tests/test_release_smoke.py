"""Use the same real-CLI scenarios in the test suite and on built artifacts."""

import runpy
from pathlib import Path


def test_release_cli_acceptance_and_refusal_paths():
    smoke = runpy.run_path(str(Path(__file__).resolve().parents[1] / "scripts" / "smoke_release.py"))
    smoke["main"]()
