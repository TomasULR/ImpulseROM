#!/usr/bin/env python3
"""Fail a ROM build when split property-context files cannot be merged safely."""

from __future__ import annotations

import argparse
import base64
import hashlib
import mmap
import os
import subprocess
import struct
import zipfile
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree


RUNTIME_LINKS = {
    "system/system/bin/linker": "/apex/com.android.runtime/bin/linker",
    "system/system/bin/linker_asan": "/apex/com.android.runtime/bin/linker",
    "system/system/lib/libc.so": "/apex/com.android.runtime/lib/bionic/libc.so",
    "system/system/lib/libdl.so": "/apex/com.android.runtime/lib/bionic/libdl.so",
    "system/system/lib/libdl_android.so": (
        "/apex/com.android.runtime/lib/bionic/libdl_android.so"
    ),
    "system/system/lib/libm.so": "/apex/com.android.runtime/lib/bionic/libm.so",
}

SECURITY_COMPATIBILITY_LIBRARIES = (
    "libvkjni.so",
    "libvkmanager.so",
    "vendor.samsung.hardware.security.vaultkeeper@2.0.so",
    "lib.engmode.samsung.so",
    "lib.engmodejni.samsung.so",
    "vendor.samsung.hardware.security.engmode@1.0.so",
)

SOURCE_MATCHED_CORE_FILES = (
    "apex/com.android.bt.apex",
    "bin/init",
    "bin/vold",
    "bin/vdc",
    "bin/installd",
    "bin/bootanimation",
    "bin/surfaceflinger",
    "lib64/libandroid_servers.so",
    "lib64/libandroid_runtime.so",
    "lib64/libepm.so",
    "lib64/libgui.so",
    "lib64/libmdf.so",
    "lib64/libui.so",
)

# libstagefright.so is intentionally absent here: the d2s video compatibility
# patch below validates its exact post-patch hash and instruction sequence.

SOURCE_MATCHED_FIRST_BOOT_APKS = (
    "priv-app/SamsungCamera/SamsungCamera.apk",
)

D2S_SCOPED_PLATFORM_APKS = {
    "com.samsung.accessibility": (
        "system/system/priv-app/Accessibility/Accessibility.apk"
    ),
    "com.android.systemui": (
        "system/system/system_ext/priv-app/SystemUI/SystemUI.apk"
    ),
    "com.samsung.android.biometrics.app.setting": (
        "system/system/priv-app/BiometricSetting/BiometricSetting.apk"
    ),
    "com.samsung.android.sead": (
        "system/system/priv-app/EnvironmentAdaptiveDisplay/"
        "EnvironmentAdaptiveDisplay.apk"
    ),
}
D2S_SCOPED_SIGNATURE_SERVICE = (
    "system/system/framework/services.jar"
)
D2S_STANDARD_CAMERA_VERSION = b"14.1.01.17"
D2S_STANDARD_CAMERA_PATH = (
    "system/system/priv-app/SamsungCamera/SamsungCamera.apk"
)
D2S_STANDARD_CAMERA_NATIVE_DIR = (
    "system/system/priv-app/SamsungCamera/lib/arm64"
)
D2S_STANDARD_CAMERA_NATIVE_LIBRARIES = (
    "libmpbase.so",
    "libcamera_effect_processor_jni.so",
    "libEventFinderResultConverter.camera.samsung.so",
    "libdirectbuffer-jni.so",
    "libSceneDetectorJNI.so",
    "libimagexmpinjector.so",
    "libhandgesture.arcsoft.so",
    "libatomjpeg_panorama_enc.quram.so",
    "libpanorama.arcsoft.so",
    "libnode-jni.so",
    "libc++_shared.so",
    "libPanoramaInterface_arcsoft.so",
    "libtype-converter.so",
    "libnativeutils-jni.so",
    "libarcore_sdk_c.so",
    "libimageutils-jni.so",
    "librenderscript-toolkit.so",
    "libarcore_sdk_jni.so",
    "libDiagMonKey.so",
)

D2S_LEGACY_FCM_LEVELS = ("3", "4")

D2S_HIDL_HEALTH_FILES = (
    "bin/hw/android.hardware.health@2.1-service-samsung",
    "etc/init/android.hardware.health@2.1-service-samsung.rc",
    "etc/vintf/manifest/android.hardware.health@2.1-samsung.xml",
    "lib/android.hardware.health@2.1.so",
    "lib64/android.hardware.health@2.1.so",
)

D2S_PLATFORM_NATIVE_API36_FILES = (
    "system/system/bin/bootanimation",
    "system/system/bin/surfaceflinger",
    "system/system/lib64/libandroid_runtime.so",
    "system/system/lib64/libgui.so",
    "system/system/lib64/libui.so",
)
D2S_STAGEFRIGHT_VIDEO_ENCODER_PATH = "system/system/lib64/libstagefright.so"
D2S_STAGEFRIGHT_VIDEO_ENCODER_SHA256 = (
    "dd20c5a7b300f6b90c98d3dc1e1957d71a7ef9e59b0e0f58c41151d17b1c189d"
)
D2S_STAGEFRIGHT_VIDEO_ENCODER_UNSAFE_PATTERN = bytes.fromhex(
    "2100805202408052e30314aae41f8052f7430091"
)
D2S_STAGEFRIGHT_VIDEO_ENCODER_SAFE_PATTERN = bytes.fromhex(
    "21008052c21f8052e30314aae41f8052f7430091"
)

D2S_NETBPFLOAD_COMPAT_FILES = {
    "ethtool": "ca878a914a6f436a5af846d2353dbe44bccf592c527d5b03ac5e6db8e8857b9e",
    "for-system/clatd": "a8cb1311b422a1bc9b0065d73e6e615b61207d331fd42950e8e4da210c46c528",
    "netbpfload": "a3507cc9cdf11c7eb4301d71a596a1fb64bc774aefc7185f6a237b8a4435a448",
    "ot-daemon": "954fd201f94dc49e2d40d9ef90b6d032b177ddf6c85083a5953ebcb915cc0b70",
}

D2S_NETBPFLOAD_COMPAT_LABELS = {
    "ethtool": "u:object_r:system_file:s0",
    "for-system/clatd": "u:object_r:clatd_exec:s0",
    "netbpfload": "u:object_r:bpfloader_exec:s0",
    "ot-daemon": "u:object_r:ot_daemon_exec:s0",
}

