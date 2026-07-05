"""Synchronize static version strings from version.py.

Runtime Python modules import VERSION directly. Static assets such as README,
GitHub Pages HTML, and embedded help text cannot import Python at runtime, so
this script rewrites their displayed release strings from the same source.

Usage:
    python scripts/sync_version.py
    python scripts/sync_version.py --check
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VERSION_FILE = ROOT / "version.py"
TARGET_FILES = [
    ROOT / "README.md",
    ROOT / "COMPLETE_USER_GUIDE.md",
    ROOT / "docs" / "index.html",
    ROOT / "slr_gui.py",
]

VERSION_RE = re.compile(
    r"(?<![A-Za-z0-9_.-])v?\d+\.\d+\.\d+(?:-[A-Za-z0-9][A-Za-z0-9.-]*)?(?![A-Za-z0-9_.-])"
)
SHIELDS_VERSION_RE = re.compile(r"\d+\.\d+\.\d+--[A-Za-z0-9.]+")


def read_version() -> str:
    tree = ast.parse(VERSION_FILE.read_text(encoding="utf-8"), filename=str(VERSION_FILE))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "VERSION":
                    value = ast.literal_eval(node.value)
                    if isinstance(value, str) and value:
                        return value
    raise RuntimeError(f"Could not find VERSION in {VERSION_FILE}")


def sync_text(text: str, version: str) -> str:
    tag = f"v{version}"
    shields_version = version.replace("-", "--")

    text = SHIELDS_VERSION_RE.sub(shields_version, text)

    def replace(match: re.Match[str]) -> str:
        value = match.group(0)
        prefix = text[max(0, match.start() - 16):match.start()].lower()
        if prefix.endswith("python "):
            return value
        return tag if value.startswith("v") else version

    return VERSION_RE.sub(replace, text)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sync static release versions from version.py")
    parser.add_argument("--check", action="store_true", help="Fail if any target is out of sync")
    args = parser.parse_args(argv)

    version = read_version()
    changed = []

    for path in TARGET_FILES:
        original = path.read_text(encoding="utf-8")
        updated = sync_text(original, version)
        if updated != original:
            changed.append(path.relative_to(ROOT).as_posix())
            if not args.check:
                path.write_text(updated, encoding="utf-8")

    if args.check and changed:
        print("Version strings are out of sync:", file=sys.stderr)
        for path in changed:
            print(f"  {path}", file=sys.stderr)
        return 1

    if changed:
        print(f"Updated version strings to v{version}:")
        for path in changed:
            print(f"  {path}")
    else:
        print(f"Version strings already in sync at v{version}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
