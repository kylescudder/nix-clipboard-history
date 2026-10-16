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
- Dark and light themes, custom colours and fonts, compact layout, and GTK CSS overrides.
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
for the current session. For a Lua configuration (`hyprland.lua`):

```sh
hyprctl eval "hl.bind('SUPER + SHIFT + V', hl.dsp.exec_cmd('$(realpath result)/bin/nix-clipboard-history show'))"
```

For a legacy configuration (`hyprland.conf`):

```sh
hyprctl keyword bind "SUPER SHIFT, V, exec, $(realpath result)/bin/nix-clipboard-history show"
```

If `hyprctl keyword` reports `keyword can't work with non-legacy parsers. Use eval.`,
use the Lua command above. See Hyprland's [runtime configuration documentation](https://wiki.hypr.land/configuring/core/advanced-configuration/using-hyprctl/#eval).

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
      appearance = {
        theme = "dark"; # or "light"
        accent_color = "#a6e3a1";
        density = "compact";
      };
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

### Home Manager option reference

These options live under `programs.nix-clipboard-history`:

| Option | Default | Purpose |
| --- | --- | --- |
| `enable` | `false` | Install the app, write its config, and enable the capture service. |
| `package` | This flake's default package for your system | Override the package to install and run. |
| `settings` | `{ }` | Configuration written as JSON; accepts every setting in [Configuration](#configuration), including `appearance`. |
| `extraCss` | `""` | GTK4 CSS text; a nonempty value writes `style.css`. See [Themes and appearance](#themes-and-appearance). |
| `hyprland.enable` | `true` | Add the popup shortcut; requires Home Manager's Hyprland module to be enabled. Set `false` to manage the shortcut yourself. |
| `hyprland.shortcut` | `"SUPER SHIFT, V"` | Shortcut in Hyprland modifier/key syntax, for example `"SUPER ALT, V"`; also converted for Lua configurations. |

Manage these files through your Home Manager configuration when using the module.
After changing `settings` or `extraCss`, apply your usual rebuild, then reopen the
popup. Restart the capture service too if capture settings changed.

## Keyboard controls

- **Super+Shift+V**: open the popup.
- **Type**: search; all search words must match, in any order.
- **← / →**: cycle categories: All, Text & links, Images, and Pinned.
- **↑ / ↓**: select an item; **Enter**: paste into the previous app.
- **Ctrl+Enter**: copy the selected item without pasting.
- **Alt+1…9**: paste one of the first nine visible items.
- **Ctrl+P**: pin or unpin; **Ctrl+Backspace** / **Ctrl+Delete**: delete the item.
- **Ctrl+1…4**: select All, Text & links, Images, or Pinned.
- **Ctrl+F**: focus search; **Esc** or a click outside the popup: close.
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

### General setting reference

| Setting | Default | Accepted values and effect |
| --- | --- | --- |
| `max_items` | `500` | Integer ≥ 1. History item budget, including pins. |
| `retention_days` | `30` | Integer ≥ 1. Expire unpinned items this many days after their last copy. |
| `max_item_bytes` | `10485760` (10 MiB) | Integer ≥ 1. Skip new captures larger than this many bytes. |
| `max_total_bytes` | `268435456` (256 MiB) | Integer ≥ 1. Total stored clipboard payload budget, including pins. |
| `auto_paste` | `true` | Boolean. Paste after selection; `false` copies the item and closes the popup. |
| `paste_delay_ms` | `160` | Integer from 0 to 5000. Delay after closing the popup before restoring focus and pasting. |
| `capture_images` | `true` | Boolean. Record supported images; `false` uses text from mixed offers and skips image-only offers. |
| `excluded_apps` | `[]` | List of application class strings to exclude from capture, using exact, case-insensitive matches against the focused app. |
| `terminal_classes` | List below | List of application class strings that receive Ctrl+Shift+V; exact, case-insensitive matching. Replaces the default list. |
| `appearance` | Defaults below | Object containing the settings in [Themes and appearance](#themes-and-appearance). |

Use JSON numbers for integer settings and JSON `true`/`false` for booleans.
Unknown keys, wrong types, and out-of-range values are rejected with an error.
Omitted settings use their defaults; omitted fields inside `appearance` do too.
There is no `0` or `null` value to disable the history limits.

The defaults retain up to 500 items and 256 MiB of clipboard payload, with a
30-day expiry and 10 MiB per-item limit. Pins survive automatic pruning and count
toward the budgets; pins alone may exceed them. Database indexes, searchable
text, and SQLite free pages take additional space. Age-based pruning runs every
minute, at service startup, and when opening the popup.

`paste_delay_ms` allows keyboard focus to settle after the popup is destroyed.
The app restores the original Hyprland window, confirms focus, and then sends
the paste shortcut. Enter activates on release; quick selection waits for held
modifiers to be released. A failed paste leaves the item copied and reports an
error on stderr without reopening the popup. `show --copy-only` disables
automatic paste for that invocation.

`terminal_classes` replaces the built-in list of terminal app classes that
receive **Ctrl+Shift+V** instead of **Ctrl+V**. The exact default is:

```json
[
  "kitty",
  "Alacritty",
  "foot",
  "footclient",
  "org.wezfurlong.wezterm",
  "com.mitchellh.ghostty",
  "Ghostty",
  "org.gnome.Terminal",
  "org.gnome.Console",
  "konsole",
  "com.raggesilver.BlackBox",
  "xterm",
  "st-256color"
]
```

Use `hyprctl -j activewindow` to find an app's class. Setting
`"terminal_classes": []` makes every app receive **Ctrl+V**. A terminal using
different paste keys can use copy-only mode.

Restart the capture service after changing capture settings. Reopen the popup to
reload its settings; appearance changes only require reopening the popup.

### Themes and appearance

Add an `appearance` object to `config.json`, or set `settings.appearance` in
Home Manager. Omitted fields keep their defaults, so existing configurations
keep the dark theme and original layout. For example:

```json
{
  "appearance": {
    "theme": "light",
    "accent_color": "#0f766e",
    "font_family": "Noto Sans",
    "monospace_font_family": "Fira Code",
    "font_size": 14,
    "density": "compact",
    "border_radius": 12,
    "window_width": 960,
    "window_height": 680,
    "show_preview": true
  }
}
```

| Setting | Default | Accepted values |
| --- | --- | --- |
| `theme` | `"dark"` | `"dark"` or `"light"` |
| `accent_color` | `""` | `""` for the theme default (`#b8c8ff` dark, `#365ad6` light), or `"#RRGGBB"`; hex letters are case-insensitive |
| `font_family` | `"Inter"` | A single nonblank font family name without control characters |
| `monospace_font_family` | `"JetBrains Mono"` | A single nonblank preview font family name without control characters |
| `font_size` | `13` | Integer from 10 to 24. Base font size in pixels; scales all popup text |
| `density` | `"comfortable"` | `"comfortable"` or `"compact"` |
| `border_radius` | `18` | Integer from 0 to 32. Popup corner radius in pixels |
| `window_width` | `880` | Integer from 600 to 1600. Requested popup width in logical pixels |
| `window_height` | `640` | Integer from 400 to 1200. Requested popup height in logical pixels |
| `show_preview` | `true` | Boolean; `false` gives the history list the full content width |

The accent colour applies to buttons, selected items, tabs, and focus outlines.
Button text automatically uses a contrasting black or white colour. Fonts fall
back to Noto Sans/DejaVu Sans and DejaVu Sans Mono when the requested font is
unavailable. Popup dimensions are constrained by the active monitor and GTK's
minimum content size; larger fonts may need a wider or taller popup.

For a complete custom theme, create
`$XDG_CONFIG_HOME/nix-clipboard-history/style.css`
(`~/.config/nix-clipboard-history/style.css` by default). It uses GTK4 CSS and
loads after the built-in theme and appearance settings. You can override named
colours or widget styles:

```css
@define-color clipboard_bg #1e1e2e;
@define-color clipboard_preview_bg #181825;
@define-color clipboard_fg #cdd6f4;
@define-color clipboard_muted #a6adc8;
@define-color clipboard_border #45475a;

.clipboard-window .shell { box-shadow: none; }
.clipboard-window .history-row { border-radius: 4px; }
```

All named colours and their defaults are listed below. Define them using
`@define-color` and reference them as `@clipboard_bg`, for example.

| Colour name | Dark default | Light default | Used for |
| --- | --- | --- | --- |
| `clipboard_bg` | `#17191f` | `#f8f9fc` | Main popup surface. |
| `clipboard_preview_bg` | `#14171d` | `#f0f2f7` | Preview surface. |
| `clipboard_fg` | `#e7e9ef` | `#222838` | Main text and icons. |
| `clipboard_muted` | `#8f95a6` | `#596479` | Secondary text and controls. |
| `clipboard_subtle` | `#7e8aa3` | `#647087` | Metadata, hints, and keycaps. |
| `clipboard_border` | `#353842` | `#cbd1dd` | Popup and search borders. |
| `clipboard_divider` | `#2c303a` | `#dce0e9` | Panel and toolbar separators. |
| `clipboard_input_bg` | `#20232b` | `#ffffff` | Search field surface. |
| `clipboard_hover_bg` | `#222630` | `#e8ecf4` | Hovered controls and rows. |
| `clipboard_icon_bg` | `#252b38` | `#e3e8f2` | Item icon and keycap surfaces. |
| `clipboard_scrollbar` | `#3b4150` | `#b3bdcf` | Scrollbar slider. |
| `clipboard_accent` | `#b8c8ff` | `#365ad6` | Primary button, focus, and colours mixed into selections. |
| `clipboard_accent_fg` | `#000000` | `#ffffff` | Primary button text; calculated from `appearance.accent_color`. |
| `clipboard_danger` | `#ff9aab` | `#a32142` | Destructive action text. |
| `clipboard_danger_bg` | `#492735` | `#fbe4ea` | Destructive action surface. |

When replacing the accent in CSS, set its foreground colour too. Useful widget
classes include `.header`,
`.search-box`, `.filter`, `.history-row`, `.item-title`, `.item-meta`, `.preview`,
`.text-preview`, `.footer`, and `.primary`. The
[built-in stylesheet](nix_clipboard_history/style.css) contains the full selector
reference. Use installed fonts or the documented fallbacks in your custom CSS.

Home Manager can write this file declaratively:

```nix
programs.nix-clipboard-history.extraCss = ''
  @define-color clipboard_bg #1e1e2e;
  @define-color clipboard_preview_bg #181825;
  .clipboard-window .shell { box-shadow: none; }
'';
```

Reopen the popup after editing your theme. Unreadable or invalid custom CSS
reports a warning on stderr and falls back to the built-in appearance settings.

## Storage and privacy

History stays on this machine in
`$XDG_DATA_HOME/nix-clipboard-history/history.sqlite3`
(`~/.local/share/nix-clipboard-history/` by default). The directory is mode `0700`
and the database and journal files are `0600`. **History is not encrypted.**

The native watcher skips offers carrying `x-kde-passwordManagerHint` before
requesting their contents. The capture helper also ignores
`CLIPBOARD_STATE=sensitive`, `nil`, and `clear`. Password managers must actually
mark their copies as sensitive for that protection to apply.
`excluded_apps` matches Hyprland's focused application class, case-insensitively;
Wayland does not provide reliable clipboard-owner attribution, so this is a
best-effort extra filter. Pause recording before copying anything you do not
want retained. Clearing history is not a guarantee of forensic erasure from
backups or storage media.

Text is stored and pasted as UTF-8 plain text, preserving whitespace. PNG, JPEG,
GIF, WebP, TIFF, and BMP images preserve their original bytes and MIME type.
Each clipboard offer produces at most one record. Capture prefers an available
supported image (PNG, JPEG, WebP, GIF, TIFF, then BMP), then UTF-8/plain text.
Unsupported image formats never mask a supported alternative. With
`capture_images = false`, mixed offers use their text representation instead.
Image previews depend on the installed GdkPixbuf loaders. Rich formatting, file
offers, primary-selection history, and OCR are outside the current feature set.

## Commands and troubleshooting

Run `nix-clipboard-history` without a command to open the popup. The complete
command reference is:

| Command | Arguments and options | Behaviour |
| --- | --- | --- |
| `show` | `--copy-only`, `--windowed` | Open the popup. `--copy-only` disables automatic paste for this invocation. `--windowed` uses a regular GTK window for development. |
| `daemon` | None | Watch the Wayland clipboard; run one capture service per session. |
| `capture` | `--kind text\|image\|auto` (default `text`) | Read one item from stdin; used by the native watcher. See below. |
| `list` | Optional `query`, `--kind all\|text\|image\|pinned` (default `all`), `--limit N` (default `100`, integer ≥ 1) | Print JSON metadata, with pins first and then newest copies. All query words must match text/source, case-insensitively. Full clipboard bodies are omitted. |
| `copy` | Required item `id` | Copy the item to the clipboard without pasting. |
| `pin` | Required item `id` | Toggle the item's pin. |
| `delete` | Required item `id` | Delete the history item. |
| `clear` | Required `--yes`, optional `--all` | Delete unpinned history; add `--all` to include pins. Leaves the live clipboard unchanged. |
| `pause` | None | Pause capture; persists across restarts. |
| `resume` | None | Resume capture. |
| `status` | None | Print JSON with `items`, `pinned`, payload `bytes`, `paused`, and `daemon_running`. |

Use `nix-clipboard-history --version` to print the version. `-h` / `--help`
works globally and after any command, for example
`nix-clipboard-history list --help`. Put popup flags after `show`, for example
`nix-clipboard-history show --copy-only`.

`capture --kind text` expects UTF-8 plain text. `--kind image` detects a supported
image format from its bytes. `--kind auto` uses the watcher's `CLIPBOARD_TYPE`
environment variable to select text or image; unsupported or missing types are
ignored. Capture is skipped when paused, when the focused application is excluded,
or when `CLIPBOARD_STATE` is anything other than `data` (the default when unset).
Empty, invalid, unsupported, or oversized content is not retained.

Common examples:

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
environment. The watcher requires a compositor with wlr data-control;
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
nix build
env PYTHONPATH=. python tests/wayland_smoke.py --package ./result
```

The GTK smoke test exercises the real widget tree under Xvfb with the default,
light, compact, custom, and invalid-CSS fallback styles. It writes screenshots
to `artifacts/clipboard*.png`. Its clipboard transfer is stubbed. The
Wayland smoke test uses an isolated headless Sway session to check real
text/image capture, clipboard ownership, sensitive hints, daemon lifecycle,
and the GTK layer-shell overlay. Real pointer and keyboard events verify outside
clicks on both monitors, arrow-key selection followed by Enter, Alt quick
selection, and copy-only behavior. A separate GTK text input receives the pasted
text; Hyprland IPC is adapted to Sway for this integration test.
Multi-format clipboard checks verify one record per offer, SVG-before-PNG
selection, image priority, text fallback, sensitive hints, and disabled images.
The `--package` option runs the installed daemon outside the checkout with Python
import paths cleared, so development files cannot hide packaging errors. Omit it
to test the daemon directly from source.
Automatic paste should also be verified in a live Hyprland session.
`show --windowed` opens a regular window for UI development.

Built with Python, a small native Wayland watcher, GTK4,
[gtk4-layer-shell](https://github.com/wmww/gtk4-layer-shell), wl-clipboard, and SQLite.
MIT licensed. The Nix package builds and installs the watcher automatically.
