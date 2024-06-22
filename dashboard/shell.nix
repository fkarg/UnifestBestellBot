with import <nixpkgs> {};

stdenv.mkDerivation {
    name = "dashboard";
    buildInputs = [
      # misc
      fish
      git
      nodejs_18
      mosquitto
    ];
    shellHook = ''
        export ENVNAME=dashboard
        npm install
        npx parcel build index.html
        # npm run serve
        python3 -m http.server 8003
    '';
}
