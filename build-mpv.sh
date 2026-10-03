#!/bin/sh
set -eu
cd "$(dirname "$0")"
sdk=${DECKLINK_SDK_INCLUDE:-'/home/paulo/Blackmagic DeckLink SDK 16.0/Linux/include'}
if [ -d .deps/local ]; then
    export PKG_CONFIG_PATH="$PWD/.deps/local/lib/pkgconfig:$PWD/.deps/root/usr/lib/x86_64-linux-gnu/pkgconfig${PKG_CONFIG_PATH:+:$PKG_CONFIG_PATH}"
fi
if [ ! -f build-mpv/build.ninja ]; then
    meson setup build-mpv mpv -Ddecklink=enabled "-Ddecklink-sdk=$sdk" \
        -Dmanpage-build=disabled -Dtests=true -Dvulkan=disabled -Dlua=lua5.2 "$@"
elif [ "$#" -gt 0 ]; then
    meson setup --reconfigure build-mpv mpv "$@"
fi
meson compile -C build-mpv -j "${JOBS:-4}"