D2S_NETBPFLOAD_COMPAT_METADATA = {
    "ethtool": (0, 2000, 755),
    "for-system": (1029, 1000, 750),
    "for-system/clatd": (1029, 1029, 6755),
    "netbpfload": (0, 0, 750),
    "ot-daemon": (0, 2000, 755),
}

D2S_NETBPFLOAD_PATCH_FROM = bytes.fromhex(
    "280200546808009008614439c8010036"
)
D2S_NETBPFLOAD_PATCH_TO = bytes.fromhex(
    "2802005468080090086144390e000014"
)
D2S_NETBPFLOAD_BIND_MOUNT = (
    "mount none /system/etc/netbpfload_compat/bin "
    "/apex/com.android.tethering/bin bind"
)
D2S_ACONFIG_METADATA_MOUNT = (
    "mount tmpfs tmpfs /metadata nodev noexec nosuid "
    "mode=0775,uid=0,gid=1000,size=64m"
)
D2S_FORBIDDEN_LEGACY_APEXES = (
    "system/system/apex/com.android.btservices.apex",
)
D2S_UNSUPPORTED_KNOX_MATRIX_PATHS = (
    "system/system/bin/fabric_crypto",
    "system/system/etc/init/fabric_crypto.rc",
    "system/system/etc/permissions/FabricCryptoLib.xml",
    "system/system/etc/permissions/privapp-permissions-com.samsung.android.kmxservice.xml",
    "system/system/etc/vintf/manifest/fabric_crypto_manifest.xml",
    "system/system/framework/FabricCryptoLib.jar",
    "system/system/lib64/com.samsung.security.fabric.cryptod-V1-cpp.so",
    "system/system/lib64/vendor.samsung.hardware.security.fkeymaster-V1-cpp.so",
    "system/system/lib64/vendor.samsung.hardware.security.fkeymaster-V1-ndk.so",
    "system/system/priv-app/KmxService",
)
D2S_FKEYMASTER_INTERFACE = (
    "<name>vendor.samsung.hardware.security.fkeymaster</name>"
)
D2S_UNSUPPORTED_KNOX_GUARD_PATHS = (
    "system/system/etc/permissions/privapp-permissions-com.samsung.android.kgclient.xml",
    "system/system/etc/permissions/signature-permissions-com.samsung.android.kgclient.xml",
    "system/system/priv-app/KnoxGuard",
)
D2S_KNOX_GUARD_INTERFACE = (
    "<name>vendor.samsung.hardware.tlc.kg</name>"
)
D2S_KNOX_GUARD_CONFIGS = (
    "system/system/etc/broadcast_allowlist.xml",
    "system/system/etc/deviceidle/reviewed_allowlist.xml",
    "system/system/etc/irremovable_list.txt",
    "system/system/etc/permissions/platform.xml",
    "system/system/etc/sysconfig/allowed-system-preload-apps.xml",
    "system/system/etc/sysconfig/required-packages.xml",
    "system/system/etc/sysconfig/safe-mode-allow-list.xml",
)


@dataclass(frozen=True)
class PropertyContext:
    name: str
    context: str
    match_kind: str
    path: Path
    line_number: int


def read_android_api_levels(path: Path) -> set[int]:
    """Read Android NT_VERSION notes without trusting filenames or props."""
    try:
        with path.open("rb") as stream, mmap.mmap(
            stream.fileno(), 0, access=mmap.ACCESS_READ
        ) as contents:
            if len(contents) < 20 or contents[:4] != b"\x7fELF":
                return set()
            byte_order = {1: "<", 2: ">"}.get(contents[5])
            if byte_order is None:
                return set()
            levels: set[int] = set()
            position = 0
            owner = b"Android\0"
            while True:
                owner_offset = contents.find(owner, position)
                if owner_offset < 0:
                    return levels
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
    except (OSError, ValueError):
        return set()


def validate_d2s_platform_native_api36(
    work_dir: Path,
) -> tuple[list[str], int]:
    errors: list[str] = []
    for relative in D2S_PLATFORM_NATIVE_API36_FILES:
        path = work_dir / relative
        levels = read_android_api_levels(path) if path.is_file() else set()
        if levels != {36}:
            errors.append(
                f"{relative}: Android NT_VERSION={sorted(levels) or '<missing>'}, "
                "expected=[36]"
            )
    return errors, len(D2S_PLATFORM_NATIVE_API36_FILES)


def validate_d2s_stagefright_video_encoder(
    work_dir: Path,
    expected_sha256: str = D2S_STAGEFRIGHT_VIDEO_ENCODER_SHA256,
) -> tuple[list[str], int]:
    """Require the bounded Samsung video-encoder fread compatibility patch."""
    path = work_dir / D2S_STAGEFRIGHT_VIDEO_ENCODER_PATH
    if not path.is_file():
        return [f"missing patched video encoder library: {path}"], 0

    contents = path.read_bytes()
    errors: list[str] = []
    actual_sha256 = hashlib.sha256(contents).hexdigest()
    if actual_sha256 != expected_sha256:
        errors.append(
            f"{D2S_STAGEFRIGHT_VIDEO_ENCODER_PATH}: sha256={actual_sha256}, "
            f"expected={expected_sha256}"
        )
    safe_count = contents.count(D2S_STAGEFRIGHT_VIDEO_ENCODER_SAFE_PATTERN)
    unsafe_count = contents.count(D2S_STAGEFRIGHT_VIDEO_ENCODER_UNSAFE_PATTERN)
    if safe_count != 1 or unsafe_count != 0:
        errors.append(
            f"{D2S_STAGEFRIGHT_VIDEO_ENCODER_PATH}: bounded fread pattern "
            f"count={safe_count}, unsafe pattern count={unsafe_count}; "
            "expected 1/0"
        )
    return errors, 1


