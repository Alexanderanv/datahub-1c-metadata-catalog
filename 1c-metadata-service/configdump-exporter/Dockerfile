# syntax=docker/dockerfile:1.7

ARG BASE_IMAGE=debian:12-slim
FROM --platform=$TARGETPLATFORM ${BASE_IMAGE}

ARG TARGETARCH
ARG TARGETPLATFORM
ARG ONEC_VERSION
ARG ONEC_ALLOW_UNSATISFIED_DEB_DEPS=false
ARG ONEC_UID=1000
ARG ONEC_GID=1000

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8

RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        bash \
        ca-certificates \
        coreutils \
        dbus-x11 \
        file \
        findutils \
        fontconfig \
        fonts-dejavu-core \
        fonts-dejavu-extra \
        grep \
        gzip \
        iproute2 \
        libfontconfig1 \
        libfreetype6 \
        libglib2.0-0 \
        libglu1-mesa \
        libgtk-3-0 \
        libnss3 \
        libsm6 \
        libstdc++6 \
        libwebkit2gtk-4.0-37 \
        libx11-6 \
        libxau6 \
        libxcb1 \
        libxdmcp6 \
        libxext6 \
        libxfixes3 \
        libxi6 \
        libxrandr2 \
        libxrender1 \
        libxtst6 \
        locales \
        sed \
        tar \
        unzip \
        xauth \
        xvfb \
        xz-utils; \
    sed -i 's/^# *\\(en_US.UTF-8\\|ru_RU.UTF-8\\)/\\1/' /etc/locale.gen; \
    locale-gen; \
    apt-get clean; \
    rm -rf /var/lib/apt/lists/* /var/cache/apt/archives/*.deb

RUN --mount=type=bind,source=dist,target=/tmp/onec-dist,readonly \
    set -eux; \
    if [[ -z "${ONEC_VERSION}" ]]; then \
        echo "Build arg ONEC_VERSION is required, for example: --build-arg ONEC_VERSION=8.3.27.1644" >&2; \
        exit 10; \
    fi; \
    deb_arch="$(dpkg --print-architecture)"; \
    case "${deb_arch}" in \
        amd64) platform_arch="x86_64" ;; \
        arm64) platform_arch="arm64" ;; \
        *) platform_arch="${deb_arch}" ;; \
    esac; \
    mkdir -p /tmp/onec-pkgs; \
    roots=( \
        "/tmp/onec-dist/${ONEC_VERSION}/${deb_arch}" \
        "/tmp/onec-dist/${ONEC_VERSION}/${TARGETARCH}" \
        "/tmp/onec-dist/${ONEC_VERSION}/${platform_arch}" \
        "/tmp/onec-dist/${ONEC_VERSION}" \
        "/tmp/onec-dist/${deb_arch}" \
        "/tmp/onec-dist/${TARGETARCH}" \
        "/tmp/onec-dist/${platform_arch}" \
        "/tmp/onec-dist" \
    ); \
    for root in "${roots[@]}"; do \
        [[ -d "${root}" ]] || continue; \
        find "${root}" -maxdepth 1 -type f -name '*.deb' -exec cp -v {} /tmp/onec-pkgs/ \;; \
        while IFS= read -r -d '' archive; do \
            tar -xzf "${archive}" -C /tmp/onec-pkgs; \
        done < <(find "${root}" -maxdepth 1 -type f \( -name '*.tar.gz' -o -name '*.tgz' \) -print0); \
    done; \
    mapfile -t debs < <(find /tmp/onec-pkgs -type f -name '*.deb' | sort); \
    if (( ${#debs[@]} == 0 )); then \
        echo "No 1C .deb packages found in dist/. Put Linux client packages under dist/${ONEC_VERSION}/${deb_arch}/ or dist/${ONEC_VERSION}/${platform_arch}/." >&2; \
        exit 11; \
    fi; \
    install_debs=(); \
    for deb in "${debs[@]}"; do \
        package_name="$(dpkg-deb -f "${deb}" Package)"; \
        case "${package_name}" in \
            *-thin-client|*-thin-client-nls) \
                echo "Skipping ${package_name}: ConfigDumpInfo exporter uses thick client/Designer, and thin-client conflicts with common/server packages." >&2; \
                ;; \
            *) \
                install_debs+=("${deb}"); \
                ;; \
        esac; \
    done; \
    if (( ${#install_debs[@]} == 0 )); then \
        echo "No installable 1C .deb packages left after filtering thin-client packages." >&2; \
        exit 14; \
    fi; \
    apt-get update; \
    if ! apt-get install -y --no-install-recommends "${install_debs[@]}"; then \
        if [[ "${ONEC_ALLOW_UNSATISFIED_DEB_DEPS}" != "true" ]]; then \
            echo "apt could not satisfy 1C package dependencies." >&2; \
            echo "Provide the full 1C DEB package set for this version/architecture, including packages required by the thick client." >&2; \
            echo "For local diagnostics only, rebuild with --build-arg ONEC_ALLOW_UNSATISFIED_DEB_DEPS=true to extract payloads without registering packages." >&2; \
            exit 13; \
        fi; \
        echo "apt could not satisfy 1C package dependencies; extracting .deb payloads without registering packages for diagnostics." >&2; \
        for deb in "${install_debs[@]}"; do \
            dpkg-deb -x "${deb}" /; \
        done; \
    fi; \
    apt-get clean; \
    rm -rf /var/lib/apt/lists/* /var/cache/apt/archives/*.deb /tmp/onec-pkgs; \
    if ! command -v 1cv8 >/dev/null 2>&1; then \
        onec_bin="$(find /opt -type f -name 1cv8 -perm -111 | sort -V | tail -n 1 || true)"; \
        if [[ -n "${onec_bin}" ]]; then \
            ln -sf "${onec_bin}" /usr/local/bin/1cv8; \
        fi; \
    fi; \
    if ! command -v 1cv8c >/dev/null 2>&1; then \
        onec_cli_bin="$(find /opt -type f -name 1cv8c -perm -111 | sort -V | tail -n 1 || true)"; \
        if [[ -n "${onec_cli_bin}" ]]; then \
            ln -sf "${onec_cli_bin}" /usr/local/bin/1cv8c; \
        fi; \
    fi; \
    if ! command -v 1cv8 >/dev/null 2>&1 && ! find /opt -type f -name 1cv8 -perm -111 | grep -q .; then \
        echo "1cv8 executable was not installed. Check that the 1C thick client/designer package is present in dist/." >&2; \
        exit 12; \
    fi; \
    system_libstdcpp="$(ldconfig -p | awk '/libstdc[+][+][.]so[.]6 / { print $NF; exit }')"; \
    if [[ -n "${system_libstdcpp}" ]]; then \
        while IFS= read -r bundled_libstdcpp; do \
            if [[ -L "${bundled_libstdcpp}" ]]; then \
                rm -f "${bundled_libstdcpp}"; \
            else \
                mv "${bundled_libstdcpp}" "${bundled_libstdcpp}.onec"; \
            fi; \
            ln -sf "${system_libstdcpp}" "${bundled_libstdcpp}"; \
        done < <(find /opt/1cv8 -name 'libstdc++.so.6' -print); \
    fi; \
    if ! getent group "${ONEC_GID}" >/dev/null; then groupadd --gid "${ONEC_GID}" onec; fi; \
    if ! id -u onec >/dev/null 2>&1; then useradd --uid "${ONEC_UID}" --gid "${ONEC_GID}" --create-home --shell /bin/bash onec; fi; \
    mkdir -p /out /work /home/onec/.1cv8; \
    chown -R onec:"${ONEC_GID}" /out /work /home/onec

COPY scripts/export-configdump.sh /usr/local/bin/export-configdump

RUN set -eux; \
    chmod +x /usr/local/bin/export-configdump

VOLUME ["/out", "/work"]
WORKDIR /work
USER onec

HEALTHCHECK --interval=1m --timeout=10s --start-period=30s --retries=3 \
    CMD bash -lc 'command -v 1cv8 >/dev/null 2>&1 || find /opt -type f -name 1cv8 -perm -111 | grep -q .'

ENTRYPOINT ["export-configdump"]
