{ self }:
{
  config,
  lib,
  pkgs,
  ...
}:
let
  cfg = config.programs.nix-clipboard-history;
  json = pkgs.formats.json { };
  lua = (config.wayland.windowManager.hyprland.configType or "hyprlang") == "lua";
  luaShortcut = lib.concatStringsSep " + " (
    lib.filter (part: part != "") (
      lib.splitString " " (lib.replaceStrings [ "," ] [ " " ] cfg.hyprland.shortcut)
    )
  );
in
{
  options.programs.nix-clipboard-history = {
    enable = lib.mkEnableOption "native clipboard history for Hyprland";
    package = lib.mkOption {
      type = lib.types.package;
      default = self.packages.${pkgs.stdenv.hostPlatform.system}.default;
      description = "Clipboard history package to use.";
    };
    settings = lib.mkOption {
      type = json.type;
      default = { };
      example = {
        max_items = 500;
        retention_days = 30;
        auto_paste = true;
        appearance = {
          theme = "dark";
          accent_color = "#a6e3a1";
          density = "compact";
        };
      };
      description = "Settings written to nix-clipboard-history/config.json. See the README for available keys.";
    };
    extraCss = lib.mkOption {
      type = lib.types.lines;
      default = "";
      example = ''
        @define-color clipboard_bg #1e1e2e;
        @define-color clipboard_preview_bg #181825;
        .clipboard-window .shell { box-shadow: none; }
      '';
      description = "GTK4 CSS written to nix-clipboard-history/style.css and loaded after the built-in theme.";
    };
    hyprland = {
      enable = lib.mkOption {
        type = lib.types.bool;
        default = true;
        description = "Add a Hyprland shortcut. Requires wayland.windowManager.hyprland.enable.";
      };
      shortcut = lib.mkOption {
        type = lib.types.str;
        default = "SUPER SHIFT, V";
        example = "SUPER ALT, V";
        description = "Hyprland modifiers and key used to open the popup.";
      };
    };
  };

  config = lib.mkIf cfg.enable {
    assertions = [
      {
        assertion = !cfg.hyprland.enable || config.wayland.windowManager.hyprland.enable;
        message = "nix-clipboard-history: enable Home Manager's Hyprland module or set programs.nix-clipboard-history.hyprland.enable = false and add the binding yourself.";
      }
    ];
    home.packages = [ cfg.package ];
    xdg.configFile."nix-clipboard-history/config.json".source =
      json.generate "clipboard-config.json" cfg.settings;
    xdg.configFile."nix-clipboard-history/style.css" = lib.mkIf (cfg.extraCss != "") {
      text = cfg.extraCss;
    };

    systemd.user.services.nix-clipboard-history = {
      Unit = {
        Description = "Wayland clipboard history capture";
        Documentation = "https://github.com/kylescudder/nix-clipboard-history";
        PartOf = [ "graphical-session.target" ];
        After = [ "graphical-session.target" ];
      };
      Service = {
        ExecStart = "${lib.getExe cfg.package} daemon";
        Restart = "on-failure";
        RestartSec = 3;
        UMask = "0077";
      };
      Install.WantedBy = [ "graphical-session.target" ];
    };

    wayland.windowManager.hyprland.settings.bind = lib.mkIf cfg.hyprland.enable (
      if lua then
        [
          {
            _args = [
              luaShortcut
              (lib.generators.mkLuaInline "hl.dsp.exec_cmd(${builtins.toJSON "${lib.getExe cfg.package} show"})")
            ];
          }
        ]
      else
        [ "${cfg.hyprland.shortcut}, exec, ${lib.getExe cfg.package} show" ]
    );
  };
}