def validate_d2s_netbpfload_compat(
    work_dir: Path,
    expected_hashes: dict[str, str] | None = None,
) -> tuple[list[str], int]:
    """Require the narrow 25Q4 BPF gate patch and its APEX-path bind mount."""
    if expected_hashes is None:
        expected_hashes = D2S_NETBPFLOAD_COMPAT_FILES

    errors: list[str] = []
    compat_bin = work_dir / "system/system/etc/netbpfload_compat/bin"
    for relative, expected_hash in expected_hashes.items():
        path = compat_bin / relative
        if not path.is_file():
            errors.append(f"missing NetBpfLoad compatibility file: {path}")
            continue
        actual_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual_hash != expected_hash:
            errors.append(
                f"NetBpfLoad compatibility file {relative} hash differs: "
                f"{actual_hash}, expected {expected_hash}"
            )

    loader = compat_bin / "netbpfload"
    if loader.is_file():
        contents = loader.read_bytes()
        if contents.count(D2S_NETBPFLOAD_PATCH_FROM) != 0:
            errors.append("NetBpfLoad still contains the Android 25Q4 5.10 hard gate")
        if contents.count(D2S_NETBPFLOAD_PATCH_TO) != 1:
            errors.append(
                "NetBpfLoad does not contain exactly one validated 25Q4 gate bypass"
            )

    init_rc = work_dir / "system/system/etc/init/hw/init.rc"
    if not init_rc.is_file():
        errors.append(f"missing Android init configuration: {init_rc}")
    else:
        lines = [line.strip() for line in init_rc.read_text(
            encoding="utf-8", errors="replace"
        ).splitlines()]
        bind_positions = [
            index for index, line in enumerate(lines)
            if line == D2S_NETBPFLOAD_BIND_MOUNT
        ]
        start_positions = [
            index for index, line in enumerate(lines)
            if line == "exec_start bpfloader"
        ]
        if len(bind_positions) != 1:
            errors.append(
                "init.rc must contain exactly one validated Tethering bin bind mount"
            )
        if len(start_positions) != 1:
            errors.append("init.rc must contain exactly one bpfloader start")
        if (
            len(bind_positions) == 1
            and len(start_positions) == 1
            and bind_positions[0] + 1 != start_positions[0]
        ):
            errors.append("Tethering bin bind mount must immediately precede bpfloader")

    file_contexts = work_dir / "configs/file_context-system"
    context_text = file_contexts.read_text(
        encoding="utf-8", errors="replace"
    ) if file_contexts.is_file() else ""
    for relative, expected_label in D2S_NETBPFLOAD_COMPAT_LABELS.items():
        entry = f"/system/etc/netbpfload_compat/bin/{relative} {expected_label}"
        if entry not in context_text.splitlines():
            errors.append(f"missing NetBpfLoad SELinux metadata: {entry}")

    fs_config = work_dir / "configs/fs_config-system"
    fs_text = fs_config.read_text(
        encoding="utf-8", errors="replace"
    ) if fs_config.is_file() else ""
    for relative, (uid, gid, mode) in D2S_NETBPFLOAD_COMPAT_METADATA.items():
        prefix = (
            f"system/etc/netbpfload_compat/bin/{relative} "
            f"{uid} {gid} {mode} "
        )
        if not any(line.startswith(prefix) for line in fs_text.splitlines()):
            errors.append(
                f"missing exact Tethering APEX metadata for {relative}: "
                f"uid={uid} gid={gid} mode={mode}"
            )

    return errors, len(expected_hashes)


def validate_d2s_aconfig_compat(work_dir: Path) -> tuple[list[str], int]:
    """Require writable generated-flag storage on pre-/metadata d2s layouts."""
    init_rc = work_dir / "system/system/etc/init/aconfigd.rc"
    if not init_rc.is_file():
        return [f"missing Aconfig init configuration: {init_rc}"], 1

    # Init comments and blank lines are not commands.  Ignore them when
    # enforcing that the compatibility mount is the first early-init command.
    lines = [
        stripped
        for line in init_rc.read_text(
            encoding="utf-8", errors="replace"
        ).splitlines()
        if (stripped := line.strip()) and not stripped.startswith("#")
    ]
    early_init = [
        index for index, line in enumerate(lines) if line == "on early-init"
    ]
    mounts = [
        index
        for index, line in enumerate(lines)
        if line == D2S_ACONFIG_METADATA_MOUNT
    ]
    errors: list[str] = []
    if len(early_init) != 1:
        errors.append("aconfigd.rc must contain exactly one early-init action")
    if len(mounts) != 1:
        errors.append("aconfigd.rc must contain exactly one d2s metadata tmpfs mount")
    if (
        len(early_init) == 1
        and len(mounts) == 1
        and mounts[0] != early_init[0] + 1
    ):
        errors.append("d2s metadata tmpfs must be the first Aconfig early-init command")
    return errors, 1


def validate_d2s_legacy_apex_absence(work_dir: Path) -> tuple[list[str], int]:
    errors = [
        f"legacy APEX must not coexist with Android 16 source: {relative}"
        for relative in D2S_FORBIDDEN_LEGACY_APEXES
        if (work_dir / relative).exists()
    ]
    return errors, len(D2S_FORBIDDEN_LEGACY_APEXES)


def validate_d2s_knox_matrix_absence(work_dir: Path) -> tuple[list[str], int]:
    errors = [
        f"unsupported Knox Matrix component remains: {relative}"
        for relative in D2S_UNSUPPORTED_KNOX_MATRIX_PATHS
        if (work_dir / relative).exists()
    ]
    matrix = (
        work_dir
        / "system/system/etc/vintf/compatibility_matrix.device.xml"
    )
    matrix_text = (
        matrix.read_text(encoding="utf-8", errors="replace")
        if matrix.is_file()
        else ""
    )
    if not matrix.is_file():
        errors.append(f"missing framework compatibility matrix: {matrix}")
    elif D2S_FKEYMASTER_INTERFACE in matrix_text:
        errors.append("unsupported Fkeymaster remains required by framework matrix")
    if D2S_KNOX_GUARD_INTERFACE in matrix_text:
        errors.append("unsupported KnoxGuard remains required by framework matrix")

    errors.extend(
        f"unsupported KnoxGuard component remains: {relative}"
        for relative in D2S_UNSUPPORTED_KNOX_GUARD_PATHS
        if (work_dir / relative).exists()
    )
    for relative in D2S_KNOX_GUARD_CONFIGS:
        path = work_dir / relative
        if not path.is_file():
            errors.append(f"missing KnoxGuard reference config: {relative}")
        elif "com.samsung.android.kgclient" in path.read_text(
            encoding="utf-8", errors="replace"
        ):
            errors.append(f"stale KnoxGuard package reference remains: {relative}")

    return errors, (
        len(D2S_UNSUPPORTED_KNOX_MATRIX_PATHS)
        + len(D2S_UNSUPPORTED_KNOX_GUARD_PATHS)
        + len(D2S_KNOX_GUARD_CONFIGS)
        + 2
    )


