#!/usr/bin/env bash

set -euo pipefail

SRC_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
IMAGE_NAME=${ONEUI85_BUILDER_IMAGE:-impulserom-oneui85-builder:ubuntu24.04}
MODE=rom
BUILDER_UID=$(id -u)
BUILDER_GID=$(id -g)

if (( BUILDER_UID == 0 || BUILDER_GID == 0 )); then
    echo "Run this wrapper as a regular host user, not root." >&2
    exit 2
fi

if [[ "${1:-}" == "--tools-only" ]]; then
    MODE=tools
    shift
elif [[ "${1:-}" == "--shell" ]]; then
    MODE=shell
    shift
fi

# An Impulse update must retain its original signing identity. The private
# key lives outside the checkout; never silently build an AOSP-testkey update
# just because the ignored security/ files are absent on a fresh clone.
SIGNING_ARGS=()
if [[ "$MODE" == rom ]]; then
    IMPULSE_SIGNING_KEY_DIR=${IMPULSE_SIGNING_KEY_DIR:-$HOME/impulse-keys}
    for SIGNING_FILE in impulse_platform.pk8 impulse_platform.x509.pem; do
        if [[ ! -s "$IMPULSE_SIGNING_KEY_DIR/$SIGNING_FILE" ]]; then
            echo "Missing release signing input: $IMPULSE_SIGNING_KEY_DIR/$SIGNING_FILE" >&2
            exit 2
        fi
        SIGNING_ARGS+=(--volume "$IMPULSE_SIGNING_KEY_DIR/$SIGNING_FILE:/workspace/security/$SIGNING_FILE:ro")
    done
    KEY_PUBLIC_HASH=$(openssl pkey -inform DER -in "$IMPULSE_SIGNING_KEY_DIR/impulse_platform.pk8" \
        -pubout -outform DER | sha256sum | cut -d ' ' -f1)
    CERT_PUBLIC_HASH=$(openssl x509 -in "$IMPULSE_SIGNING_KEY_DIR/impulse_platform.x509.pem" \
        -pubkey -noout | openssl pkey -pubin -outform DER | sha256sum | cut -d ' ' -f1)
    if [[ "$KEY_PUBLIC_HASH" != "$CERT_PUBLIC_HASH" ]]; then
        echo "Impulse signing key does not match the release certificate." >&2
        exit 2
    fi
fi

docker build \
    --build-arg "BUILDER_UID=$BUILDER_UID" \
    --build-arg "BUILDER_GID=$BUILDER_GID" \
    --tag "$IMAGE_NAME" \
    --file "$SRC_DIR/docker/Dockerfile" \
    "$SRC_DIR"

DOCKER_ARGS=(
    --rm
    --init
    --shm-size=2g
    --ulimit nofile=1048576:1048576
    --env "APKTOOL_PARALLEL_JOBS=${APKTOOL_PARALLEL_JOBS:-1}"
    --env "APKTOOL_THREAD_COUNT=${APKTOOL_THREAD_COUNT:-2}"
    # d2s One UI 8.5 bring-up: keep signed APKs at stock until the custom
    # platform-signature framework patch is proven to boot. See apktool.sh BUILD.
    --env "KEEP_SIGNED_APKS_STOCK=${KEEP_SIGNED_APKS_STOCK:-true}"
    # The framework now contains an exact, path- and package-scoped platform
    # signature bridge. Rebuild only the five APKs required for d2s hardware
    # compatibility; every other signed APK remains byte-identical to stock.
    --env "ENABLE_SCOPED_PLATFORM_APK_REBUILDS=${ENABLE_SCOPED_PLATFORM_APK_REBUILDS:-true}"
    --env "INCLUDE_KERNELSU_MANAGER=${INCLUDE_KERNELSU_MANAGER:-true}"
    # fail (default): a drifted framework patch aborts the build. skip: a drifted
    # patch keeps its target at clean stock and is recorded, for a first-boot
    # bring-up on a source the inherited patch set was not authored against.
    --env "PATCH_DRIFT_POLICY=${PATCH_DRIFT_POLICY:-fail}"
    --env TERM=dumb
    --volume "$SRC_DIR:/workspace"
    "${SIGNING_ARGS[@]}"
    --workdir /workspace
)

# Firmware extraction mounts read-only Android images. Tool compilation and an
# interactive inspection shell do not need host-wide container privileges.
if [[ "$MODE" == rom ]]; then
    DOCKER_ARGS+=(--privileged)
fi

case "$MODE" in
    tools)
        docker run "${DOCKER_ARGS[@]}" "$IMAGE_NAME" \
            bash -lc 'source buildenv.sh d2s && ./external/make.sh'
        ;;
    shell)
        docker run --interactive --tty "${DOCKER_ARGS[@]}" "$IMAGE_NAME" \
            bash -lc 'source buildenv.sh d2s && exec bash' bash "$@"
        ;;
    rom)
        docker run "${DOCKER_ARGS[@]}" "$IMAGE_NAME" \
            bash -lc 'source buildenv.sh d2s && ./scripts/make_rom.sh "$@"' \
            bash "$@"
        ;;
esac
