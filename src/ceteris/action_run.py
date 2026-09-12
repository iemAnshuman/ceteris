"""Internal Action entrypoint: inputs are data, not interpolated shell code."""
from __future__ import annotations

import os
import shlex
import sys

from .cli import main


def run(label: str) -> int:
    args = ["run", "--label", label, "--config", os.environ["CETERIS_CONFIG"],
            "--repeats", os.environ["REPEATS"]]
    for metric in os.environ.get("METRIC", "").splitlines():
        if metric.strip():
            args.extend(["--metric", metric])
    args.extend(["--", *shlex.split(os.environ["COMMAND"])])
    return main(args)


if __name__ == "__main__":
    raise SystemExit(run(sys.argv[1]))
