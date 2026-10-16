{
  description = "A native clipboard history for Nix and Hyprland";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    home-manager = {
      url = "github:nix-community/home-manager";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs =
    {
      self,
      nixpkgs,
      home-manager,
    }:
    let
      systems = [
        "x86_64-linux"
        "aarch64-linux"
      ];
      forAllSystems = nixpkgs.lib.genAttrs systems;
      pkgsFor = system: import nixpkgs { inherit system; };
    in
    {
      packages = forAllSystems (
        system:
        let
          package = (pkgsFor system).callPackage ./nix/package.nix { };
        in
        {
          default = package;
          nix-clipboard-history = package;
        }
      );

      apps = forAllSystems (system: {
        default = {
          type = "app";
          program = "${self.packages.${system}.default}/bin/nix-clipboard-history";
          meta.description = "Open the native clipboard history popup";
        };
      });

      homeManagerModules.default = import ./nix/home-manager.nix { inherit self; };

      checks = forAllSystems (
        system:
        let
          pkgs = pkgsFor system;
          makeHome =
            configType:
            home-manager.lib.homeManagerConfiguration {
              inherit pkgs;
              modules = [
                self.homeManagerModules.default
                {
                  home = {
                    username = "clipboard-test";
                    homeDirectory = "/home/clipboard-test";
                    stateVersion = "26.05";
                  };
                  wayland.windowManager.hyprland.enable = true;
                  wayland.windowManager.hyprland.configType = configType;
                  programs.nix-clipboard-history.enable = true;
                }
              ];
            };
          checkHome =
            configType:
            let
              home = makeHome configType;
              extension = if configType == "lua" then "lua" else "conf";
              generated = home.config.xdg.configFile."hypr/hyprland.${extension}".text;
            in
            assert nixpkgs.lib.hasInfix "nix-clipboard-history show" generated;
            assert nixpkgs.lib.hasInfix (
              if configType == "lua" then "SUPER + SHIFT + V" else "SUPER SHIFT, V"
            ) generated;
            pkgs.writeText "clipboard-home-manager-${configType}-check" (
              builtins.toJSON {
                service = home.config.systemd.user.services.nix-clipboard-history;
                inherit generated;
                settings = home.config.xdg.configFile."nix-clipboard-history/config.json".source;
                assertions = map (
                  a:
                  assert a.assertion;
                  a.message
                ) home.config.assertions;
              }
            );
        in
        {
          package = self.packages.${system}.default;
          home-manager-hyprlang = checkHome "hyprlang";
          home-manager-lua = checkHome "lua";
        }
      );

      devShells = forAllSystems (
        system:
        let
          pkgs = pkgsFor system;
        in
        {
          default = pkgs.mkShell {
            inputsFrom = [ self.packages.${system}.default ];
            packages = [
              (pkgs.python3.withPackages (ps: [
                ps.pygobject3
                ps.setuptools
              ]))
              pkgs.ruff
              pkgs.nixfmt
              pkgs.wl-clipboard
              pkgs.xvfb-run
              pkgs.dbus
              pkgs.imagemagick
              pkgs.dejavu_fonts
              pkgs.sway-unwrapped
              pkgs.wtype
              pkgs.wlrctl
              pkgs.grim
              pkgs.pkg-config
              pkgs.wayland
              pkgs.wayland-scanner
            ];
            shellHook = ''
              export NIX_CLIPBOARD_LAYER_SHELL=${pkgs.gtk4-layer-shell}/lib/libgtk4-layer-shell.so.0
              export WLR_POINTER_PROTOCOL=${pkgs.wlr-protocols}/share/wlr-protocols/unstable/wlr-virtual-pointer-unstable-v1.xml
              export FONTCONFIG_FILE=${pkgs.makeFontsConf { fontDirectories = [ pkgs.dejavu_fonts ]; }}
              export DBUS_SESSION_CONFIG=${pkgs.dbus}/share/dbus-1/session.conf
              export XDG_DATA_DIRS=${pkgs.adwaita-icon-theme}/share:${pkgs.gtk4}/share:''${XDG_DATA_DIRS:-/usr/local/share:/usr/share}
            '';
          };
        }
      );

      formatter = forAllSystems (system: (pkgsFor system).nixfmt);
    };
}
