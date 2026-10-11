#!/usr/bin/env python3
"""Build storage-steward.skill (a zip of the skill folder) from the source tree.

The archive is reproducible: entries are sorted and carry a fixed timestamp, so the same tree always
produces the same bytes. Everything under scripts/ and references/ ships, so a new module can't be
left out of a release by accident. evals/ and bytecode stay out.

Usage: python3 tools/package_skill.py [--out dist/storage-steward.skill]
"""
from __future__ import annotations

import argparse
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILL = ROOT / "storage-steward"
SHIPPED = ("SKILL.md", "scripts", "references")
FIXED_TIME = (1980, 1, 1, 0, 0, 0)  # earliest time a zip entry can hold


def shipped_files() -> list[Path]:
    files = []
    for name in SHIPPED:
        path = SKILL / name
        if path.is_file():
            files.append(path)
            continue
        files.extend(p for p in path.rglob("*")
                     if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc")
    return sorted(files)


def build(out: Path) -> int:
    out.parent.mkdir(parents=True, exist_ok=True)
    files = shipped_files()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in files:
            info = zipfile.ZipInfo(f"storage-steward/{path.relative_to(SKILL).as_posix()}", FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (0o755 if path.suffix == ".py" else 0o644) << 16
            zf.writestr(info, path.read_bytes())
    return len(files)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--out", type=Path, default=ROOT / "dist" / "storage-steward.skill")
    a = p.parse_args(argv)
    n = build(a.out)
    print(f"{a.out} ({n} files, {a.out.stat().st_size / 1024:.1f} KiB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
