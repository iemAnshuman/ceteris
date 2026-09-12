"""Exercise the installed CLI, including refusal paths, before publishing it.

Run with a fresh environment's Python: python -I scripts/smoke_release.py.
No test dependencies or editable checkout imports are needed.
"""

import json
from pathlib import Path
import subprocess
import sys
import tempfile


def cli(work, expected, *args):
    result = subprocess.run([sys.executable, "-I", "-m", "ceteris", *args],
                            cwd=work, capture_output=True, text=True)
    if result.returncode != expected:
        raise AssertionError((args, expected, result.returncode, result.stdout, result.stderr))
    return result.stdout


def main():
    good = {"name": "good", "real_time": 42}
    failed = {"name": "failed", "error_occurred": True}
    cases = [
        ("valid", [good], None, 0),
        ("failed-first", [failed, good], None, 2),
        ("failed-last", [good, failed], None, 2),
        ("all-failed", [failed], None, 2),
        ("null", [{"name": "bad", "real_time": None}], "gbench", 2),
        ("mixed-repetitions", [good, {**good, "real_time": None}, good], "gbench", 2),
        ("infinite", [{"name": "bad", "real_time": "Infinity"}], "gbench", 2),
        ("boolean", [{"name": "bad", "real_time": True}], "gbench", 2),
    ]
    with tempfile.TemporaryDirectory(prefix="ceteris-release-smoke-") as scratch:
        for name, rows, fmt, expected in cases:
            work = Path(scratch) / name
            work.mkdir()
            content = json.dumps({"benchmarks": rows})
            script = "from pathlib import Path; Path('out.json').write_text(" + repr(content) + ")"
            cli(work, 0, "run", "--repeats", "2", "-q", "--ingest",
                "out.json" + (":" + fmt if fmt else ""), "--", sys.executable, "-c", script)
            records = sorted(str(p) for p in (work / ".ceteris" / "runs").glob("*.json"))
            assert len(records) == 2, records
            output = cli(work, expected, "compare", "--certify", *records)
            certificate = next(line for line in output.splitlines() if line.startswith("ceteris-certified"))
            cli(work, 0, "verify", certificate, *records)
            cli(work, 0 if expected == 0 else 1, "verify", "--require-pass", certificate, *records)
            print(name + ": run / compare / verify / require-pass OK", flush=True)


if __name__ == "__main__":
    main()
