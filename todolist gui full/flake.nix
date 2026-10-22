{
  description = "To-do list: desktop program and application server";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs = { self, nixpkgs }:
    let
      systems = [ "x86_64-linux" "aarch64-linux" ];
      forAll = f: nixpkgs.lib.genAttrs systems (system: f nixpkgs.legacyPackages.${system});
    in
    {
      packages = forAll (pkgs: {
        client = pkgs.callPackage ./nix/package.nix { component = "client"; };
        server = pkgs.callPackage ./nix/package.nix { component = "server"; };
        default = self.packages.${pkgs.stdenv.hostPlatform.system}.client;
      });

      apps = forAll (pkgs: {
        default = { type = "app"; program = nixpkgs.lib.getExe self.packages.${pkgs.stdenv.hostPlatform.system}.client; };
        server = { type = "app"; program = nixpkgs.lib.getExe self.packages.${pkgs.stdenv.hostPlatform.system}.server; };
      });

      # services.todolist-server; the package defaults to this flake's server.
      nixosModules.default = { pkgs, lib, ... }: {
        imports = [ ./nix/module.nix ];
        services.todolist-server.package =
          lib.mkDefault self.packages.${pkgs.stdenv.hostPlatform.system}.server;
      };
    };
}
