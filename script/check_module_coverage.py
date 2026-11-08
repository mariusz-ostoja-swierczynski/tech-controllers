"""Fail when any module of the integration falls below the coverage floor.

The integration quality scale's test-coverage rule asks for 95% both in total and
per module, and `coverage`'s own ``fail_under`` only covers the total. This reads
the JSON report the test runs write and checks every file, so one module cannot
slip under the floor while a well-covered neighbour hides it in the average.

Run it after the two suites, from the repository root:

    pytest tests/ --cov-report= --cov=custom_components.tech
    pytest tests_ha/ --cov-report=term-missing --cov-report=json \
        --cov=custom_components.tech --cov-append
    python script/check_module_coverage.py
"""

from __future__ import annotations

import json
import pathlib
import sys

FLOOR = 95.0
REPORT = pathlib.Path("coverage.json")
PACKAGE = "custom_components/tech/"


def main() -> int:
    """Print each module's coverage and fail if one is under the floor."""
    if not REPORT.exists():
        print(f"{REPORT} is missing: run the tests with --cov-report=json first")
        return 1

    files = json.loads(REPORT.read_text(encoding="utf-8"))["files"]
    modules = {
        path: data["summary"]["percent_covered"]
        for path, data in sorted(files.items())
        if path.startswith(PACKAGE)
    }
    if not modules:
        print(f"{REPORT} has no {PACKAGE} modules in it")
        return 1

    for path, percent in modules.items():
        print(f"{percent:6.2f}%  {path}")

    short = [path for path, percent in modules.items() if percent < FLOOR]
    if short:
        print(f"\nUnder {FLOOR}%: {', '.join(short)}")
        return 1

    print(f"\nEvery module is at or above {FLOOR}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