def find_property_context_files(work_dir: Path) -> list[Path]:
    """Return real property-context files from the assembled partitions."""
    files: list[Path] = []
    for path in work_dir.rglob("*property_contexts"):
        if not path.is_file() or "configs" in path.parts:
            continue
        files.append(path)
    return sorted(files)


def parse_property_contexts(path: Path) -> list[PropertyContext]:
    entries: list[PropertyContext] = []
    for line_number, raw_line in enumerate(
        path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1
    ):
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue

        fields = line.split()
        if len(fields) < 2:
            continue

        match_kind = "prefix"
        if len(fields) >= 3 and fields[2] in {"exact", "prefix"}:
            match_kind = fields[2]

        entries.append(
            PropertyContext(
                name=fields[0],
                context=fields[1],
                match_kind=match_kind,
                path=path,
                line_number=line_number,
            )
        )
    return entries


def validate_property_contexts(work_dir: Path) -> tuple[list[str], int, int]:
    context_files = find_property_context_files(work_dir)
    by_name: dict[str, list[PropertyContext]] = defaultdict(list)
    entry_count = 0

    for path in context_files:
        entries = parse_property_contexts(path)
        entry_count += len(entries)
        for entry in entries:
            by_name[entry.name].append(entry)

    errors: list[str] = []
    for name, entries in sorted(by_name.items()):
        source_files = {entry.path for entry in entries}
        match_kinds: dict[str, list[PropertyContext]] = defaultdict(list)
        for entry in entries:
            match_kinds[entry.match_kind].append(entry)

        reasons: list[str] = []
        if len(source_files) > 1:
            reasons.append("declared by multiple split-policy files")
        for match_kind, matching_entries in sorted(match_kinds.items()):
            if len(matching_entries) > 1:
                reasons.append(f"has {len(matching_entries)} {match_kind} matches")

        # A single exact and a single prefix declaration in one file is valid
        # Android syntax (for example persist.sys.theme in AOSP policy).
        if not reasons:
            continue

        details = []
        for entry in entries:
            relative_path = entry.path.relative_to(work_dir)
            details.append(
                f"{relative_path}:{entry.line_number} "
                f"[{entry.match_kind}] {entry.context}"
            )
        errors.append(f"{name}: {'; '.join(reasons)}\n    " + "\n    ".join(details))

    if not context_files:
        errors.append("no property-context files were found in the assembled work dir")

    return errors, len(context_files), entry_count


def find_elf32_files(work_dir: Path) -> list[Path]:
    """Return 32-bit ELF objects shipped by the target vendor partition."""
    vendor_dir = work_dir / "vendor"
    if not vendor_dir.is_dir():
        return []

    files: list[Path] = []
    for path in vendor_dir.rglob("*"):
        if not path.is_file():
            continue
        try:
            with path.open("rb") as stream:
                header = stream.read(5)
        except OSError:
            continue
        if header[:4] == b"\x7fELF" and header[4:5] == b"\x01":
            files.append(path)
    return sorted(files)


def _read_properties(path: Path) -> dict[str, str]:
    properties: dict[str, str] = {}
    if not path.is_file():
        return properties
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        properties[key.strip()] = value.strip()
    return properties


def _has_vendor_ndk_version(path: Path, expected: str) -> tuple[bool, str]:
    if not path.is_file():
        return False, f"missing {path}"
    try:
        root = ElementTree.parse(path).getroot()
    except ElementTree.ParseError as error:
        return False, f"invalid XML in {path}: {error}"

    versions: list[str] = []
    for element in root.iter():
        if element.tag.rsplit("}", 1)[-1] != "vendor-ndk":
            continue
        for child in element:
            if child.tag.rsplit("}", 1)[-1] == "version" and child.text:
                versions.append(child.text.strip())
    if versions == [expected]:
        return True, f"vendor-ndk={expected}"
    return False, f"vendor-ndk versions are {versions or '<missing>'}, expected [{expected}]"


def _system_ext_apex_dir(root: Path) -> Path:
    standalone = root / "system_ext/apex"
    if standalone.is_dir():
        return standalone
    return root / "system/system/system_ext/apex"


def validate_vndk31_contract(work_dir: Path) -> list[str]:
    errors: list[str] = []
    vendor_prop = _read_properties(work_dir / "vendor/build.prop")
    actual_vndk = vendor_prop.get("ro.vndk.version")
    if actual_vndk != "31":
        errors.append(
            f"vendor ro.vndk.version is {actual_vndk or '<missing>'}, expected 31"
        )

    framework_manifest_candidates = (
        work_dir / "system_ext/etc/vintf/manifest.xml",
        work_dir / "system/system/system_ext/etc/vintf/manifest.xml",
    )
    framework_manifest = next(
        (path for path in framework_manifest_candidates if path.is_file()),
        framework_manifest_candidates[-1],
    )
    for label, path in (
        ("framework", framework_manifest),
        ("vendor", work_dir / "vendor/etc/vintf/compatibility_matrix.xml"),
    ):
        ok, detail = _has_vendor_ndk_version(path, "31")
        if not ok:
            errors.append(f"{label} VINTF does not select vendor NDK 31: {detail}")

    apex_dirs = {
        work_dir / "system_ext/apex",
        work_dir / "system/system/system_ext/apex",
    }
    vndk_apexes = sorted(
        path
        for apex_dir in apex_dirs
        if apex_dir.is_dir()
        for path in apex_dir.glob("com.android.vndk.v*.apex")
    )
    expected = ["com.android.vndk.v31.apex"]
    actual = [path.name for path in vndk_apexes]
    if actual != expected:
        errors.append(
            f"assembled VNDK APEX set is {actual or '<missing>'}, expected {expected}"
        )
    return errors


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _tree_manifest(root: Path) -> dict[str, tuple[str, int | str]]:
    manifest: dict[str, tuple[str, int | str]] = {}
    if not root.is_dir():
        return manifest
    for path in sorted(root.rglob("*")):
        relative = str(path.relative_to(root))
        if path.is_symlink():
            manifest[relative] = ("symlink", os.readlink(path))
        elif path.is_dir():
            manifest[relative] = ("directory", 0)
        elif path.is_file():
            manifest[relative] = ("file", _sha256_file(path))
        else:
            manifest[relative] = ("other", path.lstat().st_mode)
    return manifest


