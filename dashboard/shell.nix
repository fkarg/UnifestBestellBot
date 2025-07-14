with import <nixpkgs> {};

stdenv.mkDerivation {
    name = "dashboard";
    buildInputs = [
      # misc
      fish
      git
      nodejs
      mosquitto
    ];
    shellHook = ''
        export ENVNAME=dashboard
        npm install
        npx parcel build index.html
        # npm run serve
        python3 -m http.server --directory dist 80
    '';
}
