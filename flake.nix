{
  description = "Application packaged using poetry2nix";

  inputs.flake-utils.url = "github:numtide/flake-utils";
  inputs.nixpkgs.url = "github:NixOS/nixpkgs";
  inputs.poetry2nix.url = "github:nix-community/poetry2nix";

  outputs = { self, nixpkgs, flake-utils, poetry2nix }:
    {
      # Nixpkgs overlay providing the application
      overlay = nixpkgs.lib.composeManyExtensions [
        poetry2nix.overlay
        (final: prev: {
          aws-artifact-copy = prev.poetry2nix.mkPoetryApplication {
            projectDir = ./.;
            overrides = prev.poetry2nix.overrides.withDefaults (self: super: {
              trio-asyncio = super.trio-asyncio.overridePythonAttrs (old: {
                buildInputs = (old.buildInputs or [ ])
                  ++ [ self.pytest-runner ];
              });
            });
          };
        })
      ];
    } // (flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = import nixpkgs {
          inherit system;
          overlays = [ self.overlay ];
        };
      in rec {
        apps = { aws-artifact-copy = pkgs.aws-artifact-copy; };

        defaultApp = apps.aws-artifact-copy;

        devShell = pkgs.mkShell {
          nativeBuildInputs = with pkgs; [ black nixfmt poetry ];
        };
      }));
}
