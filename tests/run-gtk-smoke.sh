#!/usr/bin/env bash
set -euo pipefail

test_dir=$(mktemp -d)
trap 'rm -rf "$test_dir"' EXIT
export XDG_DATA_HOME="$test_dir/data"
export XDG_CONFIG_HOME="$test_dir/config"
export GDK_BACKEND=x11
export GSK_RENDERER=cairo
export GTK_A11Y=none
export PYTHONPATH="$PWD${PYTHONPATH:+:$PYTHONPATH}"

xvfb-run -a -s '-screen 0 1280x800x24' \
  dbus-run-session --config-file="$DBUS_SESSION_CONFIG" -- python tests/gtk_smoke.py
