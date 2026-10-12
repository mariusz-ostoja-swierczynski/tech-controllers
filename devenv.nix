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
    version = "3.14";
    uv.enable = true;
    uv.sync.enable = true;
  };

  # https://devenv.sh/scripts/
  scripts.setup = {
    exec = ''
      echo '🛠️ Running setup'
      # Sync with pyproject.toml via pip
      # The Home Assistant suite needs the `test` group on top of `test_api`.
      uv sync --group test_api --group test
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
      pytest tests/ --cov-report= --cov=custom_components.tech
      echo '🧪 Running Home Assistant tests'
      pytest tests_ha/ --cov-report=term-missing --cov-report=json --cov=custom_components.tech --cov-append --cov-fail-under=95
      echo '🧪 Checking every module'
      python script/check_module_coverage.py
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

  scripts.typecheck = {
    exec = ''
      echo '🔍 Typecheck the integration'
      mypy
    '';
    description = "Typecheck the integration";
  };

  enterShell = ''
    echo Entering development environment for tech-controllers...
    export PYTHONPATH="$PYTHONPATH:$PWD/custom_components"

    # Remove Nix's externally-managed marker so uv can install into the venv freely
    find ".devenv/state/venv" -name "EXTERNALLY-MANAGED" -delete 2>/dev/null || true

    export UV_PYTHON="$VIRTUAL_ENV/bin/python"
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
      uv sync --group test_api --python "$VIRTUAL_ENV/bin/python"
      find ".devenv/state/venv" -name "EXTERNALLY-MANAGED" -delete 2>/dev/null || true
    '';
    after = ["devenv:enterShell"];
  };

  # https://devenv.sh/tests/
  enterTest = ''
    echo '🧪 Running tests'
    pytest tests/ --cov-report= --cov=custom_components.tech
    pytest tests_ha/ --cov-report=term-missing --cov-report=json --cov=custom_components.tech --cov-append --cov-fail-under=95
    python script/check_module_coverage.py
  '';
}
