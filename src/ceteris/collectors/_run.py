"""Subprocess helper. Never raises.

This is where the UNKNOWN / NOT_APPLICABLE distinction is actually decided, in
one place, so every collector inherits it consistently:

    tool not on PATH            -> NOT_APPLICABLE   (structurally absent)
    tool present but failed     -> UNKNOWN          (fail closed)
    tool present but timed out  -> UNKNOWN          (fail closed)

Getting this backwards in either direction breaks a real case: treat a missing
nvidia-smi as UNKNOWN and every laptop-to-laptop comparison becomes
uncertifiable; treat a hung nvidia-smi as NOT_APPLICABLE and a GPU node quietly
compares equal to a laptop.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass

DEFAULT_TIMEOUT = 5.0


@dataclass(frozen=True)
class CmdResult:
    argv: list[str]
    ok: bool
    missing: bool
    stdout: str = ""
    stderr: str = ""
    detail: str = ""
    timed_out: bool = False

    @property
    def banner(self) -> str:
        """Version banners are not consistently on stdout: `java -version`
        writes to stderr and exits 0, which left toolchain.java permanently
        unknown. Prefer stdout, fall back to stderr."""
        return self.stdout.strip() or self.stderr.strip()

    @property
    def provenance(self) -> str:
        return " ".join(self.argv)


def run(
    argv: list[str],
    timeout: float = DEFAULT_TIMEOUT,
    cwd: str | None = None,
) -> CmdResult:
    tool = shutil.which(argv[0])
    if tool is None:
        return CmdResult(
            argv=argv, ok=False, missing=True, detail=f"{argv[0]} not on PATH"
        )
    try:
        proc = subprocess.run(
            [tool, *argv[1:]],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return CmdResult(
            argv=argv,
            ok=False,
            missing=False,
            detail=f"timed out after {timeout}s",
            timed_out=True,
        )
    except OSError as exc:
        return CmdResult(argv=argv, ok=False, missing=False, detail=str(exc))

    if proc.returncode != 0:
        stderr = " ".join(proc.stderr.split())[:200]
        return CmdResult(
            argv=argv,
            ok=False,
            missing=False,
            stdout=proc.stdout,
            stderr=proc.stderr,
            detail=f"exit {proc.returncode}: {stderr}" if stderr else f"exit {proc.returncode}",
        )
    return CmdResult(argv=argv, ok=True, missing=False, stdout=proc.stdout, stderr=proc.stderr)
