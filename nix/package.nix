{
  lib,
  python3Packages,
  gtk4,
  gtk4-layer-shell,
  gobject-introspection,
  wrapGAppsHook4,
  wl-clipboard,
  hyprland,
  adwaita-icon-theme,
}:

python3Packages.buildPythonApplication {
  pname = "nix-clipboard-history";
  version = "0.1.0";
  pyproject = true;
  src = lib.cleanSourceWith {
    src = ../.;
    filter =
      path: type:
      lib.cleanSourceFilter path type
      && !(builtins.elem (baseNameOf path) [
        ".venv"
        "__pycache__"
        ".ruff_cache"
        "artifacts"
        "build"
        "dist"
      ])
      && !(lib.hasSuffix ".egg-info" (baseNameOf path));
  };

  build-system = [ python3Packages.setuptools ];
  dependencies = [ python3Packages.pygobject3 ];
  nativeBuildInputs = [
    gobject-introspection
    wrapGAppsHook4
  ];
  buildInputs = [
    gtk4
    gtk4-layer-shell
    adwaita-icon-theme
  ];

  # The Python wrapper also carries GI typelibs, GTK data, and the native library path.
  dontWrapGApps = true;
  preFixup = ''
    makeWrapperArgs+=(
      "''${gappsWrapperArgs[@]}"
      --prefix PATH : ${
        lib.makeBinPath [
          wl-clipboard
          hyprland
        ]
      }
      --set NIX_CLIPBOARD_LAYER_SHELL ${gtk4-layer-shell}/lib/libgtk4-layer-shell.so.0
    )
  '';

  postInstall = ''
    install -Dm644 data/io.github.kylescudder.NixClipboardHistory.desktop \
      $out/share/applications/io.github.kylescudder.NixClipboardHistory.desktop
    install -Dm644 assets/icon.svg \
      $out/share/icons/hicolor/scalable/apps/io.github.kylescudder.NixClipboardHistory.svg
  '';

  checkPhase = ''
    runHook preCheck
    python -m unittest discover -s tests -v
    runHook postCheck
  '';
  pythonImportsCheck = [ "nix_clipboard_history" ];

  meta = {
    description = "Searchable text and image clipboard history for Hyprland";
    homepage = "https://github.com/kylescudder/nix-clipboard-history";
    license = lib.licenses.mit;
    mainProgram = "nix-clipboard-history";
    platforms = lib.platforms.linux;
  };
}
