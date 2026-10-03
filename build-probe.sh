#!/bin/sh
set -eu
cd "$(dirname "$0")"
sdk=${DECKLINK_SDK_INCLUDE:-'/home/paulo/Blackmagic DeckLink SDK 16.0/Linux/include'}
mkdir -p build
c++ -std=c++20 -O2 -Wall -Wextra -I"$sdk" -Impv \
    mpv/TOOLS/decklink_probe.cpp mpv/video/out/decklink_bridge.cpp \
    "$sdk/DeckLinkAPIDispatch.cpp" -ldl -pthread -o build/decklink-probe
printf '%s\n' 'Built build/decklink-probe'
