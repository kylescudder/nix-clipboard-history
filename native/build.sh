#!/usr/bin/env bash
set -euo pipefail

build_dir=${1:-build/native}
mkdir -p "$build_dir"
wayland-scanner client-header "$WLR_DATA_CONTROL_PROTOCOL" "$build_dir/data-control-client.h"
wayland-scanner private-code "$WLR_DATA_CONTROL_PROTOCOL" "$build_dir/data-control.c"
read -r -a wayland_flags <<< "$(pkg-config --cflags --libs wayland-client)"
"${CC:-cc}" -std=c11 -Wall -Wextra -Werror -Wno-unused-parameter \
  native/watch.c "$build_dir/data-control.c" -I "$build_dir" \
  "${wayland_flags[@]}" -o "$build_dir/nix-clipboard-history-watch"
