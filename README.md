<img src="assets/icon.svg" width="96" height="96" alt="Clipboard History logo">

# Clipboard History

A native clipboard popup for **Nix and Hyprland**, inspired by Raycast's clipboard
history and Windows' Win+V. Press **Super+Shift+V**, search, and press **Enter** to paste
an older copy into the app you were using.

- Persistent text, links, and images, with a preview beside the history.
- Search across text and source application names; filter by text, images, or pins.
- Pin frequently used items. Repeated copies move up without creating duplicates.
- Automatic paste, including Ctrl+Shift+V for terminal applications.
- Copy without pasting, pause recording, delete individual items, or clear history.
- A Nix flake, desktop launcher, and Home Manager module with a session service.

Requires Linux, a running Hyprland session, and Nix with flakes enabled. Packages
are exposed for `x86_64-linux` and `aarch64-linux`.

## Try it from this checkout

In a terminal **inside Hyprland**, build the package and start the capture service:

```sh
nix build path:.
./result/bin/nix-clipboard-history daemon
```

Leave it running. In a second terminal, from the same checkout, add a shortcut
for the current session:

```sh
hyprctl keyword bind "SUPER SHIFT, V, exec, $(realpath result)/bin/nix-clipboard-history show"
```

Copy two different pieces of text, focus a text field in another app, then press
**Super+Shift+V**, choose the older item, and press **Enter**. It should paste
into that field. Try copying an image, searching, pinning with **Ctrl+P**, and
copying without pasting with **Ctrl+Enter**.

The shortcut lasts until Hyprland reloads its configuration. Stop the daemon with
**Ctrl+C**. These commands do not install a login service; use the Home Manager
module below for persistent setup. Run one capture service per session; if the
Home Manager service is already running, use it instead of starting another daemon.

For a quick look without a shortcut, run `./result/bin/nix-clipboard-history show`.
Automatic paste then targets the terminal you launched it from.

### Test from macOS

The native popup needs Linux/Wayland. The core tests run directly on macOS:

```sh
python3 -m unittest discover -s tests -v
```

With Docker running, you can also exercise the actual GTK interface in Linux
and capture a screenshot, without installing Nix on your Mac:

```sh
docker run --rm \
  -v "$PWD:/work" -w /work \
  -v nix-clipboard-history-store:/nix \
  nixos/nix:latest \
  nix --extra-experimental-features 'nix-command flakes' develop path:/work \
  --command bash tests/run-gtk-smoke.sh
```

The screenshot is written to `artifacts/clipboard.png`. To test real Wayland
capture and the layer-shell popup under headless Sway, replace the final line with
`--command env PYTHONPATH=. python tests/wayland_smoke.py`. Automatic paste into
your apps still needs a live Hyprland session.

## Home Manager

Add this project to your configuration's flake inputs. Until your changes are
pushed, use `path:/absolute/path/to/nix-clipboard-history` for the URL.

```nix
inputs.nix-clipboard-history = {
  url = "github:kylescudder/nix-clipboard-history";
  inputs.nixpkgs.follows = "nixpkgs";
  inputs.home-manager.follows = "home-manager";
};
```

Import the module into your **Home Manager** modules (including when Home Manager
is embedded in NixOS):

```nix
{ inputs, ... }: {
  imports = [ inputs.nix-clipboard-history.homeManagerModules.default ];

  wayland.windowManager.hyprland.enable = true;

  programs.nix-clipboard-history = {
    enable = true;
    settings = {
      max_items = 500;
      retention_days = 30;
      auto_paste = true;
      excluded_apps = [ "1Password" "org.keepassxc.KeePassXC" ];
    };
    # hyprland.shortcut = "SUPER ALT, V"; # optional override
  };
}
```

Pass `inputs` through `extraSpecialArgs` if your configuration uses the example's
module function. Alternatively, refer to the input directly where you assemble
your Home Manager module list.

Apply your usual Home Manager/NixOS rebuild, then log into Hyprland. The module
installs the app, writes its settings, starts capture with
`graphical-session.target`, and adds **Super+Shift+V**. Both Home Manager's `hyprlang`
and `lua` configuration formats are supported. Remove any existing binding for
the same shortcut from your config.

Home Manager's Hyprland systemd integration (enabled by default), or a session
manager such as UWSM, must import the Wayland environment and start the graphical
session target. If you apply the module during an existing session:

```sh
systemctl --user import-environment WAYLAND_DISPLAY HYPRLAND_INSTANCE_SIGNATURE XDG_CURRENT_DESKTOP
systemctl --user restart nix-clipboard-history.service
```

If you manage Hyprland outside Home Manager, set
`programs.nix-clipboard-history.hyprland.enable = false` and add the shortcut
yourself. For a legacy `hyprland.conf`:

```ini
bind = SUPER SHIFT, V, exec, nix-clipboard-history show
```

For `hyprland.lua`:

```lua
hl.bind("SUPER + SHIFT + V", hl.dsp.exec_cmd("nix-clipboard-history show"))
```

Without Home Manager, install the package using `nix profile add path:.`, add the
shortcut above, and launch `nix-clipboard-history daemon` once at session start.

## Keyboard controls

