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
  ];

  # https://devenv.sh/languages/
  languages.python = {
    enable = true;
    version = "3.13";
    uv.enable = true;
    venv.enable = true;
    venv.requirements = builtins.readFile ./requirements.txt + "\n" + builtins.readFile ./requirements_test_api.txt;
  };

  # https://devenv.sh/scripts/
  scripts.setup = {
    exec = ''
      echo '🛠️ Running setup'
      python3 -m pip install --requirement requirements.txt --requirement requirements_test_api.txt
    '';
    description = "Install dependencies";
  };

  scripts.develop = {
    exec = ''
      # Create config dir if not present
      if [[ ! -d "$PWD/config" ]]; then
          mkdir -p "$PWD/config"
          ln -s "$PWD/custom_components/" "$PWD/config/custom_components"
          hass --config "$PWD/config" --script ensure_config
      fi

      if [ ! -L "$PWD/config/custom_components" ]; then
          ln -s "$PWD/custom_components/" "$PWD/config/custom_components"
      fi

      # Set the path to custom_components
      ## This let's us have the structure we want <root>/custom_components/integration_blueprint
      ## while at the same time have Home Assistant configuration inside <root>/config
      ## without resulting to symlinks.
      export PYTHONPATH="$PYTHONPATH:$PWD/custom_components"

      # Start Home Assistant
      hass --config "$PWD/config" --debug
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
    ${pkgs.gnused}/bin/sed -e 's| |••|g' -e 's|=| |' <<EOF | ${pkgs.util-linuxMinimal}/bin/column -t | ${pkgs.gnused}/bin/sed -e 's|^|🦾 |' -e 's|••| |g'
    ${lib.generators.toKeyValue {} (lib.mapAttrs (name: value: value.description) config.scripts)}
    EOF
    echo
  '';

  tasks."app:setup" = {
    exec = ''
      echo '🛠️ Running setup'
      python3 -m pip install --requirement requirements.txt --requirement requirements_test_api.txt
    '';
    after = ["devenv:enterShell"];
  };

  # https://devenv.sh/tests/
  enterTest = ''
    echo '🧪 Running tests'
    pytest tests/tests_api --cov-report=term-missing --cov=custom_components.tech.tech tests/
  '';
}
