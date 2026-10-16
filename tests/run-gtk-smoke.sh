#!/usr/bin/env bash
set -euo pipefail

test_dir=$(mktemp -d)
trap 'rm -rf "$test_dir"' EXIT
export GDK_BACKEND=x11
export GSK_RENDERER=cairo
export GTK_A11Y=none
export PYTHONPATH="$PWD${PYTHONPATH:+:$PYTHONPATH}"

for appearance in default light compact custom invalid; do
  export XDG_DATA_HOME="$test_dir/$appearance/data"
  export XDG_CONFIG_HOME="$test_dir/$appearance/config"
  export GTK_SMOKE_APPEARANCE="$appearance"
  xvfb-run -a -s '-screen 0 1280x800x24' \
    dbus-run-session --config-file="$DBUS_SESSION_CONFIG" -- python tests/gtk_smoke.py
done
