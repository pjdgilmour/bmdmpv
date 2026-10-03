#!/bin/sh
# Install for bash-completion's per-user lazy loader; no .bashrc edits.
set -eu
base=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
destination=${XDG_DATA_HOME:-$HOME/.local/share}/bash-completion/completions
mkdir -p "$destination"
install -m 644 "$base/completions/mpv-decklink" "$destination/mpv-decklink"
printf 'Autocompletar Bash instalado em %s/mpv-decklink\n' "$destination"