def _compare_tree(source: Path, assembled: Path, label: str) -> list[str]:
    if not source.is_dir():
        return [f"validated multilib source is missing {label}: {source}"]
    if not assembled.is_dir():
        return [f"assembled work dir is missing {label}: {assembled}"]
    source_manifest = _tree_manifest(source)
    assembled_manifest = _tree_manifest(assembled)
    if source_manifest == assembled_manifest:
        return []

    missing = sorted(set(source_manifest) - set(assembled_manifest))
    extra = sorted(set(assembled_manifest) - set(source_manifest))
    changed = sorted(
        path
        for path in set(source_manifest).intersection(assembled_manifest)
        if source_manifest[path] != assembled_manifest[path]
    )
    return [
        f"{label} differs from the validated multilib snapshot; "
        f"missing={missing[:8]}, extra={extra[:8]}, changed={changed[:8]}"
    ]


def _compare_file(
    source: Path,
    assembled: Path,
    label: str,
    expected_source: str = "validated multilib snapshot",
) -> list[str]:
    if not source.is_file() and not source.is_symlink():
        return [f"{expected_source} is missing {label}: {source}"]
    if not assembled.is_file() and not assembled.is_symlink():
        return [f"assembled work dir is missing {label}: {assembled}"]
    if source.is_symlink() or assembled.is_symlink():
        if (
            source.is_symlink()
            and assembled.is_symlink()
            and os.readlink(source) == os.readlink(assembled)
        ):
            return []
        source_target = os.readlink(source) if source.is_symlink() else "<regular>"
        assembled_target = (
            os.readlink(assembled) if assembled.is_symlink() else "<regular>"
        )
        return [
            f"{label} symlink contract differs: assembled={assembled_target}, "
            f"expected={source_target}"
        ]
    source_hash = _sha256_file(source)
    assembled_hash = _sha256_file(assembled)
    if source_hash == assembled_hash:
        return []
    return [
        f"{label} hash differs from {expected_source}: "
        f"assembled={assembled_hash}, expected={source_hash}"
    ]


def _firmware_system_dir(firmware_dir: Path) -> Path:
    nested = firmware_dir / "system/system"
    if nested.is_dir():
        return nested
    return firmware_dir / "system"


def validate_source_matched_core(
    work_dir: Path, source_firmware_dir: Path
) -> tuple[list[str], int]:
    """Keep boot and graphics core files from the same Android source build."""
    source_system = _firmware_system_dir(source_firmware_dir.resolve())
    assembled_system = work_dir / "system/system"
    errors: list[str] = []
    for relative in SOURCE_MATCHED_CORE_FILES:
        errors.extend(
            _compare_file(
                source_system / relative,
                assembled_system / relative,
                f"boot-critical /system/{relative}",
                "source firmware",
            )
        )
    return errors, len(SOURCE_MATCHED_CORE_FILES)


def validate_source_matched_first_boot_apks(
    work_dir: Path, source_firmware_dir: Path
) -> tuple[list[str], int]:
    """Keep signed APKs stock when the custom platform-signature patch is off."""
    source_system = _firmware_system_dir(source_firmware_dir.resolve())
    assembled_system = work_dir / "system/system"
    errors: list[str] = []
    for relative in SOURCE_MATCHED_FIRST_BOOT_APKS:
        errors.extend(
            _compare_file(
                source_system / relative,
                assembled_system / relative,
                f"source-signed /system/{relative}",
                "source firmware",
            )
        )
    return errors, len(SOURCE_MATCHED_FIRST_BOOT_APKS)


def _read_pem_certificate_der(path: Path) -> bytes:
    text = path.read_text(encoding="ascii")
    payload = "".join(
        line.strip()
        for line in text.splitlines()
        if line and not line.startswith("-----")
    )
    return base64.b64decode(payload, validate=True)


