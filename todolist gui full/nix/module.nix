# NixOS: the to-do list's application server as a system service.
#
#   services.todolist-server = {
#     enable = true;
#     openFirewall = true;   # reachable from the phone and other computers
#   };
#
# Then create the first administrator:  sudo todolist-server-admin create-admin --name ... --email ...
# The database (and its backups/ folder) is in dataDir, owned by the user todolist-server.
{ config, lib, pkgs, ... }:

let
  cfg = config.services.todolist-server;
  database = "${cfg.dataDir}/todo_server.db";
  # The account commands (create-admin, set-password) on the service's database, as its user.
  admin = pkgs.writeShellScriptBin "todolist-server-admin" ''
    if [ "$(id -u)" != 0 ]; then
      echo "Run it with sudo: sudo todolist-server-admin $*" >&2
      exit 1
    fi
    exec ${pkgs.util-linux}/bin/runuser -u todolist-server -- \
      ${lib.getExe cfg.package} --db ${lib.escapeShellArg database} "$@"
  '';
in
{
  options.services.todolist-server = {
    enable = lib.mkEnableOption "the to-do list application server";

    package = lib.mkOption {
      type = lib.types.package;
      description = "The server package (the flake's packages.<system>.server).";
    };

    host = lib.mkOption {
      type = lib.types.str;
      default = "0.0.0.0";
      description = "Address to listen on: 0.0.0.0 for every network, 127.0.0.1 for this computer only.";
    };

    port = lib.mkOption {
      type = lib.types.port;
      default = 8000;
    };

    openFirewall = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = "Open the port in the firewall (needed for phones and other computers).";
    };

    tokenDays = lib.mkOption {
      type = lib.types.ints.positive;
      default = 30;
      description = "How many days a login stays valid.";
    };

    dataDir = lib.mkOption {
      type = lib.types.path;
      default = "/var/lib/todolist-server";
      description = "Folder of the database (todo_server.db) and its backups.";
    };
  };

  config = lib.mkIf cfg.enable {
    users.users.todolist-server = {
      isSystemUser = true;
      group = "todolist-server";
      home = cfg.dataDir;
    };
    users.groups.todolist-server = { };

    systemd.tmpfiles.settings.todolist-server.${cfg.dataDir}.d = {
      user = "todolist-server";
      group = "todolist-server";
      mode = "0750";
    };

    systemd.services.todolist-server = {
      description = "To-do list application server";
      wantedBy = [ "multi-user.target" ];
      after = [ "network.target" ];
      serviceConfig = {
        ExecStart = lib.escapeShellArgs [
          (lib.getExe cfg.package)
          "--db" database
          "run"
          "--host" cfg.host
          "--port" (toString cfg.port)
          "--token-days" (toString cfg.tokenDays)
        ];
        User = "todolist-server";
        Group = "todolist-server";
        WorkingDirectory = cfg.dataDir;
        Restart = "on-failure";
        # It needs nothing but its own folder.
        ReadWritePaths = [ cfg.dataDir ];
        ProtectSystem = "strict";
        ProtectHome = true;
        PrivateTmp = true;
        PrivateDevices = true;
        NoNewPrivileges = true;
        ProtectKernelTunables = true;
        ProtectKernelModules = true;
        ProtectControlGroups = true;
        RestrictAddressFamilies = [ "AF_INET" "AF_INET6" "AF_UNIX" ];
        RestrictNamespaces = true;
        LockPersonality = true;
        SystemCallArchitectures = "native";
      };
    };

    networking.firewall.allowedTCPPorts = lib.mkIf cfg.openFirewall [ cfg.port ];
    environment.systemPackages = [ admin ];
  };
}
