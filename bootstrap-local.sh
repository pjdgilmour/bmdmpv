#!/bin/sh
# Debian 13: local build dependencies; does not install system packages.
set -eu
cd "$(dirname "$0")"
mkdir -p .deps/debs
(
    cd .deps/debs
    apt-get download libavcodec-dev libavfilter-dev libavformat-dev \
        libavutil-dev libswresample-dev libswscale-dev libpostproc-dev \
        libavdevice-dev libass-dev libunibreak-dev liblcms2-dev \
        libvulkan-dev libxxhash-dev libpulse-dev libpipewire-0.3-dev libspa-0.2-dev liblua5.2-dev
)
python3 scripts/extract-local-deps.py
revision=92b5ac6db79f4d680eb656692f7bf51e9606f42a
if [ ! -d .deps/libplacebo/.git ]; then
    git clone --no-checkout --depth 1 https://github.com/haasn/libplacebo.git .deps/libplacebo
    git -C .deps/libplacebo fetch --depth 1 origin "$revision"
    git -C .deps/libplacebo checkout --detach "$revision"
    git -C .deps/libplacebo submodule update --init --recursive --depth 1
fi
if [ "$(git -C .deps/libplacebo rev-parse HEAD)" != "$revision" ]; then
    printf '%s\n' 'Unexpected libplacebo revision. Preserve local edits and check .deps/libplacebo.' >&2
    exit 1
fi
export PKG_CONFIG_PATH="$PWD/.deps/root/usr/lib/x86_64-linux-gnu/pkgconfig${PKG_CONFIG_PATH:+:$PKG_CONFIG_PATH}"
if [ ! -f .deps/libplacebo-build/build.ninja ]; then
    meson setup .deps/libplacebo-build .deps/libplacebo \
        --prefix="$PWD/.deps/local" --libdir=lib -Dvulkan=disabled \
        -Dopengl=enabled -Ddemos=false -Dtests=false \
        -Dshaderc=disabled -Dglslang=disabled -Dlibdovi=disabled
fi
meson compile -C .deps/libplacebo-build -j "${JOBS:-4}"
meson install -C .deps/libplacebo-build
./build-probe.sh
./build-mpv.sh -Dlibavdevice=enabled -Dpipewire=enabled -Dpulse=enabled -Dlua=lua5.2