def _apk_signature_identities(apk: Path) -> set[str]:
    """Return signer-certificate identities from APK v1 PKCS#7 blocks."""
    identities: set[str] = set()
    with zipfile.ZipFile(apk) as archive:
        signature_entries = sorted(
            name
            for name in archive.namelist()
            if name.startswith("META-INF/") and name.endswith(".RSA")
        )
        if not signature_entries:
            raise ValueError("v1 signature block is missing")
        for name in signature_entries:
            block = archive.read(name)
            result = subprocess.run(
                [
                    "openssl",
                    "pkcs7",
                    "-inform",
                    "DER",
                    "-print_certs",
                    "-outform",
                    "DER",
                ],
                input=block,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            if result.returncode == 0 and result.stdout:
                identities.add("pkcs7:" + hashlib.sha256(result.stdout).hexdigest())
            else:
                # Synthetic unit-test archives do not contain real PKCS#7. An
                # exact raw-block match remains fail-closed for that fixture;
                # production Samsung APKs always take the parsed path above.
                identities.add("raw:" + hashlib.sha256(block).hexdigest())
    return identities


def validate_apk_signature(apk: Path, apksigner: str) -> list[str]:
    """Verify payload signatures, not just the presence of a signer certificate."""
    try:
        result = subprocess.run(
            [apksigner, "verify", "--verbose", str(apk)],
            capture_output=True, text=True, errors="replace", timeout=120,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return [f"cannot verify APK signature for {apk}: {error}"]
    if result.returncode != 0:
        # Broken v1 manifests can report thousands of missing entries. Keep
        # the build failure readable without hiding the original cause.
        detail = "\n".join((result.stdout + result.stderr).splitlines()[:8])
        return [f"invalid APK signature for {apk}: {detail}"]
    return []


def validate_d2s_standard_camera(
    work_dir: Path, source_firmware_dir: Path
) -> tuple[list[str], int]:
    """Require signed v5.5 camera and its byte-identical adjacent native libs."""
    camera = work_dir / D2S_STANDARD_CAMERA_PATH
    source_camera = (
        _firmware_system_dir(source_firmware_dir.resolve())
        / "priv-app/SamsungCamera/SamsungCamera.apk"
    )
    errors: list[str] = []
    if not camera.is_file():
        return [f"missing standard EternityROM camera: {camera}"], 0
    if not source_camera.is_file():
        return [f"missing source Samsung camera signer reference: {source_camera}"], 0

    try:
        with zipfile.ZipFile(camera) as archive:
            names = set(archive.namelist())
            if "AndroidManifest.xml" not in names:
                errors.append(f"{D2S_STANDARD_CAMERA_PATH}: AndroidManifest.xml is missing")
            else:
                manifest = archive.read("AndroidManifest.xml")
                if (
                    D2S_STANDARD_CAMERA_VERSION not in manifest
                    and D2S_STANDARD_CAMERA_VERSION.decode().encode("utf-16le")
                    not in manifest
                ):
                    errors.append(
                        f"{D2S_STANDARD_CAMERA_PATH}: expected standard EternityROM "
                        f"camera {D2S_STANDARD_CAMERA_VERSION.decode()}"
                    )
            if not any(
                name == "classes.dex"
                or (name.startswith("classes") and name.endswith(".dex"))
                for name in names
            ):
                errors.append(f"{D2S_STANDARD_CAMERA_PATH}: DEX payload is missing")

            expected_entries = {
                f"lib/arm64-v8a/{name}"
                for name in D2S_STANDARD_CAMERA_NATIVE_LIBRARIES
            }
            archive_entries = {
                name
                for name in names
                if name.startswith("lib/arm64-v8a/") and name.endswith(".so")
            }
            if archive_entries != expected_entries:
                missing = sorted(expected_entries - archive_entries)
                unexpected = sorted(archive_entries - expected_entries)
                errors.append(
                    f"{D2S_STANDARD_CAMERA_PATH}: unexpected arm64 native payload; "
                    f"missing={missing}, extra={unexpected}"
                )

            native_dir = work_dir / D2S_STANDARD_CAMERA_NATIVE_DIR
            adjacent_names = (
                {path.name for path in native_dir.glob("*.so")}
                if native_dir.is_dir()
                else set()
            )
            expected_names = set(D2S_STANDARD_CAMERA_NATIVE_LIBRARIES)
            if adjacent_names != expected_names:
                errors.append(
                    f"{D2S_STANDARD_CAMERA_NATIVE_DIR}: adjacent native library "
                    f"set does not match APK; missing="
                    f"{sorted(expected_names - adjacent_names)}, extra="
                    f"{sorted(adjacent_names - expected_names)}"
                )
            for library in D2S_STANDARD_CAMERA_NATIVE_LIBRARIES:
                entry = f"lib/arm64-v8a/{library}"
                adjacent = native_dir / library
                if entry not in archive_entries or not adjacent.is_file():
                    continue
                if adjacent.read_bytes() != archive.read(entry):
                    errors.append(
                        f"{D2S_STANDARD_CAMERA_NATIVE_DIR}/{library}: adjacent "
                        "native library differs from signed APK"
                    )

        camera_signers = _apk_signature_identities(camera)
        source_signers = _apk_signature_identities(source_camera)
        if not camera_signers & source_signers:
            errors.append(
                f"{D2S_STANDARD_CAMERA_PATH}: signer does not match the Samsung "
                "platform certificate from source firmware"
            )
    except (OSError, ValueError, zipfile.BadZipFile, KeyError) as error:
        errors.append(f"invalid standard camera {D2S_STANDARD_CAMERA_PATH}: {error}")
    return errors, 1


def validate_d2s_scoped_platform_apks(
    work_dir: Path, platform_certificate: Path
) -> tuple[list[str], int]:
    """Require all intentionally rebuilt APKs and their scoped key bridge."""
    errors: list[str] = []
    try:
        certificate_der = _read_pem_certificate_der(platform_certificate)
    except (OSError, ValueError) as error:
        return [f"invalid ROM platform certificate {platform_certificate}: {error}"], 0

    for package_name, relative in D2S_SCOPED_PLATFORM_APKS.items():
        apk = work_dir / relative
        if not apk.is_file():
            errors.append(f"missing scoped platform APK {package_name}: {apk}")
            continue
        try:
            with zipfile.ZipFile(apk) as archive:
                names = set(archive.namelist())
                if "AndroidManifest.xml" not in names:
                    errors.append(f"{relative}: AndroidManifest.xml is missing")
                if not any(
                    name == "classes.dex" or (
                        name.startswith("classes") and name.endswith(".dex")
                    )
                    for name in names
                ):
                    errors.append(f"{relative}: DEX payload is missing")
                signature_entries = sorted(
                    name
                    for name in names
                    if name.startswith("META-INF/") and name.endswith(".RSA")
                )
                if not signature_entries:
                    errors.append(f"{relative}: v1 signature block is missing")
                elif not any(
                    certificate_der in archive.read(name)
                    for name in signature_entries
                ):
                    errors.append(
                        f"{relative}: not signed by the configured ROM platform key"
                    )
        except (OSError, zipfile.BadZipFile, KeyError) as error:
            errors.append(f"invalid scoped platform APK {relative}: {error}")

    services = work_dir / D2S_SCOPED_SIGNATURE_SERVICE
    certificate_hex = certificate_der.hex().encode("ascii")
    if not services.is_file():
        errors.append(f"missing scoped-signature framework: {services}")
    else:
        try:
            with zipfile.ZipFile(services) as archive:
                dex_entries = [
                    name
                    for name in archive.namelist()
                    if name == "classes.dex"
                    or (name.startswith("classes") and name.endswith(".dex"))
                ]
                if not dex_entries or not any(
                    certificate_hex in archive.read(name) for name in dex_entries
                ):
                    errors.append(
                        f"{D2S_SCOPED_SIGNATURE_SERVICE}: ROM platform key bridge "
                        "is missing"
                    )
        except (OSError, zipfile.BadZipFile) as error:
            errors.append(
                f"invalid scoped-signature framework "
                f"{D2S_SCOPED_SIGNATURE_SERVICE}: {error}"
            )

    return errors, len(D2S_SCOPED_PLATFORM_APKS)


def _parse_xml(path: Path, label: str) -> tuple[ElementTree.Element | None, list[str]]:
    if not path.is_file():
        return None, [f"missing {label}: {path}"]
    try:
        return ElementTree.parse(path).getroot(), []
    except ElementTree.ParseError as error:
        return None, [f"invalid XML in {label} {path}: {error}"]


def validate_target_fcm_contract(
    work_dir: Path, target_firmware_dir: Path
) -> tuple[list[str], str | None]:
    """Require the framework matrix for the target vendor's real FCM level."""
    errors: list[str] = []
    vendor_manifest = work_dir / "vendor/etc/vintf/manifest.xml"
    manifest_root, manifest_errors = _parse_xml(vendor_manifest, "device manifest")
    errors.extend(manifest_errors)
    if manifest_root is None:
        return errors, None

    target_level = manifest_root.attrib.get("target-level")
    if not target_level:
        errors.append(f"device manifest has no target-level: {vendor_manifest}")
        return errors, None

    target_system = _firmware_system_dir(target_firmware_dir.resolve())
    if target_level != D2S_LEGACY_FCM_LEVELS[0]:
        errors.append(
            f"d2s device manifest target-level is {target_level}, expected "
            f"{D2S_LEGACY_FCM_LEVELS[0]}"
        )

    for matrix_level in D2S_LEGACY_FCM_LEVELS:
        relative = Path("etc/vintf") / f"compatibility_matrix.{matrix_level}.xml"
        assembled_matrix = work_dir / "system/system" / relative
        matrix_root, matrix_errors = _parse_xml(
            assembled_matrix, f"framework compatibility matrix level {matrix_level}"
        )
        errors.extend(matrix_errors)
        if matrix_root is not None:
            if matrix_root.attrib.get("type") != "framework":
                errors.append(
                    f"{assembled_matrix} type is "
                    f"{matrix_root.attrib.get('type') or '<missing>'}, "
                    "expected framework"
                )
            if matrix_root.attrib.get("level") != matrix_level:
                errors.append(
                    f"{assembled_matrix} level is "
                    f"{matrix_root.attrib.get('level') or '<missing>'}, "
                    f"expected {matrix_level}"
                )

        errors.extend(
            _compare_file(
                target_system / relative,
                assembled_matrix,
                f"framework compatibility matrix level {matrix_level}",
                "target firmware",
            )
        )

    for relative in D2S_HIDL_HEALTH_FILES:
        errors.extend(
            _compare_file(
                target_firmware_dir.resolve() / "vendor" / relative,
                work_dir / "vendor" / relative,
                f"d2s HIDL health compatibility file /vendor/{relative}",
                "target firmware",
            )
        )
    return errors, target_level


def validate_modern_ueventd_rules(work_dir: Path) -> tuple[list[str], int]:
    """Android 16 sysfs rules require path, attribute, mode, uid and gid."""
    path = work_dir / "vendor/ueventd.rc"
    if not path.is_file():
        return [f"missing vendor ueventd rules: {path}"], 0

    errors: list[str] = []
    sysfs_rule_count = 0
    for line_number, raw_line in enumerate(
        path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1
    ):
        line = raw_line.split("#", 1)[0].strip()
        if not line.startswith("/sys"):
            continue
        sysfs_rule_count += 1
        fields = line.split()
        if len(fields) not in {5, 6}:
            errors.append(
                f"{path.relative_to(work_dir)}:{line_number}: Android 16 sysfs "
                f"ueventd rule has {len(fields)} fields, expected 5 or 6: {line}"
            )
    return errors, sysfs_rule_count


def validate_multilib_snapshot(work_dir: Path, firmware_dir: Path) -> list[str]:
    errors: list[str] = []
    source_system = firmware_dir / "system/system"
    if not source_system.is_dir():
        source_system = firmware_dir / "system"

    errors.extend(
        _compare_tree(
            source_system / "lib",
            work_dir / "system/system/lib",
            "/system/lib",
        )
    )

    for relative in (
        "apex/com.android.runtime.apex",
        "apex/com.android.i18n.apex",
        "bin/bootstrap/linker",
        "bin/bootstrap/linker_asan",
    ):
        errors.extend(
            _compare_file(
                source_system / relative,
                work_dir / "system/system" / relative,
                f"/system/{relative}",
            )
        )

    source_vndk = _system_ext_apex_dir(firmware_dir) / "com.android.vndk.v31.apex"
    assembled_vndk = _system_ext_apex_dir(work_dir) / "com.android.vndk.v31.apex"
    errors.extend(_compare_file(source_vndk, assembled_vndk, "VNDK31 APEX"))

    for library in SECURITY_COMPATIBILITY_LIBRARIES:
        errors.extend(
            _compare_file(
                source_system / "lib64" / library,
                work_dir / "system/system/lib64" / library,
                f"API 36 security compatibility library {library}",
            )
        )
    return errors


def validate_multilib_runtime(
    work_dir: Path, multilib_firmware_dir: Path | None = None
) -> tuple[list[str], int]:
    """Require a 32-bit bionic entry point when legacy vendor ELF32 exists."""
    elf32_files = find_elf32_files(work_dir)
    if not elf32_files:
        return [], 0

    invalid_links: list[str] = []
    for relative, expected_target in RUNTIME_LINKS.items():
        path = work_dir / relative
        if not path.is_symlink():
            invalid_links.append(f"{relative}: not a symlink")
            continue
        actual_target = os.readlink(path)
        if actual_target != expected_target:
            invalid_links.append(
                f"{relative}: points to {actual_target}, expected {expected_target}"
            )
    if not invalid_links:
        errors = validate_vndk31_contract(work_dir)
        if multilib_firmware_dir is not None:
            firmware_dir = multilib_firmware_dir.resolve()
            if not firmware_dir.is_dir():
                errors.append(
                    f"multilib firmware directory does not exist: {firmware_dir}"
                )
            else:
                errors.extend(validate_multilib_snapshot(work_dir, firmware_dir))
        return errors, len(elf32_files)

    examples = ", ".join(
        str(path.relative_to(work_dir)) for path in elf32_files[:8]
    )
    return [
        "legacy vendor contains "
        f"{len(elf32_files)} ELF32 files but the 32-bit runtime entry points "
        f"are missing or invalid: {'; '.join(invalid_links)}. Examples: {examples}"
    ], len(elf32_files)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("work_dir", type=Path)
    parser.add_argument(
        "--multilib-firmware-dir",
        type=Path,
        help="preflight-validated extracted firmware used for the API 36 multilib layer",
    )
    parser.add_argument(
        "--source-firmware-dir",
        type=Path,
        help="extracted framework firmware used to assemble the system partition",
    )
    parser.add_argument(
        "--require-source-matched-core",
        action="store_true",
        help="reject cross-version replacements of boot and graphics core files",
    )
    parser.add_argument(
        "--require-source-matched-first-boot-apks",
        action="store_true",
        help="reject stripped or re-signed first-boot APK replacements",
    )
    parser.add_argument(
        "--require-d2s-scoped-platform-apks",
        action="store_true",
        help="require three ROM-signed d2s APKs, scoped bridge, and Samsung-signed camera",
    )
    parser.add_argument(
        "--apksigner",
        default=os.environ.get("APKSIGNER", "apksigner"),
        help="Android SDK apksigner executable (required for scoped Camera validation)",
    )
    parser.add_argument(
        "--rom-platform-cert",
        type=Path,
        help="PEM certificate used to sign scoped d2s platform APKs",
    )
    parser.add_argument(
        "--target-firmware-dir",
        type=Path,
        help="extracted target firmware used for legacy vendor compatibility files",
    )
    parser.add_argument(
        "--require-d2s-android16-contracts",
        action="store_true",
        help="require the real target FCM matrix and Android 16 ueventd grammar",
    )
    args = parser.parse_args()

    work_dir = args.work_dir.resolve()
    if not work_dir.is_dir():
        parser.error(f"work dir does not exist: {work_dir}")

    errors, file_count, entry_count = validate_property_contexts(work_dir)
    multilib_errors, elf32_count = validate_multilib_runtime(
        work_dir, args.multilib_firmware_dir
    )
    errors.extend(multilib_errors)
    source_core_count = 0
    if args.require_source_matched_core:
        if args.source_firmware_dir is None:
            parser.error(
                "--require-source-matched-core needs --source-firmware-dir"
            )
        source_core_errors, source_core_count = validate_source_matched_core(
            work_dir, args.source_firmware_dir
        )
        errors.extend(source_core_errors)
    source_apk_count = 0
    if args.require_source_matched_first_boot_apks:
        if args.source_firmware_dir is None:
            parser.error(
                "--require-source-matched-first-boot-apks needs "
                "--source-firmware-dir"
            )
        source_apk_errors, source_apk_count = (
            validate_source_matched_first_boot_apks(
                work_dir, args.source_firmware_dir
            )
        )
        errors.extend(source_apk_errors)
    scoped_apk_count = 0
    if args.require_d2s_scoped_platform_apks:
        if args.rom_platform_cert is None:
            parser.error(
                "--require-d2s-scoped-platform-apks needs --rom-platform-cert"
            )
        if args.source_firmware_dir is None:
            parser.error(
                "--require-d2s-scoped-platform-apks needs --source-firmware-dir"
            )
        scoped_apk_errors, scoped_apk_count = validate_d2s_scoped_platform_apks(
            work_dir, args.rom_platform_cert.resolve()
        )
        errors.extend(scoped_apk_errors)
        camera_errors, camera_count = validate_d2s_standard_camera(
            work_dir, args.source_firmware_dir
        )
        errors.extend(camera_errors)
        errors.extend(validate_apk_signature(
            work_dir / D2S_STANDARD_CAMERA_PATH, args.apksigner
        ))
        scoped_apk_count += camera_count
    target_fcm_level: str | None = None
    ueventd_rule_count = 0
    platform_native_count = 0
    video_encoder_patch_count = 0
    netbpfload_compat_count = 0
    aconfig_compat_count = 0
    forbidden_legacy_apex_count = 0
    knox_matrix_absence_count = 0
    if args.require_d2s_android16_contracts:
        if args.target_firmware_dir is None:
            parser.error(
                "--require-d2s-android16-contracts needs --target-firmware-dir"
            )
        fcm_errors, target_fcm_level = validate_target_fcm_contract(
            work_dir, args.target_firmware_dir
        )
        errors.extend(fcm_errors)
        ueventd_errors, ueventd_rule_count = validate_modern_ueventd_rules(work_dir)
        errors.extend(ueventd_errors)
        platform_native_errors, platform_native_count = (
            validate_d2s_platform_native_api36(work_dir)
        )
        errors.extend(platform_native_errors)
        video_encoder_errors, video_encoder_patch_count = (
            validate_d2s_stagefright_video_encoder(work_dir)
        )
        errors.extend(video_encoder_errors)
        netbpfload_errors, netbpfload_compat_count = (
            validate_d2s_netbpfload_compat(work_dir)
        )
        errors.extend(netbpfload_errors)
        aconfig_errors, aconfig_compat_count = validate_d2s_aconfig_compat(
            work_dir
        )
        errors.extend(aconfig_errors)
        legacy_apex_errors, forbidden_legacy_apex_count = (
            validate_d2s_legacy_apex_absence(work_dir)
        )
        errors.extend(legacy_apex_errors)
        knox_errors, knox_matrix_absence_count = (
            validate_d2s_knox_matrix_absence(work_dir)
        )
        errors.extend(knox_errors)
    print(
        "Property-context validation: "
        f"{file_count} files, {entry_count} declarations"
    )
    print(f"Multilib validation: {elf32_count} vendor ELF32 files")
    if args.require_source_matched_core:
        print(
            "Source-matched core validation: "
            f"{source_core_count} boot-critical files"
        )
    if args.require_source_matched_first_boot_apks:
        print(
            "Source-signed first-boot APK validation: "
            f"{source_apk_count} files"
        )
    if args.require_d2s_scoped_platform_apks:
        print(
            "Scoped d2s platform APK validation: "
            f"{scoped_apk_count} APKs and services.jar bridge "
            "(3 ROM-signed, camera Samsung-signed)"
        )
    if args.require_d2s_android16_contracts:
        print(
            "Legacy-vendor Android 16 validation: "
            f"FCM={target_fcm_level or '<missing>'}, "
            f"{ueventd_rule_count} sysfs ueventd rules, "
            f"{platform_native_count} API36 graphics-core files, "
            f"{video_encoder_patch_count} bounded video-encoder fread patch, "
            f"{netbpfload_compat_count} NetBpfLoad compatibility files, "
            f"{aconfig_compat_count} Aconfig metadata compatibility mount, "
            f"{forbidden_legacy_apex_count} forbidden legacy APEX checks, "
            f"{knox_matrix_absence_count} Knox Matrix absence checks"
        )
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1

    print("Property-context validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
