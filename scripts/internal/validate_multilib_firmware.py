#!/usr/bin/env python3
"""Validate an API 36 Samsung multilib firmware before using its 32-bit layer.

The candidate firmware is expected to be an extracted Samsung firmware tree
(for example ``out/fw/SM-S711B_EUX``).  The reference tree is the extracted
main ROM donor.  This validator intentionally runs before any files are copied
into ``prebuilts`` or a work directory.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import mmap
import os
import re
import shutil
import struct
import subprocess
import tempfile
import zipfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Sequence


EXPECTED_API = "36"
EXPECTED_RELEASE = "16"
EXPECTED_CANDIDATE_SPEC = "SM-S711B/EUX/355195301615976"
EXPECTED_CANDIDATE_BUILD = (
    "S711BXXSGGZF2/S711BOXMGGZF2/S711BXXSGGZF2"
)
EXPECTED_CANDIDATE_MODEL = "SM-S711B"
EXPECTED_DONOR_SPEC = "SM-S721B/EUX/351273090276500"
EXPECTED_DONOR_BUILD = "S721BXXSCDZF3/S721BOXMCDZF3/S721BXXSCDZF3"
EXPECTED_DONOR_MODEL = "SM-S721B"
MIN_SYSTEM_LIB_ELF_COUNT = 700
MIN_SYSTEM_LIB_API36_NOTES = 650
EM_ARM = 40
EM_AARCH64 = 183

RUNTIME_APEX = "com.android.runtime.apex"
I18N_APEX = "com.android.i18n.apex"
VNDK31_APEX = "com.android.vndk.v31.apex"

RUNTIME_32_ELFS = (
    "bin/crash_dump32",
    "bin/linker",
    "lib/bionic/libc.so",
    "lib/bionic/libdl.so",
    "lib/bionic/libdl_android.so",
    "lib/bionic/libm.so",
    "lib/libc_malloc_debug.so",
    "lib/libc_malloc_hooks.so",
)
RUNTIME_64_ELFS = (
    "bin/crash_dump64",
    "bin/linker64",
    "bin/linkerconfig",
    "lib64/bionic/libc.so",
    "lib64/bionic/libdl.so",
    "lib64/bionic/libdl_android.so",
    "lib64/bionic/libm.so",
    "lib64/libc_malloc_debug.so",
    "lib64/libc_malloc_hooks.so",
)
RUNTIME_SYMLINKS = {
    "bin/linker_asan": "linker",
    "bin/linker_asan64": "linker64",
    "bin/linker_hwasan64": "linker64",
    "lib/ld-android.so": "/system/lib/ld-android.so",
    "lib/libbase.so": "/system/lib/libbase.so",
    "lib/libc++.so": "/system/lib/libc++.so",
    "lib/liblzma.so": "/system/lib/liblzma.so",
    "lib/libprocinfo.so": "/system/lib/libprocinfo.so",
    "lib/libunwindstack.so": "/system/lib/libunwindstack.so",
    "lib64/ld-android.so": "/system/lib64/ld-android.so",
    "lib64/libbase.so": "/system/lib64/libbase.so",
    "lib64/libc++.so": "/system/lib64/libc++.so",
    "lib64/liblzma.so": "/system/lib64/liblzma.so",
    "lib64/libprocinfo.so": "/system/lib64/libprocinfo.so",
    "lib64/libunwindstack.so": "/system/lib64/libunwindstack.so",
}
BOOTSTRAP_API_NOTE_ELFS = ("libc.so", "libm.so")
RUNTIME_32_API_NOTE_ELFS = (
    "bin/crash_dump32",
    "lib/bionic/libc.so",
    "lib/bionic/libm.so",
    "lib/libc_malloc_debug.so",
    "lib/libc_malloc_hooks.so",
)
I18N_LIBRARIES = (
    "libandroidicu.so",
    "libicu.so",
    "libicu_jni.so",
    "libicui18n.so",
    "libicuuc.so",
)
I18N_SYMLINKS = {
    "lib/libbase.so": "/system/lib/libbase.so",
    "lib/libc++.so": "/system/lib/libc++.so",
    "lib64/libbase.so": "/system/lib64/libbase.so",
    "lib64/libc++.so": "/system/lib64/libc++.so",
}
I18N_DATA_FILES = (
    "etc/icu/icudt76l.dat",
    "javalib/core-icu4j.jar",
)
VNDK31_LISTS = (
    "etc/llndk.libraries.31.txt",
    "etc/vndkcore.libraries.31.txt",
    "etc/vndkprivate.libraries.31.txt",
    "etc/vndkproduct.libraries.31.txt",
    "etc/vndksp.libraries.31.txt",
)
VNDK31_LIST_ENTRY_COUNTS = {
    "etc/llndk.libraries.31.txt": 23,
    "etc/vndkcore.libraries.31.txt": 99,
    "etc/vndkprivate.libraries.31.txt": 5,
    "etc/vndkproduct.libraries.31.txt": 73,
    "etc/vndksp.libraries.31.txt": 38,
}
VNDK31_EXPECTED_ELF_COUNT = 134
VNDK31_EXTERNAL_LIST_ENTRIES = {"libft2.so"}
BOOTSTRAP_LIBRARIES = (
    "libc.so",
    "libdl.so",
    "libdl_android.so",
    "libm.so",
)


@dataclass(frozen=True)
class ElfInfo:
    bits: int
    machine: int

    @property
    def machine_name(self) -> str:
        return {EM_ARM: "ARM", EM_AARCH64: "AArch64"}.get(
            self.machine, f"machine-{self.machine}"
        )


@dataclass(frozen=True)
class ApexManifestIdentity:
    name: str
    version: int


@dataclass
class CheckResult:
    check_id: str
    ok: bool
    detail: str


@dataclass
class ValidationReport:
    candidate: str
    donor: str
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.checks) and all(check.ok for check in self.checks)

    def add(self, check_id: str, ok: bool, detail: str) -> None:
        self.checks.append(CheckResult(check_id, ok, detail))

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "candidate": self.candidate,
            "donor": self.donor,
            "summary": {
                "passed": sum(check.ok for check in self.checks),
                "failed": sum(not check.ok for check in self.checks),
                "total": len(self.checks),
            },
            "checks": [asdict(check) for check in self.checks],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True)

    def to_text(self) -> str:
        state = "PASS" if self.ok else "FAIL"
        lines = [
            f"API 36 multilib firmware validation: {state}",
            f"Candidate: {self.candidate}",
            f"Main donor: {self.donor}",
            "",
        ]
        for check in self.checks:
            marker = "PASS" if check.ok else "FAIL"
            lines.append(f"[{marker}] {check.check_id}: {check.detail}")
        passed = sum(check.ok for check in self.checks)
        failed = len(self.checks) - passed
        lines.extend(("", f"Summary: {passed} passed, {failed} failed"))
        return "\n".join(lines)


@dataclass
class Toolchain:
    avbtool: str | None
    debugfs: str | None
    readelf: str | None
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run

    @classmethod
    def discover(cls) -> "Toolchain":
        repo_root = Path(__file__).resolve().parents[2]
        bundled_avbtool = repo_root / "out/tools/bin/avbtool"
        return cls(
            avbtool=(
                str(bundled_avbtool)
                if bundled_avbtool.is_file()
                else shutil.which("avbtool")
            ),
            debugfs=shutil.which("debugfs"),
            readelf=shutil.which("readelf"),
        )

    def run(self, args: Sequence[str]) -> subprocess.CompletedProcess[str]:
        command = list(args)
        try:
            return self.runner(
                command,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        except OSError as error:
            return subprocess.CompletedProcess(
                command,
                127,
                stdout="",
                stderr=f"could not execute {command[0]}: {error}",
            )


@dataclass
class ApexInspection:
    archive: Path
    zip_ok: bool = False
    zip_detail: str = "not inspected"
    avb_ok: bool = False
    avb_detail: str = "not inspected"
    avb_key_ok: bool = False
    avb_key_detail: str = "not inspected"
    payload_ok: bool = False
    payload_detail: str = "not inspected"
    pubkey_sha256: str | None = None
    manifest: ApexManifestIdentity | None = None
    manifest_sha256: str | None = None
    manifest_bytes: bytes | None = None
    payload_root: Path | None = None


class ManifestDecodeError(ValueError):
    pass


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
    raise ManifestDecodeError("truncated or overlong protobuf varint")


def parse_apex_manifest(data: bytes) -> ApexManifestIdentity:
    """Decode the stable name/version fields from apex_manifest.pb."""
    offset = 0
    name: str | None = None
    version: int | None = None
    while offset < len(data):
        key, offset = _decode_varint(data, offset)
        field_number = key >> 3
        wire_type = key & 0x07
        if wire_type == 0:
            value, offset = _decode_varint(data, offset)
            if field_number == 2:
                version = value
        elif wire_type == 1:
            offset += 8
        elif wire_type == 2:
            length, offset = _decode_varint(data, offset)
            end = offset + length
            if end > len(data):
                raise ManifestDecodeError("truncated length-delimited protobuf field")
            value = data[offset:end]
            offset = end
            if field_number == 1:
                try:
                    name = value.decode("utf-8")
                except UnicodeDecodeError as error:
                    raise ManifestDecodeError("manifest name is not UTF-8") from error
        elif wire_type == 5:
            offset += 4
        else:
            raise ManifestDecodeError(f"unsupported protobuf wire type {wire_type}")
        if offset > len(data):
            raise ManifestDecodeError("truncated protobuf field")
    if not name or version is None:
        raise ManifestDecodeError("manifest does not contain name and version")
    return ApexManifestIdentity(name=name, version=version)


def read_elf_info(path: Path) -> ElfInfo | None:
    try:
        with path.open("rb") as stream:
            header = stream.read(20)
    except OSError:
        return None
    if len(header) < 20 or header[:4] != b"\x7fELF":
        return None
    bits = {1: 32, 2: 64}.get(header[4])
    byte_order = {1: "<", 2: ">"}.get(header[5])
    if bits is None or byte_order is None:
        return None
    machine = struct.unpack(f"{byte_order}H", header[18:20])[0]
    return ElfInfo(bits=bits, machine=machine)


def read_android_api_levels(path: Path) -> set[int]:
    """Return Android NT_VERSION API levels embedded in an ELF.

    The Android note is deliberately parsed from its self-describing note
    record instead of trusting a filename or build property.  Scanning the
    mapped file also works for stripped Samsung binaries whose section table
    is absent while retaining the PT_NOTE payload.
    """
    info = read_elf_info(path)
    if info is None:
        return set()
    try:
        with path.open("rb") as stream, mmap.mmap(
            stream.fileno(), 0, access=mmap.ACCESS_READ
        ) as contents:
            byte_order = {1: "<", 2: ">"}.get(contents[5])
            if byte_order is None:
                return set()
            levels: set[int] = set()
            position = 0
            owner = b"Android\0"
            while True:
                owner_offset = contents.find(owner, position)
                if owner_offset < 0:
                    break
                position = owner_offset + 1
                note_offset = owner_offset - 12
                if note_offset < 0 or note_offset % 4:
                    continue
                namesz, descsz, note_type = struct.unpack(
                    f"{byte_order}III", contents[note_offset:owner_offset]
                )
                if namesz != len(owner) or descsz < 4 or note_type != 1:
                    continue
                description_offset = note_offset + 12 + ((namesz + 3) & ~3)
                if description_offset + descsz > len(contents):
                    continue
                level = struct.unpack(
                    f"{byte_order}I",
                    contents[description_offset : description_offset + 4],
                )[0]
                if 1 <= level <= 10000:
                    levels.add(level)
            return levels
    except (OSError, ValueError):
        return set()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def verify_zip_crc(path: Path) -> tuple[bool, str]:
    if not path.is_file():
        return False, f"archive is missing: {path}"
    try:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            duplicated = sorted(
                name
                for name in ("apex_payload.img", "apex_pubkey", "apex_manifest.pb")
                if names.count(name) != 1 and names.count(name) > 1
            )
            if duplicated:
                return False, "duplicate critical APEX members: " + ", ".join(
                    duplicated
                )
            bad_member = archive.testzip()
    except (OSError, zipfile.BadZipFile) as error:
        return False, f"invalid ZIP: {error}"
    if bad_member:
        return False, f"CRC failed for {bad_member}"
    return True, "all ZIP members passed CRC"


def inspect_apex(
    archive_path: Path,
    label: str,
    work_dir: Path,
    toolchain: Toolchain,
) -> ApexInspection:
    inspection = ApexInspection(archive=archive_path)
    inspection.zip_ok, inspection.zip_detail = verify_zip_crc(archive_path)
    if not inspection.zip_ok:
        inspection.avb_detail = "skipped because ZIP validation failed"
        inspection.payload_detail = "skipped because ZIP validation failed"
        return inspection

    apex_dir = work_dir / re.sub(r"[^A-Za-z0-9_.-]", "_", label)
    outer_dir = apex_dir / "outer"
    payload_root = apex_dir / "payload"
    outer_dir.mkdir(parents=True, exist_ok=True)
    payload_root.mkdir(parents=True, exist_ok=True)
    required_members = ("apex_payload.img", "apex_pubkey", "apex_manifest.pb")
    try:
        with zipfile.ZipFile(archive_path) as archive:
            missing = [name for name in required_members if name not in archive.namelist()]
            if missing:
                inspection.avb_detail = "missing APEX members: " + ", ".join(missing)
                inspection.payload_detail = inspection.avb_detail
                return inspection
            for member in required_members:
                archive.extract(member, outer_dir)
    except (OSError, zipfile.BadZipFile) as error:
        inspection.avb_detail = f"could not extract APEX members: {error}"
        inspection.payload_detail = inspection.avb_detail
        return inspection

    manifest_bytes = (outer_dir / "apex_manifest.pb").read_bytes()
    pubkey = (outer_dir / "apex_pubkey").read_bytes()
    inspection.manifest_bytes = manifest_bytes
    inspection.manifest_sha256 = _sha256(manifest_bytes)
    inspection.pubkey_sha256 = _sha256(pubkey)
    outer_pubkey_sha1 = hashlib.sha1(pubkey).hexdigest()
    try:
        inspection.manifest = parse_apex_manifest(manifest_bytes)
    except ManifestDecodeError as error:
        inspection.payload_detail = f"invalid apex_manifest.pb: {error}"

    payload_image = outer_dir / "apex_payload.img"
    if not toolchain.avbtool:
        inspection.avb_detail = "avbtool was not found"
        inspection.avb_key_detail = "avbtool was not found"
    else:
        result = toolchain.run(
            (toolchain.avbtool, "verify_image", "--image", str(payload_image))
        )
        inspection.avb_ok = result.returncode == 0
        output = "\n".join(part for part in (result.stdout, result.stderr) if part).strip()
        inspection.avb_detail = output or f"avbtool exited {result.returncode}"
        info_result = toolchain.run(
            (toolchain.avbtool, "info_image", "--image", str(payload_image))
        )
        info_output = "\n".join(
            part for part in (info_result.stdout, info_result.stderr) if part
        ).strip()
        match = re.search(r"Public key \(sha1\):\s*([0-9a-fA-F]{40})", info_output)
        embedded_pubkey_sha1 = match.group(1).lower() if match else None
        inspection.avb_key_ok = bool(
            info_result.returncode == 0
            and embedded_pubkey_sha1
            and embedded_pubkey_sha1 == outer_pubkey_sha1
        )
        inspection.avb_key_detail = (
            f"payload and outer apex_pubkey sha1={outer_pubkey_sha1}"
            if inspection.avb_key_ok
            else (
                f"outer apex_pubkey sha1={outer_pubkey_sha1}, "
                f"payload key sha1={embedded_pubkey_sha1 or '<missing>'}; "
                f"avbtool info exit={info_result.returncode}"
            )
        )

    if not toolchain.debugfs:
        inspection.payload_detail = "debugfs was not found"
        return inspection
    result = toolchain.run(
        (
            toolchain.debugfs,
            "-R",
            f"rdump / {payload_root}",
            str(payload_image),
        )
    )
    sentinel = payload_root / "apex_manifest.pb"
    inspection.payload_ok = result.returncode == 0 and sentinel.is_file()
    if inspection.payload_ok:
        inspection.payload_root = payload_root
        inspection.payload_detail = "payload filesystem extracted with debugfs"
    else:
        output = "\n".join(part for part in (result.stdout, result.stderr) if part).strip()
        inspection.payload_detail = output or "debugfs did not extract apex_manifest.pb"
    return inspection


def _resolve_existing(root: Path, relatives: Iterable[str]) -> Path | None:
    for relative in relatives:
        path = root / relative
        if path.exists() or path.is_symlink():
            return path
    return None


def _system_path(root: Path, relative: str) -> Path | None:
    return _resolve_existing(root, (f"system/system/{relative}", f"system/{relative}"))


def _system_ext_apex(root: Path, name: str) -> Path | None:
    return _resolve_existing(
        root,
        (
            f"system_ext/apex/{name}",
            f"system/system/system_ext/apex/{name}",
            f"system/system_ext/apex/{name}",
        ),
    )


def _read_properties(path: Path) -> dict[str, str]:
    properties: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        properties[key.strip()] = value.strip()
    return properties


def _firmware_directory_name(spec: str) -> str | None:
    fields = spec.split("/")
    if len(fields) != 3 or not fields[0] or not fields[1] or not fields[2]:
        return None
    return f"{fields[0]}_{fields[1]}"


def _validate_firmware_identity(
    report: ValidationReport,
    root: Path,
    prefix: str,
    require_32bit: bool,
    *,
    expected_spec: str,
    expected_build: str,
    expected_model: str,
) -> None:
    expected_directory = _firmware_directory_name(expected_spec)
    report.add(
        f"{prefix}.firmware_spec",
        expected_directory is not None and root.name == expected_directory,
        (
            f"spec={expected_spec}, directory={root.name}"
            if expected_directory is not None
            else f"invalid expected firmware spec: {expected_spec}"
        ),
    )
    marker = root / ".extracted"
    marker_value = (
        marker.read_text(encoding="utf-8", errors="replace").strip()
        if marker.is_file()
        else ""
    )
    report.add(
        f"{prefix}.firmware_build",
        marker_value == expected_build,
        f"actual={marker_value or '<missing>'}, expected={expected_build}",
    )

    build_prop = _system_path(root, "build.prop")
    if not build_prop or not build_prop.is_file():
        report.add(f"{prefix}.api_release", False, "system build.prop is missing")
        if require_32bit:
            report.add(f"{prefix}.abilist32", False, "property files are unavailable")
        return
    properties = _read_properties(build_prop)
    model = properties.get("ro.product.system.model") or properties.get(
        "ro.product.model"
    )
    report.add(
        f"{prefix}.firmware_model",
        model == expected_model,
        f"actual={model or '<missing>'}, expected={expected_model}",
    )
    expected_build_id = expected_build.split("/", 1)[0]
    fingerprint = properties.get("ro.system.build.fingerprint") or properties.get(
        "ro.build.fingerprint"
    )
    description = properties.get("ro.build.description")
    content_build_ok = bool(
        fingerprint
        and description
        and f"/{expected_build_id}:" in fingerprint
        and re.search(rf"(?:^|\s){re.escape(expected_build_id)}(?:\s|$)", description)
    )
    report.add(
        f"{prefix}.content_build",
        content_build_ok,
        (
            f"expected={expected_build_id}; fingerprint={fingerprint or '<missing>'}; "
            f"description={description or '<missing>'}"
        ),
    )
    sdk = properties.get("ro.build.version.sdk") or properties.get(
        "ro.system.build.version.sdk"
    )
    release = properties.get("ro.build.version.release")
    ok = sdk == EXPECTED_API and release == EXPECTED_RELEASE
    report.add(
        f"{prefix}.api_release",
        ok,
        f"sdk={sdk or '<missing>'}, release={release or '<missing>'}; expected 36/16",
    )

    if not require_32bit:
        return
    property_files = [
        build_prop,
        root / "vendor/build.prop",
        root / "product/etc/build.prop",
        root / "odm/etc/build.prop",
    ]
    keys = (
        "ro.product.cpu.abilist32",
        "ro.system.product.cpu.abilist32",
        "ro.vendor.product.cpu.abilist32",
        "ro.product.system.cpu.abilist32",
    )
    evidence: list[str] = []
    invalid_evidence: list[str] = []
    for path in property_files:
        if not path.is_file():
            continue
        props = _read_properties(path)
        for key in keys:
            value = props.get(key, "")
            if value:
                item = f"{path.relative_to(root)}:{key}={value}"
                evidence.append(item)
                abis = {abi.strip() for abi in value.split(",") if abi.strip()}
                if not abis.intersection({"armeabi-v7a", "armeabi"}):
                    invalid_evidence.append(item)
    report.add(
        f"{prefix}.abilist32",
        bool(evidence) and not invalid_evidence,
        (
            "; ".join(evidence)
            if evidence and not invalid_evidence
            else (
                "non-ARM 32-bit ABI lists: " + "; ".join(invalid_evidence)
                if invalid_evidence
                else "no non-empty 32-bit ABI list found"
            )
        ),
    )


def _elf_description(info: ElfInfo | None) -> str:
    if info is None:
        return "not an ELF file"
    return f"ELF{info.bits} {info.machine_name}"


def _validate_candidate_system_lib(report: ValidationReport, candidate: Path) -> None:
    system_lib = _system_path(candidate, "lib")
    if not system_lib or not system_lib.is_dir():
        report.add("candidate.system_lib", False, "system/lib directory is missing")
        report.add(
            "candidate.system_lib_api_notes", False, "system/lib is unavailable"
        )
        report.add("candidate.bootstrap", False, "system/lib is unavailable")
        report.add(
            "candidate.bootstrap_api_notes", False, "system/lib is unavailable"
        )
        return

    elf_count = 0
    invalid: list[str] = []
    api_level_counts: dict[int, int] = {}
    api35_files: list[str] = []
    for path in sorted(system_lib.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        info = read_elf_info(path)
        if info is None:
            if path.suffix == ".so":
                invalid.append(f"{path.relative_to(system_lib)}: not ELF")
            continue
        elf_count += 1
        levels = read_android_api_levels(path)
        for level in levels:
            api_level_counts[level] = api_level_counts.get(level, 0) + 1
        if 35 in levels:
            api35_files.append(str(path.relative_to(system_lib)))
        if info.bits != 32 or info.machine != EM_ARM:
            invalid.append(
                f"{path.relative_to(system_lib)}: {_elf_description(info)}"
            )
    report.add(
        "candidate.system_lib",
        elf_count >= MIN_SYSTEM_LIB_ELF_COUNT and not invalid,
        (
            f"{elf_count} ELF32 ARM files (minimum {MIN_SYSTEM_LIB_ELF_COUNT})"
            if elf_count >= MIN_SYSTEM_LIB_ELF_COUNT and not invalid
            else (
                f"{elf_count} ELF files (minimum {MIN_SYSTEM_LIB_ELF_COUNT}); "
                f"invalid: {', '.join(invalid[:12]) or 'none'}"
            )
        ),
    )
    api36_count = api_level_counts.get(int(EXPECTED_API), 0)
    note_summary = ", ".join(
        f"API{level}={count}" for level, count in sorted(api_level_counts.items())
    )
    report.add(
        "candidate.system_lib_api_notes",
        api36_count >= MIN_SYSTEM_LIB_API36_NOTES and not api35_files,
        (
            f"{note_summary or 'no Android NT_VERSION notes'}; "
            f"required API36>={MIN_SYSTEM_LIB_API36_NOTES}, API35=0"
            + (
                f"; API35 sample: {', '.join(api35_files[:8])}"
                if api35_files
                else ""
            )
        ),
    )

    bootstrap_dir = system_lib / "bootstrap"
    bootstrap_linker = _system_path(candidate, "bin/bootstrap/linker")
    failures: list[str] = []
    checked = 0
    for path in (
        *((bootstrap_dir / name) for name in BOOTSTRAP_LIBRARIES),
        bootstrap_linker,
    ):
        if path is None or not path.is_file():
            failures.append(str(path) if path else "bin/bootstrap/linker")
            continue
        checked += 1
        info = read_elf_info(path)
        if not info or info.bits != 32 or info.machine != EM_ARM:
            failures.append(f"{path}: {_elf_description(info)}")

    linker_asan = _system_path(candidate, "bin/bootstrap/linker_asan")
    if linker_asan is None:
        failures.append("bin/bootstrap/linker_asan")
    elif linker_asan.is_symlink():
        if os.readlink(linker_asan) not in {"linker", "/system/bin/bootstrap/linker"}:
            failures.append(
                f"bin/bootstrap/linker_asan -> {os.readlink(linker_asan)}"
            )
    elif linker_asan.is_file():
        info = read_elf_info(linker_asan)
        if not info or info.bits != 32 or info.machine != EM_ARM:
            failures.append(f"linker_asan: {_elf_description(info)}")
    else:
        failures.append("bin/bootstrap/linker_asan")
    report.add(
        "candidate.bootstrap",
        checked == len(BOOTSTRAP_LIBRARIES) + 1 and not failures,
        "32-bit ARM linker and bionic are complete"
        if not failures
        else "missing/invalid: " + ", ".join(failures),
    )

    note_failures: list[str] = []
    for name in BOOTSTRAP_API_NOTE_ELFS:
        path = bootstrap_dir / name
        levels = read_android_api_levels(path) if path.is_file() else set()
        if levels != {int(EXPECTED_API)}:
            note_failures.append(f"{name}: {sorted(levels) or '<missing>'}")
    report.add(
        "candidate.bootstrap_api_notes",
        not note_failures,
        (
            "known note-bearing bootstrap libc/libm report Android API 36"
            if not note_failures
            else "invalid Android NT_VERSION: " + "; ".join(note_failures)
        ),
    )


def _check_payload_elfs(
    payload_root: Path | None,
    paths: Iterable[str],
    bits: int,
    machine: int,
) -> tuple[bool, str]:
    if payload_root is None:
        return False, "APEX payload is unavailable"
    failures: list[str] = []
    checked = 0
    for relative in paths:
        path = payload_root / relative
        if not path.is_file():
            failures.append(f"{relative}: missing")
            continue
        checked += 1
        info = read_elf_info(path)
        if not info or info.bits != bits or info.machine != machine:
            failures.append(f"{relative}: {_elf_description(info)}")
    if failures:
        return False, "; ".join(failures)
    return True, f"{checked} required ELF{bits} files present"


def _check_api36_notes(
    payload_root: Path | None, paths: Iterable[str]
) -> tuple[bool, str]:
    if payload_root is None:
        return False, "APEX payload is unavailable"
    failures: list[str] = []
    checked = 0
    for relative in paths:
        path = payload_root / relative
        levels = read_android_api_levels(path) if path.is_file() else set()
        if levels != {int(EXPECTED_API)}:
            failures.append(f"{relative}: {sorted(levels) or '<missing>'}")
        else:
            checked += 1
    if failures:
        return False, "invalid Android NT_VERSION: " + "; ".join(failures)
    return True, f"{checked} known note-bearing ELF files report Android API 36"


def _check_symlinks(
    payload_root: Path | None, expected_links: dict[str, str]
) -> tuple[bool, str]:
    if payload_root is None:
        return False, "APEX payload is unavailable"
    failures: list[str] = []
    for relative, expected in expected_links.items():
        path = payload_root / relative
        if not path.is_symlink() or os.readlink(path) != expected:
            actual = os.readlink(path) if path.is_symlink() else "<not a symlink>"
            failures.append(f"{relative} -> {actual}, expected {expected}")
    if failures:
        return False, "; ".join(failures)
    return True, f"all {len(expected_links)} required symlinks have exact targets"


def _add_apex_base_checks(
    report: ValidationReport,
    label: str,
    inspection: ApexInspection,
    expected_name: str,
) -> None:
    report.add(f"{label}.zip_crc", inspection.zip_ok, inspection.zip_detail)
    report.add(f"{label}.avb", inspection.avb_ok, inspection.avb_detail)
    report.add(
        f"{label}.avb_pubkey", inspection.avb_key_ok, inspection.avb_key_detail
    )
    report.add(f"{label}.payload", inspection.payload_ok, inspection.payload_detail)
    manifest_ok = (
        inspection.manifest is not None
        and inspection.manifest.name == expected_name
        and inspection.manifest.version > 0
    )
    manifest_detail = (
        f"name={inspection.manifest.name}, version={inspection.manifest.version}, "
        f"sha256={inspection.manifest_sha256}"
        if inspection.manifest
        else "manifest could not be decoded"
    )
    report.add(f"{label}.manifest", manifest_ok, manifest_detail)

    inner_manifest = (
        inspection.payload_root / "apex_manifest.pb"
        if inspection.payload_root
        else None
    )
    inner_ok = bool(
        inner_manifest
        and inner_manifest.is_file()
        and inspection.manifest_bytes is not None
        and inner_manifest.read_bytes() == inspection.manifest_bytes
    )
    report.add(
        f"{label}.inner_manifest",
        inner_ok,
        "inner and outer apex_manifest.pb match"
        if inner_ok
        else "inner and outer apex_manifest.pb do not match",
    )


def _validate_runtime_apex(
    report: ValidationReport, label: str, inspection: ApexInspection
) -> None:
    _add_apex_base_checks(report, label, inspection, "com.android.runtime")
    ok32, detail32 = _check_payload_elfs(
        inspection.payload_root, RUNTIME_32_ELFS, 32, EM_ARM
    )
    report.add(f"{label}.elf32", ok32, detail32)
    notes_ok, notes_detail = _check_api36_notes(
        inspection.payload_root, RUNTIME_32_API_NOTE_ELFS
    )
    report.add(f"{label}.api36_notes", notes_ok, notes_detail)
    ok64, detail64 = _check_payload_elfs(
        inspection.payload_root, RUNTIME_64_ELFS, 64, EM_AARCH64
    )
    report.add(f"{label}.elf64", ok64, detail64)

    links_ok, links_detail = _check_symlinks(
        inspection.payload_root, RUNTIME_SYMLINKS
    )
    report.add(
        f"{label}.linker_symlinks",
        links_ok,
        links_detail,
    )


def _validate_i18n_apex(
    report: ValidationReport, label: str, inspection: ApexInspection
) -> None:
    _add_apex_base_checks(report, label, inspection, "com.android.i18n")
    paths32 = tuple(f"lib/{name}" for name in I18N_LIBRARIES)
    paths64 = tuple(f"lib64/{name}" for name in I18N_LIBRARIES)
    ok32, detail32 = _check_payload_elfs(
        inspection.payload_root, paths32, 32, EM_ARM
    )
    ok64, detail64 = _check_payload_elfs(
        inspection.payload_root, paths64, 64, EM_AARCH64
    )
    notes_ok, notes_detail = _check_api36_notes(
        inspection.payload_root, (*paths32, *paths64)
    )
    links_ok, links_detail = _check_symlinks(
        inspection.payload_root, I18N_SYMLINKS
    )
    missing_data: list[str] = []
    for relative in I18N_DATA_FILES:
        path = inspection.payload_root / relative if inspection.payload_root else None
        if path is None or not path.is_file() or path.stat().st_size == 0:
            missing_data.append(relative)
    data_ok = not missing_data
    report.add(f"{label}.elf32", ok32, detail32)
    report.add(f"{label}.elf64", ok64, detail64)
    report.add(f"{label}.api36_notes", notes_ok, notes_detail)
    report.add(f"{label}.symlinks", links_ok, links_detail)
    report.add(
        f"{label}.data",
        data_ok,
        "icudt76l.dat and core-icu4j.jar are non-empty"
        if data_ok
        else "missing/empty: " + ", ".join(missing_data),
    )


def _validate_vndk31_apex(
    report: ValidationReport, label: str, inspection: ApexInspection
) -> None:
    _add_apex_base_checks(report, label, inspection, "com.android.vndk.v31")
    arch_paths: dict[str, set[str]] = {"lib": set(), "lib64": set()}
    note_counts: dict[str, dict[int, int]] = {"lib": {}, "lib64": {}}
    for directory, bits, machine in (
        ("lib", 32, EM_ARM),
        ("lib64", 64, EM_AARCH64),
    ):
        failures: list[str] = []
        arch_root = inspection.payload_root / directory if inspection.payload_root else None
        if arch_root is None or not arch_root.is_dir():
            failures.append(f"{directory}: missing")
        else:
            for path in sorted(arch_root.rglob("*")):
                relative = str(path.relative_to(arch_root))
                if path.is_symlink():
                    failures.append(f"{relative}: unexpected symlink")
                    continue
                if not path.is_file():
                    continue
                arch_paths[directory].add(relative)
                info = read_elf_info(path)
                if not info or info.bits != bits or info.machine != machine:
                    failures.append(f"{relative}: {_elf_description(info)}")
                    continue
                for level in read_android_api_levels(path):
                    counts = note_counts[directory]
                    counts[level] = counts.get(level, 0) + 1
        count = len(arch_paths[directory])
        report.add(
            f"{label}.elf{bits}",
            count == VNDK31_EXPECTED_ELF_COUNT and not failures,
            (
                f"{count} recursive ELF{bits} files with correct architecture"
                if count == VNDK31_EXPECTED_ELF_COUNT and not failures
                else (
                    f"{count} files, expected {VNDK31_EXPECTED_ELF_COUNT}; "
                    f"invalid: {', '.join(failures[:12]) or 'none'}"
                )
            ),
        )

    def normalize_arch_path(relative: str) -> str:
        return re.sub(
            r"(libclang_rt\.(?:scudo|scudo_minimal|ubsan_standalone))-"
            r"(?:arm|aarch64)(-android\.so)$",
            r"\1-ARCH\2",
            relative,
        )

    normalized32 = {normalize_arch_path(path) for path in arch_paths["lib"]}
    normalized64 = {normalize_arch_path(path) for path in arch_paths["lib64"]}
    symmetry_missing32 = sorted(normalized64 - normalized32)
    symmetry_missing64 = sorted(normalized32 - normalized64)
    nested_hw = "hw/android.hidl.memory@1.0-impl.so"
    symmetry_ok = (
        normalized32 == normalized64
        and nested_hw in arch_paths["lib"]
        and nested_hw in arch_paths["lib64"]
    )
    report.add(
        f"{label}.path_symmetry",
        symmetry_ok,
        (
            "32/64 paths are symmetric after sanitizer normalization; nested hw present"
            if symmetry_ok
            else (
                f"missing32={symmetry_missing32[:8]}, "
                f"missing64={symmetry_missing64[:8]}, nested_hw="
                f"{nested_hw in arch_paths['lib']}/{nested_hw in arch_paths['lib64']}"
            )
        ),
    )

    expected_note_counts = {29: 3, 31: 131}
    notes_ok = all(
        note_counts[directory] == expected_note_counts
        for directory in ("lib", "lib64")
    )
    report.add(
        f"{label}.api_notes",
        notes_ok,
        f"lib={note_counts['lib']}, lib64={note_counts['lib64']}; "
        f"expected={expected_note_counts}",
    )

    list_failures: list[str] = []
    list_entries: dict[str, set[str]] = {}
    for relative in VNDK31_LISTS:
        path = inspection.payload_root / relative if inspection.payload_root else None
        if path is None or not path.is_file() or path.stat().st_size == 0:
            list_failures.append(f"{relative}: missing/empty")
            continue
        entries = [
            line.split()[0]
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        unique_entries = set(entries)
        expected_count = VNDK31_LIST_ENTRY_COUNTS[relative]
        if len(entries) != len(unique_entries):
            list_failures.append(f"{relative}: duplicate entries")
        if len(unique_entries) != expected_count:
            list_failures.append(
                f"{relative}: {len(unique_entries)} entries, expected {expected_count}"
            )
        list_entries[relative] = unique_entries

    available_names = {
        Path(relative).name
        for paths in arch_paths.values()
        for relative in paths
    }
    for relative, entries in list_entries.items():
        if relative.endswith("llndk.libraries.31.txt"):
            continue
        missing = sorted(
            entries - available_names - VNDK31_EXTERNAL_LIST_ENTRIES
        )
        if missing:
            list_failures.append(
                f"{relative}: entries absent from payload: {', '.join(missing[:8])}"
            )
    report.add(
        f"{label}.library_lists",
        not list_failures,
        "all five lists have the GZF2 entry counts and reference the payload"
        if not list_failures
        else "; ".join(list_failures),
    )


def exported_symbols(path: Path, toolchain: Toolchain) -> set[str]:
    if not toolchain.readelf:
        raise RuntimeError("readelf was not found")
    result = toolchain.run((toolchain.readelf, "--dyn-syms", "--wide", str(path)))
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(detail or f"readelf exited {result.returncode}")
    symbols: set[str] = set()
    for line in result.stdout.splitlines():
        fields = line.split(maxsplit=7)
        if len(fields) < 8 or not fields[0].rstrip(":").isdigit():
            continue
        _number, _value, _size, symbol_type, bind, _visibility, index, name = fields
        if index == "UND" or bind not in {"GLOBAL", "WEAK", "UNIQUE"}:
            continue
        if symbol_type in {"FILE", "SECTION"}:
            continue
        name = re.sub(r"\s+\(\d+\)$", "", name)
        if name:
            symbols.add(name)
    return symbols


def _elf64_shared_objects(root: Path | None) -> dict[str, Path]:
    if root is None:
        return {}
    lib64 = root / "lib64"
    objects: dict[str, Path] = {}
    if not lib64.is_dir():
        return objects
    for path in sorted(lib64.rglob("*.so")):
        if path.is_symlink() or not path.is_file():
            continue
        info = read_elf_info(path)
        if info and info.bits == 64 and info.machine == EM_AARCH64:
            objects[str(path.relative_to(root))] = path
    return objects


def _validate_symbol_superset(
    report: ValidationReport,
    label: str,
    candidate: ApexInspection,
    donor: ApexInspection,
    toolchain: Toolchain,
    symbol_reader: Callable[[Path, Toolchain], set[str]],
) -> None:
    candidate_objects = _elf64_shared_objects(candidate.payload_root)
    donor_objects = _elf64_shared_objects(donor.payload_root)
    if not donor_objects:
        report.add(label, False, "main donor has no inspectable ELF64 libraries")
        return
    failures: list[str] = []
    compared = 0
    for relative, donor_path in donor_objects.items():
        candidate_path = candidate_objects.get(relative)
        if candidate_path is None:
            failures.append(f"{relative}: missing from candidate")
            continue
        try:
            required = symbol_reader(donor_path, toolchain)
            provided = symbol_reader(candidate_path, toolchain)
        except RuntimeError as error:
            failures.append(f"{relative}: {error}")
            continue
        missing = sorted(required - provided)
        if missing:
            sample = ", ".join(missing[:8])
            failures.append(f"{relative}: missing {len(missing)} symbols ({sample})")
        compared += 1
    report.add(
        label,
        compared == len(donor_objects) and not failures,
        f"candidate is an exported-symbol superset for {compared} ELF64 libraries"
        if not failures and compared == len(donor_objects)
        else "; ".join(failures[:16]),
    )


def _validate_apex_identity_match(
    report: ValidationReport,
    label: str,
    candidate: ApexInspection,
    donor: ApexInspection,
) -> None:
    key_ok = bool(
        candidate.pubkey_sha256
        and donor.pubkey_sha256
        and candidate.pubkey_sha256 == donor.pubkey_sha256
    )
    report.add(
        f"{label}.pubkey_match",
        key_ok,
        (
            f"sha256={candidate.pubkey_sha256}"
            if key_ok
            else f"candidate={candidate.pubkey_sha256}, donor={donor.pubkey_sha256}"
        ),
    )
    manifest_ok = bool(
        candidate.manifest
        and donor.manifest
        and candidate.manifest == donor.manifest
    )
    report.add(
        f"{label}.manifest_identity_match",
        manifest_ok,
        f"candidate={candidate.manifest}, donor={donor.manifest}",
    )


def _inspect_or_missing(
    report: ValidationReport,
    path: Path | None,
    label: str,
    work_dir: Path,
    toolchain: Toolchain,
    apex_factory: Callable[[Path, str, Path, Toolchain], ApexInspection],
) -> ApexInspection:
    if path is None:
        missing = Path(f"<missing:{label}>")
        return ApexInspection(
            archive=missing,
            zip_detail="APEX path was not found in the extracted firmware",
            avb_detail="APEX path is missing",
            payload_detail="APEX path is missing",
        )
    try:
        return apex_factory(path, label, work_dir, toolchain)
    except Exception as error:  # report unexpected inspector failures as hard-fail
        report.add(f"{label}.inspector", False, f"inspector raised: {error}")
        return ApexInspection(
            archive=path,
            zip_detail=f"inspector failed: {error}",
            avb_detail=f"inspector failed: {error}",
            payload_detail=f"inspector failed: {error}",
        )


def validate_firmware(
    candidate: Path,
    donor: Path,
    *,
    expected_candidate_spec: str = EXPECTED_CANDIDATE_SPEC,
    expected_candidate_build: str = EXPECTED_CANDIDATE_BUILD,
    expected_candidate_model: str = EXPECTED_CANDIDATE_MODEL,
    expected_donor_spec: str = EXPECTED_DONOR_SPEC,
    expected_donor_build: str = EXPECTED_DONOR_BUILD,
    expected_donor_model: str = EXPECTED_DONOR_MODEL,
    toolchain: Toolchain | None = None,
    apex_factory: Callable[[Path, str, Path, Toolchain], ApexInspection] = inspect_apex,
    symbol_reader: Callable[[Path, Toolchain], set[str]] = exported_symbols,
) -> ValidationReport:
    candidate = candidate.resolve()
    donor = donor.resolve()
    report = ValidationReport(candidate=str(candidate), donor=str(donor))
    toolchain = toolchain or Toolchain.discover()

    report.add(
        "candidate.directory",
        candidate.is_dir(),
        "candidate firmware directory exists"
        if candidate.is_dir()
        else "candidate firmware directory is missing",
    )
    report.add(
        "donor.directory",
        donor.is_dir(),
        "main donor firmware directory exists"
        if donor.is_dir()
        else "main donor firmware directory is missing",
    )
    if not candidate.is_dir() or not donor.is_dir():
        return report

    report.add(
        "firmware.distinct",
        candidate != donor,
        "candidate and donor are different extracted trees"
        if candidate != donor
        else "candidate and donor resolve to the same directory",
    )

    _validate_firmware_identity(
        report,
        candidate,
        "candidate",
        require_32bit=True,
        expected_spec=expected_candidate_spec,
        expected_build=expected_candidate_build,
        expected_model=expected_candidate_model,
    )
    _validate_firmware_identity(
        report,
        donor,
        "donor",
        require_32bit=False,
        expected_spec=expected_donor_spec,
        expected_build=expected_donor_build,
        expected_model=expected_donor_model,
    )
    _validate_candidate_system_lib(report, candidate)

    candidate_runtime_path = _system_path(candidate, f"apex/{RUNTIME_APEX}")
    candidate_i18n_path = _system_path(candidate, f"apex/{I18N_APEX}")
    candidate_vndk_path = _system_ext_apex(candidate, VNDK31_APEX)
    donor_runtime_path = _system_path(donor, f"apex/{RUNTIME_APEX}")
    donor_i18n_path = _system_path(donor, f"apex/{I18N_APEX}")

    with tempfile.TemporaryDirectory(prefix="multilib-apex-") as temporary:
        work_dir = Path(temporary)
        candidate_runtime = _inspect_or_missing(
            report,
            candidate_runtime_path,
            "candidate.runtime",
            work_dir,
            toolchain,
            apex_factory,
        )
        candidate_i18n = _inspect_or_missing(
            report,
            candidate_i18n_path,
            "candidate.i18n",
            work_dir,
            toolchain,
            apex_factory,
        )
        candidate_vndk = _inspect_or_missing(
            report,
            candidate_vndk_path,
            "candidate.vndk31",
            work_dir,
            toolchain,
            apex_factory,
        )
        donor_runtime = _inspect_or_missing(
            report,
            donor_runtime_path,
            "donor.runtime",
            work_dir,
            toolchain,
            apex_factory,
        )
        donor_i18n = _inspect_or_missing(
            report,
            donor_i18n_path,
            "donor.i18n",
            work_dir,
            toolchain,
            apex_factory,
        )

        _validate_runtime_apex(report, "candidate.runtime", candidate_runtime)
        _validate_i18n_apex(report, "candidate.i18n", candidate_i18n)
        _validate_vndk31_apex(report, "candidate.vndk31", candidate_vndk)
        _add_apex_base_checks(
            report, "donor.runtime", donor_runtime, "com.android.runtime"
        )
        _add_apex_base_checks(report, "donor.i18n", donor_i18n, "com.android.i18n")

        _validate_apex_identity_match(
            report, "runtime", candidate_runtime, donor_runtime
        )
        _validate_apex_identity_match(report, "i18n", candidate_i18n, donor_i18n)

        vndk_key_ok = bool(
            candidate_vndk.pubkey_sha256
            and donor_runtime.pubkey_sha256
            and candidate_vndk.pubkey_sha256 == donor_runtime.pubkey_sha256
        )
        report.add(
            "vndk31.platform_pubkey_match",
            vndk_key_ok,
            (
                f"sha256={candidate_vndk.pubkey_sha256}"
                if vndk_key_ok
                else (
                    f"vndk31={candidate_vndk.pubkey_sha256}, "
                    f"donor runtime={donor_runtime.pubkey_sha256}"
                )
            ),
        )

        _validate_symbol_superset(
            report,
            "runtime.elf64_symbol_superset",
            candidate_runtime,
            donor_runtime,
            toolchain,
            symbol_reader,
        )
        _validate_symbol_superset(
            report,
            "i18n.elf64_symbol_superset",
            candidate_i18n,
            donor_i18n,
            toolchain,
            symbol_reader,
        )

    return report


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate an extracted API 36 multilib firmware against the main donor",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("candidate", type=Path, help="extracted multilib firmware root")
    parser.add_argument("donor", type=Path, help="extracted main donor firmware root")
    parser.add_argument(
        "--format", choices=("text", "json"), default="text", help="stdout format"
    )
    parser.add_argument(
        "--json-output", type=Path, help="also write the complete JSON report to this path"
    )
    parser.add_argument("--avbtool", help="override avbtool executable")
    parser.add_argument("--debugfs", help="override debugfs executable")
    parser.add_argument("--readelf", help="override readelf executable")
    parser.add_argument(
        "--expected-candidate-spec",
        default=EXPECTED_CANDIDATE_SPEC,
        help="firmware download spec that determines model/region directory",
    )
    parser.add_argument(
        "--expected-candidate-build",
        default=EXPECTED_CANDIDATE_BUILD,
        help="exact PDA/CSC/CP triple required in candidate .extracted",
    )
    parser.add_argument(
        "--expected-candidate-model",
        default=EXPECTED_CANDIDATE_MODEL,
        help="exact candidate ro.product.system.model",
    )
    parser.add_argument(
        "--expected-donor-spec",
        default=EXPECTED_DONOR_SPEC,
        help="main donor download spec that determines model/region directory",
    )
    parser.add_argument(
        "--expected-donor-build",
        default=EXPECTED_DONOR_BUILD,
        help="exact PDA/CSC/CP triple required in donor .extracted",
    )
    parser.add_argument(
        "--expected-donor-model",
        default=EXPECTED_DONOR_MODEL,
        help="exact donor ro.product.system.model",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    toolchain = Toolchain.discover()
    if args.avbtool:
        toolchain.avbtool = args.avbtool
    if args.debugfs:
        toolchain.debugfs = args.debugfs
    if args.readelf:
        toolchain.readelf = args.readelf

    report = validate_firmware(
        args.candidate,
        args.donor,
        expected_candidate_spec=args.expected_candidate_spec,
        expected_candidate_build=args.expected_candidate_build,
        expected_candidate_model=args.expected_candidate_model,
        expected_donor_spec=args.expected_donor_spec,
        expected_donor_build=args.expected_donor_build,
        expected_donor_model=args.expected_donor_model,
        toolchain=toolchain,
    )
    rendered = report.to_json() if args.format == "json" else report.to_text()
    print(rendered)
    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(report.to_json() + "\n", encoding="utf-8")
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
