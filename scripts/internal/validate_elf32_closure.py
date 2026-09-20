#!/usr/bin/env python3
"""Validate the assembled d2s ELF32 or ELF64 linker closure.

This validator runs after all ROM modules have modified ``work_dir``.  It is
deliberately stricter than a global basename check: every DT_NEEDED edge is
resolved in the namespace that owns its consumer.  The model mirrors the
Android vendor/VNDK/runtime/system links closely enough to distinguish a file
that is absent from one that exists only in an inaccessible namespace.

The generated ``/linkerconfig/ld.config.txt`` is a boot-time artifact, so this
script cannot prove the final mount/link state.  It validates all static inputs
to that generation and reports duplicate routes as warnings for boot-time
confirmation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from collections import defaultdict, deque
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Mapping, Sequence


EM_ARM = 40
EM_AARCH64 = 183
EXPECTED_VNDK_VERSION = "31"
RUNTIME_APEX = "com.android.runtime.apex"
I18N_APEX = "com.android.i18n.apex"
VNDK31_APEX = "com.android.vndk.v31.apex"
VNDK_APEX_PATTERN = "com.android.vndk.v*.apex"
EXPECTED_VNDK31_ELF_PER_ABI = 134
# Kept as a public compatibility alias for the original unit tests and any
# external callers that imported the constant before ELF64 support existed.
EXPECTED_VNDK31_ELF32 = EXPECTED_VNDK31_ELF_PER_ABI
RUNTIME_EXTERNAL_LIBRARIES = frozenset(
    {"libc.so", "libdl.so", "libdl_android.so", "libm.so"}
)


class ValidationError(RuntimeError):
    """Raised when an input cannot be inspected safely."""


@dataclass(frozen=True)
class CheckResult:
    check_id: str
    ok: bool
    detail: str


@dataclass(frozen=True)
class VersionedImport:
    symbol: str
    version: str
    needed: str | None


@dataclass(frozen=True)
class SymbolTable:
    bases: frozenset[str]
    exact_versions: frozenset[tuple[str, str]]


@dataclass(frozen=True)
class ApexPayload:
    archive: Path
    manifest_name: str | None
    payload_root: Path | None
    sha256: str
    error: str | None = None


@dataclass(frozen=True)
class Provider:
    namespace: str
    path: Path
    display_path: str


@dataclass(frozen=True)
class DependencyIssue:
    root: str
    consumer: str
    context: str
    needed: str
    candidates: tuple[str, ...] = ()
    detail: str = ""


@dataclass(frozen=True)
class DuplicateRoute:
    root: str
    consumer: str
    needed: str
    selected: str
    candidates: tuple[str, ...]


@dataclass(frozen=True)
class VersionIssue:
    root: str
    consumer: str
    needed: str | None
    symbol: str
    version: str
    provider: str | None
    detail: str


@dataclass(frozen=True)
class SymbolIssue:
    root: str
    consumer: str
    symbol: str
    detail: str


@dataclass
class RootReport:
    executable: str
    interpreter: str
    interpreter_ok: bool
    interpreter_detail: str
    loaded_elfs: int = 0
    needed_edges: int = 0
    versioned_imports: int = 0
    exact_versioned_imports: int = 0
    unversioned_imports: int = 0
    resolved_unversioned_imports: int = 0
    missing: list[DependencyIssue] = field(default_factory=list)
    namespace_blocked: list[DependencyIssue] = field(default_factory=list)
    duplicate_routes: list[DuplicateRoute] = field(default_factory=list)
    version_missing: list[VersionIssue] = field(default_factory=list)
    version_fallbacks: list[VersionIssue] = field(default_factory=list)
    unversioned_missing: list[SymbolIssue] = field(default_factory=list)
    analysis_errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(
            self.interpreter_ok
            and not self.missing
            and not self.namespace_blocked
            and not self.version_missing
            and not self.unversioned_missing
            and not self.analysis_errors
        )


@dataclass
class ValidationReport:
    work_dir: str
    bitness: int = 32
    checks: list[CheckResult] = field(default_factory=list)
    roots: list[RootReport] = field(default_factory=list)

    def add_check(self, check_id: str, ok: bool, detail: str) -> None:
        self.checks.append(CheckResult(check_id, ok, detail))

    @property
    def ok(self) -> bool:
        return bool(
            self.checks
            and all(check.ok for check in self.checks)
            and self.roots
            and all(root.ok for root in self.roots)
        )

    def to_dict(self) -> dict[str, object]:
        missing = sum(len(root.missing) for root in self.roots)
        blocked = sum(len(root.namespace_blocked) for root in self.roots)
        duplicate = sum(len(root.duplicate_routes) for root in self.roots)
        version_missing = sum(len(root.version_missing) for root in self.roots)
        unversioned_missing = sum(
            len(root.unversioned_missing) for root in self.roots
        )
        fallbacks = sum(len(root.version_fallbacks) for root in self.roots)
        return {
            "ok": self.ok,
            "work_dir": self.work_dir,
            "elf_bitness": self.bitness,
            "summary": {
                "checks_passed": sum(check.ok for check in self.checks),
                "checks_failed": sum(not check.ok for check in self.checks),
                "executables": len(self.roots),
                "missing": missing,
                "namespace_blocked": blocked,
                "duplicate_routes": duplicate,
                "version_missing": version_missing,
                "unversioned_missing": unversioned_missing,
                "version_fallbacks": fallbacks,
            },
            "checks": [asdict(check) for check in self.checks],
            "roots": [asdict(root) | {"ok": root.ok} for root in self.roots],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True)

    def to_text(self) -> str:
        lines = [
            f"ELF{self.bitness} closure validation: "
            f"{'PASS' if self.ok else 'FAIL'}",
            f"Work dir: {self.work_dir}",
            "",
        ]
        for check in self.checks:
            lines.append(
                f"[{'PASS' if check.ok else 'FAIL'}] {check.check_id}: "
                f"{check.detail}"
            )
        for root in self.roots:
            lines.extend(
                (
                    "",
                    f"[{'PASS' if root.ok else 'FAIL'}] {root.executable}",
                    f"  interpreter: {root.interpreter_detail}",
                    f"  closure: {root.loaded_elfs} ELF, "
                    f"{root.needed_edges} DT_NEEDED edges",
                    f"  symbols: {root.exact_versioned_imports}/"
                    f"{root.versioned_imports} exact, "
                    f"{root.resolved_unversioned_imports}/"
                    f"{root.unversioned_imports} strong unversioned, "
                    f"{len(root.version_fallbacks)} base fallbacks",
                )
            )
            for issue in root.missing:
                lines.append(
                    f"  MISSING: {issue.consumer} -> {issue.needed} "
                    f"({issue.detail})"
                )
            for issue in root.namespace_blocked:
                lines.append(
                    f"  NAMESPACE-BLOCKED: {issue.consumer} -> {issue.needed}; "
                    f"candidates={', '.join(issue.candidates)}"
                )
            for warning in root.duplicate_routes:
                lines.append(
                    f"  DUPLICATE-ROUTE: {warning.consumer} -> "
                    f"{warning.needed}; selected={warning.selected}; "
                    f"candidates={', '.join(warning.candidates)}"
                )
            for issue in root.version_missing:
                lines.append(
                    f"  SYMBOL-MISSING: {issue.symbol}@{issue.version} "
                    f"for {issue.consumer} ({issue.detail})"
                )
            for issue in root.unversioned_missing:
                lines.append(
                    f"  UNVERSIONED-SYMBOL-MISSING: {issue.symbol} "
                    f"for {issue.consumer} ({issue.detail})"
                )
            for warning in root.version_fallbacks:
                lines.append(
                    f"  SYMBOL-FALLBACK: {warning.symbol}@{warning.version} "
                    f"for {warning.consumer}; provider={warning.provider}"
                )
            for error in root.analysis_errors:
                lines.append(f"  ANALYSIS-ERROR: {error}")
        summary = self.to_dict()["summary"]
        assert isinstance(summary, dict)
        lines.extend(
            (
                "",
                "Summary: "
                f"{summary['executables']} executables, "
                f"{summary['missing']} missing, "
                f"{summary['namespace_blocked']} namespace-blocked, "
                f"{summary['duplicate_routes']} duplicate-route warnings, "
                f"{summary['version_missing']} missing versioned symbols, "
                f"{summary['unversioned_missing']} missing strong "
                "unversioned symbols, "
                f"{summary['version_fallbacks']} base-symbol fallbacks",
            )
        )
        return "\n".join(lines)


class ElfToolchain:
    """Read dynamic-link metadata with host binutils."""

    def __init__(
        self,
        readelf: str | None = None,
        nm: str | None = None,
        *,
        bitness: int = 32,
    ) -> None:
        if bitness not in {32, 64}:
            raise ValueError(f"unsupported ELF bitness: {bitness}")
        self.bitness = bitness
        self.readelf = readelf or shutil.which("readelf")
        self.nm = nm or shutil.which("nm")
        self._needed: dict[Path, tuple[str, ...]] = {}
        self._interpreter: dict[Path, str | None] = {}
        self._imports: dict[Path, tuple[VersionedImport, ...]] = {}
        self._unversioned_imports: dict[Path, tuple[str, ...]] = {}
        self._symbols: dict[Path, SymbolTable] = {}

    def availability_errors(self) -> list[str]:
        errors: list[str] = []
        if not self.readelf:
            errors.append("readelf was not found")
        if not self.nm:
            errors.append("nm was not found")
        return errors

    @staticmethod
    def _is_elf(path: Path, elf_class: int, machine: int) -> bool:
        try:
            with path.open("rb") as stream:
                header = stream.read(20)
        except OSError:
            return False
        if (
            len(header) < 20
            or header[:4] != b"\x7fELF"
            or header[4] != elf_class
        ):
            return False
        byte_order = {1: "<", 2: ">"}.get(header[5])
        if byte_order is None:
            return False
        return struct.unpack(f"{byte_order}H", header[18:20])[0] == machine

    @staticmethod
    def is_elf32_arm(path: Path) -> bool:
        return ElfToolchain._is_elf(path, 1, EM_ARM)

    @staticmethod
    def is_elf64_aarch64(path: Path) -> bool:
        return ElfToolchain._is_elf(path, 2, EM_AARCH64)

    def is_target_elf(self, path: Path) -> bool:
        if self.bitness == 64:
            return self.is_elf64_aarch64(path)
        return self.is_elf32_arm(path)

    def _run(self, executable: str | None, arguments: Sequence[str]) -> str:
        if not executable:
            raise ValidationError("required ELF inspection tool is unavailable")
        result = subprocess.run(
            (executable, *arguments),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            raise ValidationError(
                f"{' '.join((executable, *arguments))} exited "
                f"{result.returncode}: {detail}"
            )
        return result.stdout

    def interpreter(self, path: Path) -> str | None:
        if path not in self._interpreter:
            output = self._run(self.readelf, ("-lW", str(path)))
            match = re.search(
                r"Requesting program interpreter:\s*([^\]]+)\]", output
            )
            self._interpreter[path] = match.group(1).strip() if match else None
        return self._interpreter[path]

    def needed(self, path: Path) -> tuple[str, ...]:
        if path not in self._needed:
            output = self._run(self.readelf, ("-dW", str(path)))
            self._needed[path] = tuple(
                re.findall(r"\(NEEDED\).*?\[(.*?)\]", output)
            )
        return self._needed[path]

    def versioned_imports(self, path: Path) -> tuple[VersionedImport, ...]:
        if path in self._imports:
            return self._imports[path]
        version_output = self._run(self.readelf, ("-VW", str(path)))
        index_to_file: dict[int, str] = {}
        in_needs = False
        current_file: str | None = None
        for line in version_output.splitlines():
            if line.startswith("Version needs section"):
                in_needs = True
                current_file = None
                continue
            if line.startswith(("Version definition section", "Version symbols section")):
                in_needs = False
                current_file = None
                continue
            if not in_needs:
                continue
            file_match = re.search(r"\bFile: (\S+)", line)
            if file_match:
                current_file = file_match.group(1)
                continue
            version_match = re.search(
                r"\bName: (\S+).*\bVersion: (\d+)", line
            )
            if version_match and current_file:
                index_to_file[int(version_match.group(2))] = current_file

        symbol_output = self._run(self.readelf, ("--dyn-syms", "-W", str(path)))
        imports: list[VersionedImport] = []
        for line in symbol_output.splitlines():
            match = re.search(
                r"\s(?:GLOBAL|WEAK)\s+\S+\s+UND\s+"
                r"(\S+?)(?:\s+\((\d+)\))?\s*$",
                line,
            )
            if not match or "@" not in match.group(1):
                continue
            # Weak undefined symbols are allowed to remain unresolved.
            if re.search(r"\sWEAK\s+\S+\s+UND\s+", line):
                continue
            symbol, version = match.group(1).split("@", 1)
            version_index = int(match.group(2)) if match.group(2) else None
            imports.append(
                VersionedImport(
                    symbol=symbol,
                    version=version.lstrip("@"),
                    needed=index_to_file.get(version_index) if version_index else None,
                )
            )
        self._imports[path] = tuple(imports)
        return self._imports[path]

    def strong_unversioned_imports(self, path: Path) -> tuple[str, ...]:
        """Return strong dynamic imports that carry no ELF symbol version."""
        if path in self._unversioned_imports:
            return self._unversioned_imports[path]
        output = self._run(self.readelf, ("--dyn-syms", "-W", str(path)))
        imports: list[str] = []
        for line in output.splitlines():
            fields = line.split()
            if (
                len(fields) < 8
                or not fields[0].rstrip(":").isdigit()
                or fields[6] != "UND"
                or fields[4] not in {"GLOBAL", "GNU_UNIQUE"}
            ):
                continue
            name = fields[7]
            if "@" not in name:
                imports.append(name)
        self._unversioned_imports[path] = tuple(imports)
        return self._unversioned_imports[path]

    def defined_symbols(self, path: Path) -> SymbolTable:
        if path in self._symbols:
            return self._symbols[path]
        output = self._run(self.nm, ("-D", "--defined-only", str(path)))
        bases: set[str] = set()
        exact: set[tuple[str, str]] = set()
        for line in output.splitlines():
            fields = line.split()
            if not fields:
                continue
            name = fields[-1]
            if "@@" in name:
                base, version = name.split("@@", 1)
                bases.add(base)
                exact.add((base, version))
            elif "@" in name:
                base, version = name.split("@", 1)
                version = version.lstrip("@")
                exact.add((base, version))
            else:
                bases.add(name)
        table = SymbolTable(frozenset(bases), frozenset(exact))
        self._symbols[path] = table
        return table


def _toolchain_bitness(toolchain: object) -> int:
    """Return the selected ABI while preserving old fake-toolchain callers."""
    bitness = getattr(toolchain, "bitness", 32)
    if bitness not in {32, 64}:
        raise ValidationError(f"unsupported ELF bitness: {bitness}")
    return bitness


def _target_lib_dir(toolchain: object) -> str:
    return "lib64" if _toolchain_bitness(toolchain) == 64 else "lib"


def _target_linker(toolchain: object) -> str:
    return "linker64" if _toolchain_bitness(toolchain) == 64 else "linker"


def _target_arch_label(toolchain: object) -> str:
    return (
        "AArch64 ELF64"
        if _toolchain_bitness(toolchain) == 64
        else "ARM ELF32"
    )


def _is_target_elf(toolchain: object, path: Path) -> bool:
    checker = getattr(toolchain, "is_target_elf", None)
    if checker is not None:
        return bool(checker(path))
    # Compatibility for the synthetic pre-ELF64 test toolchain.
    return bool(getattr(toolchain, "is_elf32_arm")(path))


def _decode_varint(data: bytes, offset: int) -> tuple[int, int]:
    value = 0
    shift = 0
    while offset < len(data) and shift < 70:
        byte = data[offset]
        offset += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, offset
        shift += 7
    raise ValidationError("truncated or overlong protobuf varint")


def parse_apex_manifest_name(data: bytes) -> str:
    offset = 0
    name: str | None = None
    version: int | None = None
    while offset < len(data):
        key, offset = _decode_varint(data, offset)
        field_number = key >> 3
        wire_type = key & 7
        if wire_type == 0:
            value, offset = _decode_varint(data, offset)
            if field_number == 2:
                if version is not None:
                    raise ValidationError("APEX manifest has duplicate version")
                version = value
        elif wire_type == 1:
            offset += 8
        elif wire_type == 2:
            length, offset = _decode_varint(data, offset)
            end = offset + length
            if end > len(data):
                raise ValidationError("truncated APEX manifest field")
            value = data[offset:end]
            offset = end
            if field_number == 1:
                if name is not None:
                    raise ValidationError("APEX manifest has duplicate package name")
                try:
                    name = value.decode("utf-8")
                except UnicodeDecodeError as error:
                    raise ValidationError("APEX manifest name is not UTF-8") from error
        elif wire_type == 5:
            offset += 4
        else:
            raise ValidationError(f"unsupported protobuf wire type {wire_type}")
        if offset > len(data):
            raise ValidationError("truncated APEX manifest")
    if not name:
        raise ValidationError("APEX manifest has no package name")
    if version is None:
        raise ValidationError("APEX manifest has no version")
    return name


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def inspect_apex(
    archive: Path,
    label: str,
    temporary_root: Path,
    *,
    debugfs: str | None = None,
    avbtool: str | None = None,
) -> ApexPayload:
    """Authenticate, CRC-check, and extract an APEX without mounting it."""
    try:
        sha256 = _sha256_file(archive) if archive.is_file() else ""
    except OSError as error:
        return ApexPayload(archive, None, None, "", f"cannot hash APEX: {error}")
    if not archive.is_file():
        return ApexPayload(archive, None, None, sha256, "archive is missing")
    outer = temporary_root / label / "outer"
    payload_root = temporary_root / label / "payload"
    outer.mkdir(parents=True, exist_ok=True)
    payload_root.mkdir(parents=True, exist_ok=True)
    required = ("apex_payload.img", "apex_pubkey", "apex_manifest.pb")
    try:
        with zipfile.ZipFile(archive) as apex:
            names = apex.namelist()
            duplicate = [name for name in required if names.count(name) != 1]
            if duplicate:
                return ApexPayload(
                    archive,
                    None,
                    None,
                    sha256,
                    "missing/duplicate critical members: " + ", ".join(duplicate),
                )
            bad_member = apex.testzip()
            if bad_member:
                return ApexPayload(
                    archive, None, None, sha256, f"CRC failed for {bad_member}"
                )
            for member in required:
                apex.extract(member, outer)
    except (
        OSError,
        RuntimeError,
        NotImplementedError,
        zipfile.BadZipFile,
        zipfile.LargeZipFile,
    ) as error:
        return ApexPayload(archive, None, None, sha256, f"invalid APEX ZIP: {error}")

    try:
        outer_manifest = (outer / "apex_manifest.pb").read_bytes()
        outer_pubkey = (outer / "apex_pubkey").read_bytes()
        manifest_name = parse_apex_manifest_name(outer_manifest)
    except (OSError, ValidationError) as error:
        return ApexPayload(archive, None, None, sha256, str(error))

    if avbtool is None:
        repo_root = Path(__file__).resolve().parents[2]
        avb_candidates = (
            repo_root / "out/tools/bin/avbtool",
            repo_root / "external/android-tools/vendor/avb/avbtool.py",
        )
        avbtool = next(
            (
                str(candidate)
                for candidate in avb_candidates
                if candidate.is_file() and os.access(candidate, os.X_OK)
            ),
            None,
        ) or shutil.which("avbtool")
    if not avbtool:
        return ApexPayload(archive, manifest_name, None, sha256, "avbtool not found")

    payload_image = outer / "apex_payload.img"
    try:
        verify_result = subprocess.run(
            (avbtool, "verify_image", "--image", str(payload_image)),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        info_result = subprocess.run(
            (avbtool, "info_image", "--image", str(payload_image)),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    except OSError as error:
        return ApexPayload(
            archive, manifest_name, None, sha256, f"cannot run avbtool: {error}"
        )
    if verify_result.returncode != 0:
        detail = (verify_result.stderr or verify_result.stdout).strip()
        return ApexPayload(
            archive,
            manifest_name,
            None,
            sha256,
            f"APEX payload AVB verification failed: {detail}",
        )
    info = "\n".join((info_result.stdout, info_result.stderr))
    key_match = re.search(r"Public key \(sha1\):\s*([0-9a-fA-F]{40})", info)
    embedded_key_sha1 = key_match.group(1).lower() if key_match else None
    outer_key_sha1 = hashlib.sha1(outer_pubkey).hexdigest()
    if info_result.returncode != 0 or embedded_key_sha1 != outer_key_sha1:
        return ApexPayload(
            archive,
            manifest_name,
            None,
            sha256,
            "APEX payload key mismatch: "
            f"outer={outer_key_sha1}, embedded={embedded_key_sha1 or '<missing>'}",
        )

    debugfs_path = debugfs or shutil.which("debugfs")
    if not debugfs_path:
        return ApexPayload(archive, manifest_name, None, sha256, "debugfs not found")
    try:
        result = subprocess.run(
            (
                debugfs_path,
                "-R",
                f"rdump / {payload_root}",
                str(payload_image),
            ),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    except OSError as error:
        return ApexPayload(
            archive, manifest_name, None, sha256, f"cannot run debugfs: {error}"
        )
    inner_manifest = payload_root / "apex_manifest.pb"
    if result.returncode != 0 or not inner_manifest.is_file():
        detail = (result.stderr or result.stdout).strip()
        return ApexPayload(
            archive,
            manifest_name,
            None,
            sha256,
            detail or "debugfs did not extract the payload",
        )
    try:
        inner_manifest_bytes = inner_manifest.read_bytes()
    except OSError as error:
        return ApexPayload(
            archive,
            manifest_name,
            None,
            sha256,
            f"cannot read inner APEX manifest: {error}",
        )
    if inner_manifest_bytes != outer_manifest:
        return ApexPayload(
            archive,
            manifest_name,
            None,
            sha256,
            "inner and outer apex_manifest.pb differ",
        )
    return ApexPayload(archive, manifest_name, payload_root, sha256)


ApexInspector = Callable[[Path, str, Path], ApexPayload]


def _system_root(root: Path) -> Path:
    for relative in ("system/system", "system"):
        candidate = root / relative
        if candidate.is_dir() and (candidate / "lib").exists():
            return candidate
    return root / "system/system"


def _system_ext_root(root: Path) -> Path:
    for relative in (
        "system/system/system_ext",
        "system_ext",
        "system/system_ext",
    ):
        candidate = root / relative
        if candidate.is_dir():
            return candidate
    return root / "system/system/system_ext"


def _find_unique(root: Path, name: str) -> list[Path]:
    return sorted(
        path for path in root.rglob(name) if path.is_file() or path.is_symlink()
    )


def _read_property_values(path: Path, key: str) -> list[str]:
    if not path.is_file():
        return []
    values: list[str] = []
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        candidate, value = line.split("=", 1)
        if candidate.strip() == key:
            values.append(value.strip())
    return values


def _vendor_ndk_versions(path: Path) -> list[str]:
    if not path.is_file():
        return []
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError):
        return []
    versions: list[str] = []
    for vendor_ndk in root.iter():
        if vendor_ndk.tag.rsplit("}", 1)[-1] != "vendor-ndk":
            continue
        versions.extend(
            (child.text or "").strip()
            for child in vendor_ndk
            if child.tag.rsplit("}", 1)[-1] == "version"
        )
    return versions


def _has_vendor_ndk(path: Path, version: str) -> bool:
    return _vendor_ndk_versions(path) == [version]


def _display_work_path(path: Path, work_dir: Path) -> str:
    try:
        return str(path.relative_to(work_dir))
    except ValueError:
        return str(path)


def _provider_display(prefix: str, path: Path, base: Path) -> str:
    relative = path.relative_to(base)
    return f"{prefix}/{relative}"


def _iter_files(root: Path, *, recursive: bool) -> Iterable[Path]:
    if not root.is_dir():
        return ()
    paths = root.rglob("*") if recursive else root.iterdir()
    return sorted(
        paths,
        key=lambda path: (
            len(path.relative_to(root).parts),
            str(path.relative_to(root)),
        ),
    )


def _resolve_android_file(
    path: Path,
    work_dir: Path,
    system_root: Path,
    apexes: Mapping[str, ApexPayload],
) -> Path | None:
    """Resolve Android absolute symlinks inside an unpacked work directory."""
    runtime_root = apexes["runtime"].payload_root
    i18n_root = apexes["i18n"].payload_root
    vndk_root = apexes["vndk"].payload_root
    product_roots = (
        work_dir / "product",
        system_root / "product",
        work_dir / "system/product",
    )
    product_root = next(
        (candidate for candidate in product_roots if candidate.exists()),
        product_roots[0],
    )
    mappings: list[tuple[str, Path | None]] = [
        ("/apex/com.android.runtime", runtime_root),
        ("/apex/com.android.i18n", i18n_root),
        ("/apex/com.android.vndk.v31", vndk_root),
        ("/system_ext", _system_ext_root(work_dir)),
        ("/vendor", work_dir / "vendor"),
        ("/product", product_root),
        ("/odm", work_dir / "odm"),
        ("/system", system_root),
    ]

    current = path
    seen: set[Path] = set()
    for _ in range(16):
        if current in seen:
            return None
        seen.add(current)
        if not current.is_symlink():
            return current if current.is_file() else None
        try:
            target = os.readlink(current)
        except OSError:
            return None
        if not target.startswith("/"):
            current = current.parent / target
            continue
        mapped: Path | None = None
        for prefix, root in mappings:
            if root is None:
                continue
            if target == prefix or target.startswith(prefix + "/"):
                mapped = root / target.removeprefix(prefix).lstrip("/")
                break
        if mapped is None:
            return None
        current = mapped
    return None


@dataclass
class ProviderIndex:
    by_namespace: dict[str, dict[str, list[Provider]]]
    all_by_name: dict[str, list[Provider]]


def build_provider_index(
    work_dir: Path,
    system_root: Path,
    apexes: Mapping[str, ApexPayload],
    toolchain: ElfToolchain,
) -> ProviderIndex:
    lib_dir = _target_lib_dir(toolchain)
    vendor_lib = work_dir / "vendor" / lib_dir
    odm_lib = work_dir / "odm" / lib_dir
    system_ext_lib = _system_ext_root(work_dir) / lib_dir
    product_lib_candidates = (
        work_dir / "product" / lib_dir,
        work_dir / "system/system/product" / lib_dir,
        work_dir / "system/product" / lib_dir,
    )
    namespace_roots: dict[str, list[tuple[Path, bool, str]]] = {
        # These are explicit vendor-default search paths, not a recursive walk.
        "vendor": [
            (odm_lib, False, f"/odm/{lib_dir}"),
            (vendor_lib, False, f"/vendor/{lib_dir}"),
            (vendor_lib / "hw", False, f"/vendor/{lib_dir}/hw"),
            (vendor_lib / "egl", False, f"/vendor/{lib_dir}/egl"),
        ],
        # bootstrap/ is not an Android default namespace search directory.
        "system": [
            (system_root / lib_dir, False, f"/system/{lib_dir}"),
            (system_ext_lib, False, f"/system_ext/{lib_dir}"),
            *(
                (path, False, f"/product/{lib_dir}")
                for path in product_lib_candidates
            ),
        ],
        "runtime": [],
        "i18n": [],
        # Local VNDK extensions precede the matching APEX, but remain in the
        # VNDK namespace so the core/SP export gate and child context apply.
        "vndk": [
            (odm_lib / "vndk-sp", False, f"/odm/{lib_dir}/vndk-sp"),
            (vendor_lib / "vndk-sp", False, f"/vendor/{lib_dir}/vndk-sp"),
            (odm_lib / "vndk", False, f"/odm/{lib_dir}/vndk"),
            (vendor_lib / "vndk", False, f"/vendor/{lib_dir}/vndk"),
        ],
    }
    runtime_root = apexes["runtime"].payload_root
    i18n_root = apexes["i18n"].payload_root
    vndk_root = apexes["vndk"].payload_root
    if runtime_root:
        namespace_roots["runtime"].append(
            (
                runtime_root / lib_dir,
                True,
                f"/apex/com.android.runtime/{lib_dir}",
            )
        )
    if i18n_root:
        namespace_roots["i18n"].append(
            (i18n_root / lib_dir, False, f"/apex/com.android.i18n/{lib_dir}")
        )
    if vndk_root:
        namespace_roots["vndk"].append(
            (
                vndk_root / lib_dir,
                False,
                f"/apex/com.android.vndk.v31/{lib_dir}",
            )
        )

    by_namespace: dict[str, dict[str, list[Provider]]] = {
        namespace: defaultdict(list) for namespace in namespace_roots
    }
    all_by_name: dict[str, list[Provider]] = defaultdict(list)
    claimed_paths: set[Path] = set()
    for namespace, roots in namespace_roots.items():
        for base, recursive, prefix in roots:
            for path in _iter_files(base, recursive=recursive):
                resolved = _resolve_android_file(
                    path, work_dir, system_root, apexes
                )
                if resolved is None or not _is_target_elf(toolchain, resolved):
                    continue
                provider = Provider(
                    namespace,
                    resolved,
                    _provider_display(prefix, path, base),
                )
                by_namespace[namespace][path.name].append(provider)
                all_by_name[path.name].append(provider)
                claimed_paths.add(path)

    # Keep resolution constrained to the explicit roots above, while taking a
    # recursive census for diagnostics.  A provider that physically exists in
    # a private/dlopen-only subdirectory is namespace-blocked, not missing.
    census_roots: list[tuple[str, Path, str]] = [
        ("vndk", odm_lib / "vndk-sp", f"/odm/{lib_dir}/vndk-sp"),
        ("vndk", vendor_lib / "vndk-sp", f"/vendor/{lib_dir}/vndk-sp"),
        ("vndk", odm_lib / "vndk", f"/odm/{lib_dir}/vndk"),
        ("vndk", vendor_lib / "vndk", f"/vendor/{lib_dir}/vndk"),
        ("vendor", odm_lib, f"/odm/{lib_dir}"),
        ("vendor", vendor_lib, f"/vendor/{lib_dir}"),
        ("system", system_root / lib_dir, f"/system/{lib_dir}"),
        ("system", system_ext_lib, f"/system_ext/{lib_dir}"),
        *(
            ("system", path, f"/product/{lib_dir}")
            for path in product_lib_candidates
        ),
    ]
    if runtime_root:
        census_roots.append(
            (
                "runtime",
                runtime_root / lib_dir,
                f"/apex/com.android.runtime/{lib_dir}",
            )
        )
    if i18n_root:
        census_roots.append(
            (
                "i18n",
                i18n_root / lib_dir,
                f"/apex/com.android.i18n/{lib_dir}",
            )
        )
    if vndk_root:
        census_roots.append(
            (
                "vndk",
                vndk_root / lib_dir,
                f"/apex/com.android.vndk.v31/{lib_dir}",
            )
        )
    for namespace, base, prefix in census_roots:
        for path in _iter_files(base, recursive=True):
            if path in claimed_paths:
                continue
            resolved = _resolve_android_file(path, work_dir, system_root, apexes)
            if resolved is None or not _is_target_elf(toolchain, resolved):
                continue
            provider = Provider(
                namespace, resolved, _provider_display(prefix, path, base)
            )
            all_by_name[path.name].append(provider)
            claimed_paths.add(path)
    return ProviderIndex(
        {namespace: dict(values) for namespace, values in by_namespace.items()},
        dict(all_by_name),
    )


@dataclass(frozen=True)
class NamespacePolicy:
    vndk_exports: frozenset[str]
    system_exports: frozenset[str]
    runtime_exports: frozenset[str]


class Resolver:
    def __init__(self, providers: ProviderIndex, policy: NamespacePolicy) -> None:
        self.providers = providers
        self.policy = policy

    def accessible(self, context: str, needed: str) -> list[Provider]:
        order = {
            "vendor": ("vendor", "vndk", "runtime", "system", "i18n"),
            "vndk": ("vndk", "vendor", "runtime", "system", "i18n"),
            "system": ("system", "runtime", "i18n"),
            "runtime": ("runtime", "system"),
            "i18n": ("i18n", "runtime", "system"),
        }[context]
        candidates: list[Provider] = []
        seen: set[tuple[str, Path]] = set()
        for namespace in order:
            providers = self.providers.by_namespace.get(namespace, {}).get(
                needed, []
            )
            if not providers:
                continue
            if context == "vendor" and namespace == "vndk":
                if needed not in self.policy.vndk_exports:
                    continue
            if context != "runtime" and namespace == "runtime":
                if needed not in self.policy.runtime_exports:
                    continue
            if context in {"vendor", "vndk"} and namespace in {"system", "i18n"}:
                if needed not in self.policy.system_exports:
                    continue
            for provider in providers:
                identity = (provider.namespace, provider.path)
                if identity in seen:
                    continue
                seen.add(identity)
                candidates.append(provider)
        return candidates

    def resolve(self, context: str, needed: str) -> tuple[Provider | None, list[Provider]]:
        candidates = self.accessible(context, needed)
        return (candidates[0] if candidates else None, candidates)


def _read_library_list(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    return {
        line.split()[0]
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }


def _read_linker_config_provides(path: Path) -> tuple[set[str], str | None]:
    """Read top-level LinkerConfig.provideLibs (protobuf field 3)."""
    if not path.is_file():
        return set(), "linker.config.pb is missing"
    try:
        data = path.read_bytes()
    except OSError as error:
        return set(), f"cannot read linker.config.pb: {error}"
    if not data:
        return set(), "linker.config.pb is empty"

    provides: set[str] = set()
    offset = 0
    try:
        while offset < len(data):
            key, offset = _decode_varint(data, offset)
            field_number = key >> 3
            wire_type = key & 7
            if field_number == 0:
                raise ValidationError("protobuf field number 0 is invalid")
            if wire_type == 0:
                _, offset = _decode_varint(data, offset)
            elif wire_type == 1:
                offset += 8
            elif wire_type == 2:
                length, offset = _decode_varint(data, offset)
                end = offset + length
                if end > len(data):
                    raise ValidationError("truncated length-delimited field")
                value = data[offset:end]
                offset = end
                if field_number == 3:
                    library = value.decode("utf-8")
                    if not re.fullmatch(r"[A-Za-z0-9_@.+-]+\.so", library):
                        raise ValidationError(
                            f"invalid provideLibs entry {library!r}"
                        )
                    provides.add(library)
            elif wire_type == 5:
                offset += 4
            else:
                raise ValidationError(f"unsupported protobuf wire type {wire_type}")
            if offset > len(data):
                raise ValidationError("truncated fixed-width field")
    except (UnicodeDecodeError, ValidationError) as error:
        return set(), f"invalid linker.config.pb: {error}"
    if not provides:
        return set(), "linker.config.pb has no provideLibs entries"
    return provides, None


def build_namespace_policy(
    system_root: Path, vndk_root: Path
) -> tuple[NamespacePolicy, dict[str, set[str]]]:
    etc = vndk_root / "etc"
    lists = {
        "llndk": _read_library_list(etc / "llndk.libraries.31.txt"),
        "core": _read_library_list(etc / "vndkcore.libraries.31.txt"),
        "private": _read_library_list(etc / "vndkprivate.libraries.31.txt"),
        "sp": _read_library_list(etc / "vndksp.libraries.31.txt"),
    }
    system_provides, _ = _read_linker_config_provides(
        system_root / "etc/linker.config.pb"
    )
    lists["system_provides"] = system_provides
    # The binary linker config contains library names for many unrelated
    # namespaces.  Treating every .so string in it as a vendor export silently
    # turns private system libraries into false providers.  The VNDK31 LLNDK
    # list is the authoritative vendor/system contract; ld-android is the one
    # bionic implementation detail needed by the linked system group.
    system_exports = (lists["llndk"] & system_provides) | {"ld-android.so"}
    vndk_exports = (lists["core"] | lists["sp"]) - lists["private"]
    return (
        NamespacePolicy(
            frozenset(vndk_exports),
            frozenset(system_exports),
            RUNTIME_EXTERNAL_LIBRARIES,
        ),
        lists,
    )


def _find_vendor_interpreters(
    work_dir: Path, toolchain: ElfToolchain
) -> tuple[list[tuple[Path, str]], list[str]]:
    # Android vendor executables live below /vendor/bin (including bin/hw).
    # Some Samsung shared objects also carry a legacy PT_INTERP despite having
    # a SONAME and non-executable file mode, so scanning vendor/lib would turn
    # those data libraries into false process roots.
    vendor_root = work_dir / "vendor/bin"
    found: list[tuple[Path, str]] = []
    errors: list[str] = []
    if not vendor_root.is_dir():
        return found, ["vendor/bin is missing"]
    for path in sorted(vendor_root.rglob("*")):
        if not path.is_file() or not _is_target_elf(toolchain, path):
            continue
        try:
            interpreter = toolchain.interpreter(path)
        except ValidationError as error:
            errors.append(f"{_display_work_path(path, work_dir)}: {error}")
            continue
        if interpreter:
            found.append((path, interpreter))
    return found, errors


def _verify_interpreter(
    interpreter: str,
    work_dir: Path,
    system_root: Path,
    runtime_root: Path,
    toolchain: ElfToolchain,
) -> tuple[bool, str]:
    linker_name = _target_linker(toolchain)
    arch_label = _target_arch_label(toolchain)
    runtime_linker = runtime_root / "bin" / linker_name
    runtime_ok = runtime_linker.is_file() and _is_target_elf(
        toolchain, runtime_linker
    )
    if interpreter in {
        f"/system/bin/{linker_name}",
        f"/apex/com.android.runtime/bin/{linker_name}",
    }:
        if interpreter == f"/system/bin/{linker_name}":
            system_linker = system_root / "bin" / linker_name
            system_path = f"/system/bin/{linker_name}"
            if not (system_linker.exists() or system_linker.is_symlink()):
                return False, f"{system_path} is missing"
            if system_linker.is_symlink():
                target = os.readlink(system_linker)
                expected = f"/apex/com.android.runtime/bin/{linker_name}"
                if target != expected:
                    return False, f"{system_path} points to {target}"
            elif not _is_target_elf(toolchain, system_linker):
                return False, f"{system_path} is not an {arch_label} linker"
        if not runtime_ok:
            return False, (
                f"runtime APEX bin/{linker_name} is missing or not "
                f"{arch_label}"
            )
        return True, f"{interpreter} -> runtime APEX {arch_label} linker"

    partition_map = {
        "/vendor/": work_dir / "vendor",
        "/system/": system_root,
    }
    for prefix, root in partition_map.items():
        if interpreter.startswith(prefix):
            candidate = root / interpreter.removeprefix(prefix)
            ok = candidate.is_file() and _is_target_elf(toolchain, candidate)
            return ok, f"{interpreter}: {'valid' if ok else 'missing/invalid'}"
    return False, f"unsupported interpreter path {interpreter}"


def _provider_label(provider: Provider) -> str:
    return f"{provider.namespace}:{provider.display_path}"


def audit_executable(
    executable: Path,
    interpreter: str,
    work_dir: Path,
    system_root: Path,
    runtime_root: Path,
    resolver: Resolver,
    toolchain: ElfToolchain,
) -> RootReport:
    root_name = _display_work_path(executable, work_dir)
    interpreter_ok, interpreter_detail = _verify_interpreter(
        interpreter, work_dir, system_root, runtime_root, toolchain
    )
    report = RootReport(
        executable=root_name,
        interpreter=interpreter,
        interpreter_ok=interpreter_ok,
        interpreter_detail=interpreter_detail,
    )
    queue: deque[tuple[str, Path, str]] = deque()
    loaded: dict[tuple[str, Path], str] = {("vendor", executable): root_name}
    edges: set[tuple[str, Path, str]] = set()
    resolutions: dict[tuple[str, Path, str], Provider] = {}
    duplicate_keys: set[tuple[str, str, tuple[str, ...]]] = set()

    try:
        for needed in toolchain.needed(executable):
            queue.append(("vendor", executable, needed))
    except ValidationError as error:
        report.analysis_errors.append(f"{root_name}: {error}")

    while queue:
        context, consumer, needed = queue.popleft()
        edge = (context, consumer, needed)
        if edge in edges:
            continue
        edges.add(edge)
        consumer_name = loaded.get(
            (context, consumer), _display_work_path(consumer, work_dir)
        )
        selected, candidates = resolver.resolve(context, needed)
        if selected is None:
            existing = resolver.providers.all_by_name.get(needed, [])
            issue = DependencyIssue(
                root=root_name,
                consumer=consumer_name,
                context=context,
                needed=needed,
                candidates=tuple(_provider_label(item) for item in existing),
                detail=(
                    f"no {_target_arch_label(toolchain)} provider exists"
                    if not existing
                    else (
                        f"{_target_arch_label(toolchain)} provider exists only "
                        "outside the allowed namespace"
                    )
                ),
            )
            if existing:
                report.namespace_blocked.append(issue)
            else:
                report.missing.append(issue)
            continue

        resolutions[edge] = selected
        candidate_labels = tuple(_provider_label(item) for item in candidates)
        if len(candidates) > 1:
            duplicate_key = (needed, _provider_label(selected), candidate_labels)
            if duplicate_key not in duplicate_keys:
                duplicate_keys.add(duplicate_key)
                report.duplicate_routes.append(
                    DuplicateRoute(
                        root=root_name,
                        consumer=consumer_name,
                        needed=needed,
                        selected=_provider_label(selected),
                        candidates=candidate_labels,
                    )
                )

        loaded_key = (selected.namespace, selected.path)
        if loaded_key in loaded:
            continue
        loaded[loaded_key] = selected.display_path
        try:
            for child_needed in toolchain.needed(selected.path):
                queue.append((selected.namespace, selected.path, child_needed))
        except ValidationError as error:
            report.analysis_errors.append(f"{selected.display_path}: {error}")

    report.loaded_elfs = len(loaded)
    report.needed_edges = len(edges)

    # ELF version-needs records name the library that introduced a version,
    # but Android's dynamic linker still searches the complete loaded group for
    # the matching symbol.  That distinction matters in Samsung blobs: several
    # LIBBINDER-tagged android::base imports are supplied by loaded libbase.so,
    # not by the libbinder.so named in the version-needs record.
    exact_providers: dict[tuple[str, str], list[str]] = defaultdict(list)
    base_providers: dict[str, list[str]] = defaultdict(list)
    for (context, provider_path), provider_name in loaded.items():
        try:
            symbols = toolchain.defined_symbols(provider_path)
        except ValidationError as error:
            report.analysis_errors.append(f"{provider_name}: {error}")
            continue
        provider_label = f"{context}:{provider_name}"
        for symbol in symbols.bases:
            base_providers[symbol].append(provider_label)
        for exact_symbol in symbols.exact_versions:
            exact_providers[exact_symbol].append(provider_label)

    version_keys: set[tuple[str, str, str, str | None]] = set()
    for (context, consumer), consumer_name in loaded.items():
        try:
            imports = toolchain.versioned_imports(consumer)
        except ValidationError as error:
            report.analysis_errors.append(f"{consumer_name}: {error}")
            continue
        for imported in imports:
            report.versioned_imports += 1
            key = (
                consumer_name,
                imported.symbol,
                imported.version,
                imported.needed,
            )
            exact = exact_providers.get((imported.symbol, imported.version), [])
            if exact:
                report.exact_versioned_imports += 1
                continue

            selected: Provider | None = None
            if imported.needed is not None:
                selected = resolutions.get((context, consumer, imported.needed))
                if selected is None:
                    selected, _ = resolver.resolve(context, imported.needed)
            issue = VersionIssue(
                root=root_name,
                consumer=consumer_name,
                needed=imported.needed,
                symbol=imported.symbol,
                version=imported.version,
                provider=_provider_label(selected) if selected else None,
                detail="",
            )
            base = base_providers.get(imported.symbol, [])
            if base:
                issue = VersionIssue(
                    **{
                        **asdict(issue),
                        "provider": base[0],
                        "detail": (
                            "loaded namespace closure exports only the "
                            "unversioned base symbol"
                        ),
                    }
                )
                report.version_fallbacks.append(issue)
            elif key not in version_keys:
                version_keys.add(key)
                association = (
                    "version need has no associated DT_NEEDED; "
                    if imported.needed is None
                    else ""
                )
                issue = VersionIssue(
                    **{
                        **asdict(issue),
                        "detail": (
                            association
                            + "loaded namespace closure exports neither exact "
                            "nor base symbol"
                        ),
                    }
                )
                report.version_missing.append(issue)

    unversioned_keys: set[tuple[str, str]] = set()
    for (_, consumer), consumer_name in loaded.items():
        try:
            imports = toolchain.strong_unversioned_imports(consumer)
        except ValidationError as error:
            report.analysis_errors.append(f"{consumer_name}: {error}")
            continue
        for symbol in imports:
            report.unversioned_imports += 1
            if base_providers.get(symbol):
                report.resolved_unversioned_imports += 1
                continue
            key = (consumer_name, symbol)
            if key in unversioned_keys:
                continue
            unversioned_keys.add(key)
            report.unversioned_missing.append(
                SymbolIssue(
                    root=root_name,
                    consumer=consumer_name,
                    symbol=symbol,
                    detail="loaded namespace closure exports no default symbol",
                )
            )
    return report


def _apex_inspection_check(
    report: ValidationReport,
    label: str,
    apex: ApexPayload,
    expected_name: str,
) -> None:
    report.add_check(
        f"apex.{label}",
        apex.error is None
        and apex.payload_root is not None
        and apex.manifest_name == expected_name,
        (
            f"name={apex.manifest_name}, sha256={apex.sha256}"
            if apex.error is None and apex.manifest_name == expected_name
            else apex.error
            or f"manifest name={apex.manifest_name}, expected={expected_name}"
        ),
    )


def validate_work_dir(
    work_dir: Path,
    *,
    bitness: int = 32,
    multilib_firmware_dir: Path | None = None,
    vendor_dlopen_roots: Sequence[Path] = (),
    toolchain: ElfToolchain | None = None,
    apex_inspector: ApexInspector | None = None,
) -> ValidationReport:
    work_dir = work_dir.resolve()
    toolchain = toolchain or ElfToolchain(bitness=bitness)
    active_bitness = _toolchain_bitness(toolchain)
    report = ValidationReport(str(work_dir), bitness=active_bitness)
    apex_inspector = apex_inspector or (
        lambda archive, label, temporary: inspect_apex(archive, label, temporary)
    )
    if not work_dir.is_dir():
        report.add_check("work_dir", False, "assembled work dir is missing")
        return report
    report.add_check("work_dir", True, "assembled work dir exists")

    tool_errors = toolchain.availability_errors()
    report.add_check(
        "tools.elf",
        not tool_errors,
        "readelf and nm are available" if not tool_errors else "; ".join(tool_errors),
    )

    vendor_prop = work_dir / "vendor/build.prop"
    vndk_values = _read_property_values(vendor_prop, "ro.vndk.version")
    report.add_check(
        "vendor.ro_vndk_version",
        vndk_values == [EXPECTED_VNDK_VERSION],
        f"values={vndk_values or '<missing>'}, expected=['31']",
    )

    system_ext = _system_ext_root(work_dir)
    system_vintf = system_ext / "etc/vintf/manifest.xml"
    vendor_matrix = work_dir / "vendor/etc/vintf/compatibility_matrix.xml"
    system_vndk_versions = _vendor_ndk_versions(system_vintf)
    vendor_vndk_versions = _vendor_ndk_versions(vendor_matrix)
    report.add_check(
        "vintf.system_ext_vendor_ndk31",
        system_vndk_versions == [EXPECTED_VNDK_VERSION],
        f"{_display_work_path(system_vintf, work_dir)} versions="
        f"{system_vndk_versions or '<missing>'}, expected=['31']",
    )
    report.add_check(
        "vintf.vendor_matrix_ndk31",
        vendor_vndk_versions == [EXPECTED_VNDK_VERSION],
        f"{_display_work_path(vendor_matrix, work_dir)} versions="
        f"{vendor_vndk_versions or '<missing>'}, expected=['31']",
    )

    vndk_apexes = _find_unique(work_dir, VNDK_APEX_PATTERN)
    vndk_ok = len(vndk_apexes) == 1 and vndk_apexes[0].name == VNDK31_APEX
    report.add_check(
        "apex.vndk31_unique",
        vndk_ok,
        (
            _display_work_path(vndk_apexes[0], work_dir)
            if vndk_ok
            else "found: "
            + (", ".join(_display_work_path(path, work_dir) for path in vndk_apexes) or "none")
        ),
    )
    runtime_apexes = _find_unique(work_dir, RUNTIME_APEX)
    i18n_apexes = _find_unique(work_dir, I18N_APEX)
    report.add_check(
        "apex.runtime_unique",
        len(runtime_apexes) == 1,
        f"found {len(runtime_apexes)} {RUNTIME_APEX}",
    )
    report.add_check(
        "apex.i18n_unique",
        len(i18n_apexes) == 1,
        f"found {len(i18n_apexes)} {I18N_APEX}",
    )
    if not vndk_ok or len(runtime_apexes) != 1 or len(i18n_apexes) != 1:
        return report

    with tempfile.TemporaryDirectory(
        prefix=f"elf{active_bitness}-closure-apex-"
    ) as temporary:
        temporary_root = Path(temporary)
        apexes = {
            "runtime": apex_inspector(
                runtime_apexes[0], "runtime", temporary_root
            ),
            "i18n": apex_inspector(i18n_apexes[0], "i18n", temporary_root),
            "vndk": apex_inspector(vndk_apexes[0], "vndk31", temporary_root),
        }
        _apex_inspection_check(report, "runtime_payload", apexes["runtime"], "com.android.runtime")
        _apex_inspection_check(report, "i18n_payload", apexes["i18n"], "com.android.i18n")
        _apex_inspection_check(report, "vndk31_payload", apexes["vndk"], "com.android.vndk.v31")
        if any(apex.error or apex.payload_root is None for apex in apexes.values()):
            return report

        if multilib_firmware_dir is not None:
            firmware = multilib_firmware_dir.resolve()
            for label, filename, work_apex in (
                ("runtime", RUNTIME_APEX, runtime_apexes[0]),
                ("i18n", I18N_APEX, i18n_apexes[0]),
                ("vndk31", VNDK31_APEX, vndk_apexes[0]),
            ):
                providers = _find_unique(firmware, filename)
                same = bool(
                    len(providers) == 1
                    and _sha256_file(providers[0]) == _sha256_file(work_apex)
                )
                report.add_check(
                    f"provider_hash.{label}",
                    same,
                    (
                        f"work sha256={_sha256_file(work_apex)}, "
                        + (
                            f"provider sha256={_sha256_file(providers[0])}"
                            if len(providers) == 1
                            else f"provider candidates={len(providers)}"
                        )
                    ),
                )

        system_root = _system_root(work_dir)
        vndk_root = apexes["vndk"].payload_root
        runtime_root = apexes["runtime"].payload_root
        assert vndk_root is not None and runtime_root is not None
        policy, lists = build_namespace_policy(system_root, vndk_root)
        report.add_check(
            "vndk31.lists",
            all(lists[name] for name in ("llndk", "core", "private", "sp")),
            ", ".join(f"{name}={len(values)}" for name, values in lists.items()),
        )
        vndk_elf_count = sum(
            1
            for path in (vndk_root / _target_lib_dir(toolchain)).rglob("*")
            if path.is_file() and _is_target_elf(toolchain, path)
        )
        report.add_check(
            f"vndk31.elf{active_bitness}_count",
            vndk_elf_count == EXPECTED_VNDK31_ELF_PER_ABI,
            f"count={vndk_elf_count}, expected={EXPECTED_VNDK31_ELF_PER_ABI}",
        )
        linker_config = system_root / "etc/linker.config.pb"
        system_provides, linker_config_error = _read_linker_config_provides(
            linker_config
        )
        report.add_check(
            "namespace.system_linker_config",
            linker_config_error is None and bool(policy.system_exports),
            (
                f"provideLibs={len(system_provides)}, allowed system exports="
                f"{len(policy.system_exports)}"
                if linker_config_error is None
                else linker_config_error
            ),
        )

        providers = build_provider_index(
            work_dir, system_root, apexes, toolchain
        )
        resolver = Resolver(providers, policy)
        executables, discovery_errors = _find_vendor_interpreters(
            work_dir, toolchain
        )
        report.add_check(
            f"vendor.elf{active_bitness}_interpreters",
            bool(executables) and not discovery_errors,
            (
                f"found {len(executables)} ELF{active_bitness} executables "
                "with PT_INTERP"
                if not discovery_errors
                else "; ".join(discovery_errors)
            ),
        )
        audit_roots = list(executables)
        existing_roots = {path.resolve() for path, _ in audit_roots}
        vendor_root = (work_dir / "vendor").resolve()
        for index, requested_root in enumerate(vendor_dlopen_roots, start=1):
            requested = Path(requested_root)
            candidate = (
                requested.resolve()
                if requested.is_absolute()
                else (work_dir / requested).resolve()
            )
            try:
                candidate.relative_to(vendor_root)
                inside_vendor = True
            except ValueError:
                inside_vendor = False
            valid = bool(
                inside_vendor
                and candidate.is_file()
                and _is_target_elf(toolchain, candidate)
            )
            report.add_check(
                f"vendor.dlopen_root.{index}",
                valid,
                (
                    _display_work_path(candidate, work_dir)
                    if valid
                    else (
                        f"invalid {_target_arch_label(toolchain)} vendor root: "
                        f"{requested}"
                    )
                ),
            )
            if valid and candidate not in existing_roots:
                audit_roots.append(
                    (candidate, f"/system/bin/{_target_linker(toolchain)}")
                )
                existing_roots.add(candidate)

        for executable, interpreter in audit_roots:
            report.roots.append(
                audit_executable(
                    executable,
                    interpreter,
                    work_dir,
                    system_root,
                    runtime_root,
                    resolver,
                    toolchain,
                )
            )
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Validate assembled d2s ELF32/ELF64 DT_NEEDED and symbol closure"
        )
    )
    parser.add_argument("work_dir", type=Path)
    parser.add_argument(
        "--bitness",
        type=int,
        choices=(32, 64),
        default=32,
        help="target vendor ELF class (default: 32)",
    )
    parser.add_argument("--multilib-firmware-dir", type=Path)
    parser.add_argument(
        "--vendor-dlopen-root",
        action="append",
        default=[],
        type=Path,
        help=(
            "also audit a relative vendor shared object loaded at runtime; "
            "may be repeated"
        ),
    )
    parser.add_argument(
        "--json",
        nargs="?",
        const="-",
        metavar="PATH",
        help="emit JSON to stdout, or write it to PATH",
    )
    args = parser.parse_args(argv)
    report = validate_work_dir(
        args.work_dir,
        bitness=args.bitness,
        multilib_firmware_dir=args.multilib_firmware_dir,
        vendor_dlopen_roots=args.vendor_dlopen_root,
    )
    if args.json == "-":
        print(report.to_json())
    else:
        print(report.to_text())
        if args.json:
            output = Path(args.json)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(report.to_json() + "\n", encoding="utf-8")
            print(f"JSON report: {output}")
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
