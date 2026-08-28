"""Compiler identity, flags, and selected CMake cache entries."""

from __future__ import annotations

import os
import re
import shutil

from ..model import Field, not_applicable, unknown, value
from ._run import run


def _parse_compiler(text: str) -> tuple[str | None, str | None]:
    first = text.strip().splitlines()[0] if text.strip() else ""
    lowered = text.lower()
    if "apple clang" in lowered:
        ident = "apple-clang"
    elif "clang" in lowered:
        ident = "clang"
    elif "free software foundation" in lowered or re.match(r"^g\+\+", first):
        ident = "gcc"
    elif "intel" in lowered or "icpx" in lowered:
        ident = "intel"
    elif "nvc++" in lowered or "nvidia" in lowered:
        ident = "nvhpc"
    else:
        ident = None
    match = re.search(r"version\s+(\d+(?:\.\d+)*)", first) or re.search(
        r"(\d+\.\d+(?:\.\d+)?)", first
    )
    return ident, (match.group(1) if match else None)


def _read_cmake_cache(path: str) -> dict[str, str]:
    entries: dict[str, str] = {}
    with open(path, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.strip()
            if not line or line.startswith(("#", "//")):
                continue
            match = re.match(r"^([A-Za-z0-9_\-\.]+):([A-Z]+)=(.*)$", line)
            if match:
                entries[match.group(1)] = match.group(3)
    return entries


def collect(ctx) -> dict[str, Field]:
    out: dict[str, Field] = {}

    cache: dict[str, str] = {}
    cache_path = ctx.cmake_cache
    if cache_path:
        cache_path = os.path.abspath(os.path.expanduser(cache_path))
        if os.path.isdir(cache_path):
            cache_path = os.path.join(cache_path, "CMakeCache.txt")
        out["build.cmake_cache_path"] = value(cache_path, provenance="--cmake-cache")
        try:
            cache = _read_cmake_cache(cache_path)
        except OSError as exc:
            out["build.cmake_cache_path"] = unknown(
                str(exc), provenance="--cmake-cache"
            )
    else:
        out["build.cmake_cache_path"] = not_applicable(
            "no --cmake-cache given", provenance="--cmake-cache"
        )

    for key in ctx.cfg.cmake_keys:
        path = f"build.cmake.{key}"
        if key in cache:
            out[path] = value(cache[key], provenance=f"CMakeCache.txt:{key}")
        elif cache:
            out[path] = not_applicable(
                "not present in CMakeCache.txt", provenance=f"CMakeCache.txt:{key}"
            )
        else:
            out[path] = not_applicable(
                "no CMake cache captured", provenance="--cmake-cache"
            )

    compiler, source = ctx.compiler, "--compiler"
    if not compiler:
        compiler, source = os.environ.get("CXX"), "$CXX"
    if not compiler:
        compiler, source = cache.get("CMAKE_CXX_COMPILER"), "CMakeCache.txt"
    if not compiler:
        compiler, source = "c++", "default c++ on PATH"

    resolved = shutil.which(compiler) or compiler
    res = run([compiler, "--version"])
    if res.missing:
        for key in ("compiler_path", "compiler_id", "compiler_version"):
            out[f"build.{key}"] = not_applicable(res.detail, provenance=source)
    elif not res.ok:
        for key in ("compiler_path", "compiler_id", "compiler_version"):
            out[f"build.{key}"] = unknown(res.detail, provenance=res.provenance)
    else:
        ident, version = _parse_compiler(res.banner)
        out["build.compiler_path"] = value(resolved, provenance=source)
        out["build.compiler_id"] = (
            value(ident, provenance=res.provenance)
            if ident
            else unknown(
                "unrecognised compiler banner: " + " ".join(res.banner.split())[:120],
                provenance=res.provenance,
            )
        )
        out["build.compiler_version"] = (
            value(version, provenance=res.provenance)
            if version
            else unknown("no version in banner", provenance=res.provenance)
        )

    flags, flag_source = ctx.cxx_flags, "--cxx-flags"
    if flags is None:
        flags, flag_source = os.environ.get("CXXFLAGS"), "$CXXFLAGS"
    if flags is None:
        flags, flag_source = cache.get("CMAKE_CXX_FLAGS"), "CMakeCache.txt"
    out["build.cxx_flags"] = (
        value(flags, provenance=flag_source)
        if flags is not None
        else not_applicable(
            "no --cxx-flags, $CXXFLAGS, or CMake cache", provenance="--cxx-flags"
        )
    )

    btype, type_source = ctx.build_type, "--build-type"
    if btype is None:
        btype, type_source = cache.get("CMAKE_BUILD_TYPE"), "CMakeCache.txt"
    out["build.type"] = (
        value(btype, provenance=type_source)
        if btype
        else not_applicable(
            "no --build-type or CMake cache", provenance="--build-type"
        )
    )
    return out
