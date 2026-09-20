FROM ubuntu:24.04@sha256:4fbb8e6a8395de5a7550b33509421a2bafbc0aab6c06ba2cef9ebffbc7092d90

ARG DEBIAN_FRONTEND=noninteractive
ARG BUILDER_UID=1000
ARG BUILDER_GID=1000

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        apksigner \
        attr \
        bc \
        brotli \
        build-essential \
        ca-certificates \
        clang \
        cmake \
        cpio \
        curl \
        file \
        fuse3 \
        gawk \
        git \
        golang-go \
        jq \
        libbrotli-dev \
        libfuse3-dev \
        liblz4-dev \
        libpcre2-dev \
        libprotobuf-dev \
        libselinux1-dev \
        libssl-dev \
        libusb-1.0-0-dev \
        libzstd-dev \
        lld \
        lz4 \
        make \
        openjdk-21-jdk-headless \
        p7zip-full \
        pcre2-utils \
        perl \
        pkg-config \
        protobuf-compiler \
        python3 \
        python3-pip \
        python3-venv \
        rsync \
        sudo \
        tar \
        unzip \
        uuid-dev \
        wget \
        xxd \
        xz-utils \
        zip \
        zlib1g-dev \
        zstd \
    && existing_group="$(getent group "$BUILDER_GID" | cut -d: -f1 || true)" \
    && if [[ -z "$existing_group" ]]; then \
           groupadd --gid "$BUILDER_GID" rombuilder; \
       elif [[ "$existing_group" != rombuilder ]]; then \
           groupmod --new-name rombuilder "$existing_group"; \
       fi \
    && existing_user="$(getent passwd "$BUILDER_UID" | cut -d: -f1 || true)" \
    && if [[ -z "$existing_user" ]]; then \
           useradd --uid "$BUILDER_UID" --gid "$BUILDER_GID" \
               --create-home --shell /bin/bash rombuilder; \
       elif [[ "$existing_user" != rombuilder ]]; then \
           usermod --login rombuilder --home /home/rombuilder --move-home \
               --gid "$BUILDER_GID" "$existing_user"; \
       fi \
    && printf 'rombuilder ALL=(ALL) NOPASSWD:ALL\n' > /etc/sudoers.d/rombuilder \
    && chmod 0440 /etc/sudoers.d/rombuilder \
    && mkdir -p /usr/local/share/oneui85-builder \
    && dpkg-query -W > /usr/local/share/oneui85-builder/packages.txt \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Several pinned tool submodules apply their own patch queues with `git am`.
# Give those temporary commits a deterministic, container-local committer.
RUN git config --system user.name "OneUI85 Builder" \
    && git config --system user.email "oneui85-builder@localhost"

# Android's libziparchive exposes FRIEND_TEST declarations in public headers.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgtest-dev \
    && dpkg-query -W > /usr/local/share/oneui85-builder/packages.txt \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

ENV LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    TERM=dumb \
    GRADLE_USER_HOME=/workspace/out/.gradle

USER rombuilder
WORKDIR /workspace
