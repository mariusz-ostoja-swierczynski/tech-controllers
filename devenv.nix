{
  pkgs,
  lib,
  config,
  ...
}: {
  name = "tech-controllers";

  # https://devenv.sh/basics/
  env = {
    GREET = "tech-controllers devenv";
  };

  # https://devenv.sh/packages/
  packages = [
    pkgs.git
    pkgs.ruff
    pkgs.ffmpeg
    pkgs.libpcap
    pkgs.libjpeg
  ];

  # https://devenv.sh/languages/
  languages.python = {
    enable = true;
    version = "3.13";
    uv.enable = true;
    uv.sync.enable = true;
  };

  # https://devenv.sh/scripts/
  scripts.setup = {
    exec = ''
      echo '🛠️ Running setup'
      # Sync with pyproject.toml via pip
      uv sync --group test_api
    '';
    description = "Install dependencies";
  };

  scripts.develop = {
    exec = ''
      source .devenv/state/venv/bin/activate
      export PYTHONPATH="$PYTHONPATH:$PWD/custom_components"
      export VIRTUAL_ENV="$PWD/.devenv/state/venv"
      export PATH="$VIRTUAL_ENV/bin:$PATH"
      export UV_PYTHON="$VIRTUAL_ENV/bin/python"

      # Remove the externally-managed marker that Nix injects,
      # so uv can install into this venv freely
      find "$VIRTUAL_ENV" -name "EXTERNALLY-MANAGED" -delete

      if [[ ! -d "$PWD/config" ]]; then
          mkdir -p "$PWD/config"
          ln -s "$PWD/custom_components/" "$PWD/config/custom_components"
          "$VIRTUAL_ENV/bin/hass" --config "$PWD/config" --script ensure_config
      fi
      if [ ! -L "$PWD/config/custom_components" ]; then
          ln -s "$PWD/custom_components/" "$PWD/config/custom_components"
      fi

      exec "$VIRTUAL_ENV/bin/hass" --config "$PWD/config" --debug
    '';
    description = "Start Home Assistant";
  };

  scripts.tests = {
    exec = ''
      echo '🧪 Running tests'
      pytest tests/tests_api --cov-report=term-missing --cov=custom_components.tech.tech tests/
    '';
    description = "Test integration";
  };

  scripts.lint = {
    exec = ''
      echo '🚨 Run lint'
      ruff check . --fix
    '';
    description = "Run lint";
  };

  enterShell = ''
    echo Entering development environment for tech-controllers...
    export PYTHONPATH="$PYTHONPATH:$PWD/custom_components"
    echo $PYTHONPATH
    echo
    echo 🦾 Available scripts:
    echo 🦾
    . .devenv/state/venv/bin/activate
    ${pkgs.gnused}/bin/sed -e 's| |••|g' -e 's|=| |' <<EOF | ${pkgs.util-linuxMinimal}/bin/column -t | ${pkgs.gnused}/bin/sed -e 's|^|🦾 |' -e 's|••| |g'
    ${lib.generators.toKeyValue {} (lib.mapAttrs (name: value: value.description) config.scripts)}
    EOF
    echo
  '';

  tasks."app:setup" = {
    exec = ''
      echo '🛠️ Running setup'
      # Sync with pyproject.toml via pip
      uv sync --group test_api
    '';
    after = ["devenv:enterShell"];
  };

  # https://devenv.sh/tests/
  enterTest = ''
    echo '🧪 Running tests'
    pytest tests/tests_api --cov-report=term-missing --cov=custom_components.tech.tech tests/
  '';
}
