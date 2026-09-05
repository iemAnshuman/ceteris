"""Command line interface: capture and compare. That is the entire v1."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import certificate
from . import store as store_mod
from .compare import EXIT_INTEGRITY, EXIT_OK, EXIT_UNDECLARED, EXIT_USAGE, compare as compare_fingerprints
from .config import Config
from .metrics import parse_cli_metrics
from .model import Fingerprint
from .render import render, render_listing, to_json


def _build_parser() -> argparse.ArgumentParser:
    from . import __version__

    parser = argparse.ArgumentParser(
        prog="ceteris",
        description=(
            "Capture the identity of a benchmark run, then gate comparisons "
            "between runs. Named for ceteris paribus: all other things equal."
        ),
    )
    parser.add_argument("--version", action="version", version=f"ceteris {__version__}")
    sub = parser.add_subparsers(dest="subcommand", required=True)

    cap = sub.add_parser(
        "capture", help="emit a JSON fingerprint of the current run environment"
    )
    cap.add_argument("--repo", help="path of the source repository (default: cwd)")
    cap.add_argument(
        "--cmake-cache", help="build tree or CMakeCache.txt to read build settings from"
    )
    cap.add_argument("--compiler", help="C++ compiler to interrogate (default: $CXX)")
    cap.add_argument("--cxx-flags", help="build flags to record (default: $CXXFLAGS)")
    cap.add_argument("--build-type", help="build type to record, e.g. Release")
    cap.add_argument("--label", help="name for this run in comparison output")
    cap.add_argument("--config", help="TOML or JSON config extending the defaults")
    cap.add_argument("--pack", action="append", default=[], metavar="NAME", help="force an ecosystem pack on. Repeatable.")
    cap.add_argument("-o", "--output", help="write here instead of stdout")

    run = sub.add_parser(
        "run",
        help="capture, run a benchmark, capture again, and record it as one run",
    )
    for opt, helptext in (
        ("--repo", "path of the source repository (default: cwd)"),
        ("--cmake-cache", "build tree or CMakeCache.txt to read build settings from"),
        ("--compiler", "C++ compiler to interrogate (default: $CXX)"),
        ("--cxx-flags", "build flags to record (default: $CXXFLAGS)"),
        ("--build-type", "build type to record, e.g. Release"),
        ("--label", "name for this run in comparison output"),
        ("--config", "TOML or JSON config extending the defaults"),
        ("--store", "directory to record runs in (default: .ceteris/runs)"),
    ):
        run.add_argument(opt, help=helptext)
    run.add_argument(
        "--metric",
        action="append",
        default=[],
        metavar="NAME=REGEX",
        help="extract a number from the run output. Repeatable.",
    )
    run.add_argument("--adapter", metavar="NAME",
                     help="force a harness adapter (hyperfine, gbench, pytest, jmh, criterion, osu, nccl, mlperf) or 'none'")
    run.add_argument("--ingest", action="append", default=[], metavar="FILE[:FORMAT]",
                     help="read metrics from a harness output file after the run. Repeatable.")
    run.add_argument("--pack", action="append", default=[], metavar="NAME",
                     help="force an ecosystem pack on (hpc, cuda, python, rust, jvm, go, node). Repeatable.")
    run.add_argument("--repeats", type=int, default=1, metavar="N",
                     help="run the command N times, one record each (default 1)")
    run.add_argument("--no-store", action="store_true", help="do not record to the store")
    run.add_argument("-o", "--output", help="also write the record here")
    run.add_argument("-q", "--quiet", action="store_true", help="do not echo run output")
    run.add_argument(
        "command",
        nargs=argparse.REMAINDER,
        help="the benchmark command, after --",
    )

    doc = sub.add_parser(
        "doctor", help="report what a capture could not see, and what looks wrong")
    doc.add_argument("fingerprint", nargs="?",
                     help="a record to inspect; omit to capture this machine now")
    doc.add_argument("--repo", help="path of the source repository (default: cwd)")
    doc.add_argument("--pack", action="append", default=[], metavar="NAME")
    doc.add_argument("--config", help="TOML or JSON config extending the defaults")

    ls = sub.add_parser("list", help="list recorded runs")
    ls.add_argument("--store", help="directory to read runs from (default: .ceteris/runs)")

    cmp_ = sub.add_parser(
        "compare", help="check whether runs differ only in what you declared"
    )
    cmp_.add_argument(
        "fingerprints",
        nargs="*",
        help="fingerprint or run files; omit to select from the store",
    )
    cmp_.add_argument("--store", help="directory to select runs from")
    cmp_.add_argument("--last", type=int, metavar="N", help="compare the last N recorded runs")
    cmp_.add_argument(
        "--label",
        action="append",
        default=[],
        metavar="GLOB",
        help="select recorded runs whose label matches. Repeatable.",
    )
    cmp_.add_argument(
        "--vary",
        action="append",
        default=[],
        metavar="FIELD",
        help="field you intended to vary; accepts globs and bare prefixes. Repeatable.",
    )
    cmp_.add_argument(
        "--waive",
        action="append",
        default=[],
        metavar="FIELD:REASON",
        help="accept a difference with a recorded reason. Repeatable.",
    )
    cmp_.add_argument(
        "--strict",
        action="store_true",
        help="also gate on informational fields and on declared fields that did not vary",
    )
    cmp_.add_argument("--require-signal", action="store_true",
                      help="exit 4 unless some metric's gap exceeds the noise floor (needs >= 3 repeats per configuration)")
    cmp_.add_argument("--config", help="TOML or JSON config extending the defaults")
    cmp_.add_argument("--json", action="store_true", help="machine-readable report")
    cmp_.add_argument("--certify", action="store_true",
                      help="append a one-line certificate that `ceteris verify` can check")

    ver = sub.add_parser("verify", help="check a certificate line against its records")
    ver.add_argument("certificate", help="the ceteris-certified line, quoted")
    ver.add_argument("fingerprints", nargs="+", help="the record files the certificate covers")
    ver.add_argument("--config", help="TOML or JSON config extending the defaults")
    ver.add_argument("--require-pass", action="store_true",
                     help="exit non-zero unless the comparison itself passed, not merely that "
                          "the certificate honestly describes it")
    return parser


def _load_fingerprint(path: str) -> Fingerprint:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    fingerprint = Fingerprint.from_json(raw)
    if not fingerprint.meta.get("label"):
        fingerprint.meta["label"] = Path(path).stem
    return fingerprint


def _parse_waivers(items: list[str]) -> dict[str, str]:
    waivers: dict[str, str] = {}
    for item in items:
        field, sep, reason = item.partition(":")
        if not sep or not reason.strip():
            raise ValueError(
                f"--waive {item!r} needs a reason: use --waive FIELD:'why this is fine'"
            )
        waivers[field.strip()] = reason.strip()
    return waivers


def _cmd_capture(args) -> int:
    from .capture import capture

    cfg = Config.load(args.config, packs=args.pack, tree=args.repo)
    fingerprint = capture(
        repo=args.repo,
        cmake_cache=args.cmake_cache,
        compiler=args.compiler,
        cxx_flags=args.cxx_flags,
        build_type=args.build_type,
        label=args.label,
        cfg=cfg,
    )
    text = fingerprint.dumps()
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return EXIT_OK


def _select_paths(args) -> list[str]:
    if args.fingerprints:
        return list(args.fingerprints)
    store = store_mod.store_path(args.store)
    paths = store_mod.select(store, last=args.last, labels=args.label)
    if not paths:
        raise ValueError(
            f"no runs selected from {store}. Record some with `ceteris run`, "
            "or pass fingerprint files directly."
        )
    return [str(p) for p in paths]


def _cmd_compare(args) -> int:
    paths = _select_paths(args)
    if len(paths) < 2:
        raise ValueError(
            f"compare needs at least two runs; selected {len(paths)}"
        )
    cfg = Config.load(args.config)
    fingerprints = [_load_fingerprint(p) for p in paths]
    report = compare_fingerprints(
        fingerprints,
        vary=args.vary,
        waive=_parse_waivers(args.waive),
        cfg=cfg,
        strict=args.strict,
        require_signal=args.require_signal,
    )
    if args.json:
        body = to_json(report)
        if args.certify:
            body["certificate"] = certificate.issue(report)
        sys.stdout.write(json.dumps(body, indent=2, sort_keys=True) + "\n")
    else:
        sys.stdout.write(render(report))
        if args.certify:
            sys.stdout.write("\n" + certificate.issue(report) + "\n")
    return report.exit_code


def _cmd_verify(args) -> int:
    parsed = certificate.parse(args.certificate)
    cfg = Config.load(args.config)
    fingerprints = [_load_fingerprint(p) for p in args.fingerprints]
    report = compare_fingerprints(
        fingerprints, vary=parsed.vary, waive=parsed.waive, cfg=cfg, strict=parsed.strict,
        require_signal=parsed.require_signal,
    )
    result = certificate.verify(args.certificate, report)
    sys.stdout.write(f"ceteris: {result.message}\n")
    if not result.integrity_verified:
        return EXIT_INTEGRITY if args.require_pass else EXIT_UNDECLARED
    if args.require_pass and not result.comparison_passed:
        sys.stdout.write(
            f"ceteris: the certificate is genuine and the comparison did not pass "
            f"({result.verdict})\n"
        )
        return EXIT_UNDECLARED
    return EXIT_OK


def _cmd_run(args) -> int:
    from .runner import run_repeated

    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        raise ValueError(
            "nothing to run. Put the benchmark command after --, "
            "e.g. ceteris run --label a -- mpirun -n 2 ./bench"
        )
    cfg = Config.load(args.config, packs=args.pack, tree=args.repo)
    records = run_repeated(
        command,
        args.repeats,
        label=args.label,
        cfg=cfg,
        repo=args.repo,
        cmake_cache=args.cmake_cache,
        compiler=args.compiler,
        cxx_flags=args.cxx_flags,
        build_type=args.build_type,
        metric_patterns=parse_cli_metrics(args.metric),
        echo=not args.quiet,
        adapter=args.adapter,
        ingest=args.ingest,
    )
    worst = 0
    outputs = _output_paths(args.output, len(records))
    for record, out_path in zip(records, outputs):
        if out_path:
            Path(out_path).write_text(record.dumps(), encoding="utf-8")
        if not args.no_store:
            path = store_mod.save(record, store_mod.store_path(args.store))
            sys.stderr.write(f"ceteris: recorded {path}\n")
        if record.drift:
            sys.stderr.write(
                f"ceteris: WARNING -- the environment changed during this run "
                f"({len(record.drift)} field(s)); this run is not certifiable\n"
            )
        worst = max(worst, int(record.run.get("exit_code", 0)))
    if not any(r.metrics for r in records):
        # The environment is recorded either way, but a first-time user who
        # printed a number and got no measurement should be told why.
        sys.stderr.write(
            "ceteris: no metric was extracted: no harness was recognised and no "
            "--metric NAME=REGEX was given. The run is recorded with its "
            "environment only.\n"
        )
    # The wrapped command's exit code is passed through so that wrapping a
    # benchmark in ceteris does not change how a surrounding script behaves.
    return worst


def _output_paths(output: str | None, n: int) -> list:
    """-o with --repeats used to write one JSON list, which nothing could
    read back. One record per file: out.json, out-2.json, out-3.json."""
    if not output:
        return [None] * n
    if n == 1:
        return [output]
    base = Path(output)
    return [str(base)] + [str(base.with_name(f"{base.stem}-{i}{base.suffix}")) for i in range(2, n + 1)]


def _cmd_doctor(args) -> int:
    from . import doctor

    cfg = Config.load(args.config, packs=args.pack, tree=args.repo)
    if args.fingerprint:
        fingerprint, local = _load_fingerprint(args.fingerprint), False
    else:
        from .capture import capture

        fingerprint, local = capture(repo=args.repo, cfg=cfg, label="this machine"), True
    findings = doctor.diagnose(fingerprint, local=local)
    sys.stdout.write(doctor.render(fingerprint, findings))
    return doctor.exit_code(findings)


def _cmd_list(args) -> int:
    store = store_mod.store_path(args.store)
    paths = store_mod.all_runs(store)
    if not paths:
        sys.stdout.write(f"no runs recorded in {store}\n")
        return EXIT_OK
    sys.stdout.write(render_listing([store_mod.load(p) for p in paths], store))
    return EXIT_OK


# Options whose value legitimately starts with a dash. argparse would read
# `--cxx-flags -O3` as a missing value followed by an unknown option, which is
# a poor first experience for a tool whose entire subject is compiler flags.
_DASH_VALUED = ("--cxx-flags", "--metric")


def _glue_dash_values(argv: list[str]) -> list[str]:
    out: list[str] = []
    i = 0
    while i < len(argv):
        token = argv[i]
        if token == "--":  # everything after is the wrapped command
            out.extend(argv[i:])
            break
        if (
            token in _DASH_VALUED
            and i + 1 < len(argv)
            and argv[i + 1].startswith("-")
        ):
            out.append(f"{token}={argv[i + 1]}")
            i += 2
            continue
        out.append(token)
        i += 1
    return out


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(_glue_dash_values(list(argv if argv is not None else sys.argv[1:])))
    handler = {
        "capture": _cmd_capture,
        "run": _cmd_run,
        "list": _cmd_list,
        "doctor": _cmd_doctor,
        "compare": _cmd_compare,
        "verify": _cmd_verify,
    }[args.subcommand]
    try:
        return handler(args)
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        parser.exit(EXIT_USAGE, f"ceteris: {exc}\n")
    except KeyboardInterrupt:
        parser.exit(130, "ceteris: interrupted\n")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