- **Super+Shift+V**: open the popup.
- **Type**: search; all search words must match, in any order.
- **↑ / ↓**: select an item; **Enter**: paste into the previous app.
- **Ctrl+Enter**: copy the selected item without pasting.
- **Alt+1…9**: paste one of the first nine visible items.
- **Ctrl+P**: pin or unpin; **Ctrl+Backspace** / **Ctrl+Delete**: delete the item.
- **Ctrl+1…4**: select All, Text & links, Images, or Pinned.
- **Ctrl+F**: focus search; **Esc**: close.
- Double-click a row to paste it; single-click to preview it.

The pause button stops recording until resumed, including across restarts. The
clear button requires a second click and keeps pins. Deleting history leaves
the live system clipboard unchanged.

## Configuration

Home Manager writes `$XDG_CONFIG_HOME/nix-clipboard-history/config.json`
(`~/.config/nix-clipboard-history/config.json` by default). Without Home Manager,
create that JSON file yourself. All settings are optional:

```json
{
  "max_items": 500,
  "retention_days": 30,
  "max_item_bytes": 10485760,
  "max_total_bytes": 268435456,
  "auto_paste": true,
  "paste_delay_ms": 160,
  "capture_images": true,
  "excluded_apps": []
}
```

The defaults retain up to 500 items and 256 MiB of clipboard payload, with a
30-day expiry and 10 MiB per-item limit. Pins survive automatic pruning and count
toward the budgets; pins alone may exceed them. Database indexes, searchable
text, and SQLite free pages take additional space. Age-based pruning runs every
minute, at service startup, and when opening the popup.

`paste_delay_ms` allows keyboard focus to return after closing the popup. The
app verifies that the original Hyprland window is still focused before sending
a paste shortcut. If focus changes, it leaves the item copied and displays an
explanation. `show --copy-only` disables automatic paste for that invocation.

`terminal_classes` can replace the built-in list of terminal app classes that
receive **Ctrl+Shift+V** instead of **Ctrl+V**. The default includes kitty,
Alacritty, foot, WezTerm, Ghostty, GNOME Terminal/Console, Konsole, Black Box,
xterm, and st. Use `hyprctl -j activewindow` to find an app's class. A terminal
using different paste keys can use copy-only mode.

Restart the capture service after changing settings. Reopen the popup to reload
its settings.

## Storage and privacy

History stays on this machine in
`$XDG_DATA_HOME/nix-clipboard-history/history.sqlite3`
(`~/.local/share/nix-clipboard-history/` by default). The directory is mode `0700`
and the database and journal files are `0600`. **History is not encrypted.**

Capture ignores `CLIPBOARD_STATE=sensitive`, `nil`, and `clear`, as supplied by
[wl-clipboard](https://github.com/bugaevc/wl-clipboard). Password managers must
actually mark their copies as sensitive for that protection to apply.
`excluded_apps` matches Hyprland's focused application class, case-insensitively;
Wayland does not provide reliable clipboard-owner attribution, so this is a
best-effort extra filter. Pause recording before copying anything you do not
want retained. Clearing history is not a guarantee of forensic erasure from
backups or storage media.

Text is stored and pasted as UTF-8 plain text, preserving whitespace. PNG, JPEG,
GIF, WebP, TIFF, and BMP images preserve their original bytes and MIME type.
Image previews depend on the installed GdkPixbuf loaders. Rich formatting, file
offers, primary-selection history, and OCR are outside the current feature set.

## Commands and troubleshooting

```sh
nix-clipboard-history status                 # counts, payload size, paused/running state
nix-clipboard-history list "search words"    # JSON metadata; full body omitted
nix-clipboard-history list --kind pinned
nix-clipboard-history copy 42
nix-clipboard-history pin 42                 # toggle pin
nix-clipboard-history delete 42
nix-clipboard-history pause
nix-clipboard-history resume
nix-clipboard-history clear --yes            # keep pins
nix-clipboard-history clear --all --yes      # include pins
journalctl --user -u nix-clipboard-history -e
```

If capture is offline, check the service logs and confirm that
`WAYLAND_DISPLAY` and `HYPRLAND_INSTANCE_SIGNATURE` are in the service's
environment. The watcher requires a compositor with Wayland data-control;
Hyprland supplies it. Another clipboard manager can record the same copies, so
disable its recording service if you intend this app to own your history.

## Development

The storage, configuration, and CLI tests use only the Python standard library:

```sh
python3 -m unittest discover -s tests -v
```

On Linux, the flake provides GTK, layer-shell, wl-clipboard, and development tools:

```sh
nix develop
python -m nix_clipboard_history daemon
python -m nix_clipboard_history show
ruff check nix_clipboard_history tests
ruff format --check nix_clipboard_history tests
nix fmt -- --check flake.nix nix/*.nix
nix flake check
bash tests/run-gtk-smoke.sh
env PYTHONPATH=. python tests/wayland_smoke.py
```

The GTK smoke test exercises the real widget tree under Xvfb and writes a
screenshot to `artifacts/clipboard.png`. Its clipboard transfer is stubbed. The
Wayland smoke test uses an isolated headless Sway session to check real
text/image capture, clipboard ownership, sensitive hints, daemon lifecycle,
and the GTK layer-shell overlay.
Automatic paste should also be verified in a live Hyprland session.
`show --windowed` opens a regular window for UI development.

Built with Python, GTK4, [gtk4-layer-shell](https://github.com/wmww/gtk4-layer-shell),
wl-clipboard, and SQLite. MIT licensed.
