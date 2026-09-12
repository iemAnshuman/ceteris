"""ceteris -- capture benchmark run identity, then gate comparisons between runs.

Named for *ceteris paribus*: all other things being equal. That is precisely
the claim a benchmark comparison makes, and precisely the claim this tool
checks.

Library use mirrors the CLI:

    from ceteris import capture, compare, Config

    a = capture(repo="~/codes/hpx")
    b = capture(repo="~/codes/hpx")
    report = compare([a, b], vary=["runtime.env.LCI_ATTR_PACKET_SIZE"])
    assert report.exit_code == 0

`ceteris run -- mpirun ...` captures before and after the command to detect
mid-run drift and records measurements with the execution evidence.
"""

from .compare import Report, compare
from .config import Config
from .model import Field, Fingerprint, State

__version__ = "0.4.1"

def __getattr__(name: str):
    # capture is resolved lazily so that `from ceteris import compare` does not
    # pull in the subprocess-running collectors.
    if name == "capture":
        from .capture import capture

        return capture
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "capture",
    "compare",
    "Config",
    "Field",
    "Fingerprint",
    "Report",
    "State",
    "__version__",
]
