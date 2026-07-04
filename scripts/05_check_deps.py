#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]

REQUIRED_DEPS: list[dict[str, Any]] = [
    {
        "package": "PyYAML",
        "import_name": "yaml",
        "required_for": [
            "TOOL_MATRIX.yaml parsing",
            "rules/recipes.yaml parsing",
            "FAST_STATIC formal audit pipeline",
            "benchmark regression suite",
        ],
        "install_hint": "python3 -m pip install -r requirements.txt",
    }
]


def check_dep(dep: dict[str, Any]) -> dict[str, Any]:
    spec = importlib.util.find_spec(dep["import_name"])
    available = spec is not None
    return {
        "package": dep["package"],
        "import_name": dep["import_name"],
        "available": available,
        "origin": getattr(spec, "origin", None) if spec else None,
        "required_for": dep["required_for"],
        "install_hint": dep["install_hint"],
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Check Python dependencies for AI Audit Workbench.")
    parser.add_argument("--strict", action="store_true", help="Exit non-zero when required dependencies are missing.")
    parser.add_argument("--print-summary", action="store_true", help="Print dependency check summary.")
    args = parser.parse_args(argv)

    results = [check_dep(dep) for dep in REQUIRED_DEPS]
    missing = [item for item in results if not item["available"]]

    print("dependency-check summary")
    for item in results:
        status = "available" if item["available"] else "missing"
        print(f"  {item['package']}: {status}")
        if item["available"] and item.get("origin"):
            print(f"    origin: {item['origin']}")
        if not item["available"]:
            print("    required_for:")
            for use in item["required_for"]:
                print(f"      - {use}")
            print(f"    install: {item['install_hint']}")

    if missing:
        print("")
        print("Required Python dependencies are missing.")
        print("Run: python3 -m pip install -r requirements.txt")
        if args.strict:
            return 2
    else:
        print("All required Python dependencies are available.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
