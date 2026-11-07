"""Собирает portable-zip и SHA-256 для готовой папки dist/Chitalka."""

from __future__ import annotations

import hashlib
import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist" / "Chitalka"
VERSION = "1.0.0"


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def main() -> int:
    if not (DIST / "Chitalka.exe").exists():
        print("Сначала соберите exe: python tools/build_exe.py")
        return 1
    for junk in ("library.db", "library.db-wal", "library.db-shm", "settings.json",
                 "selftest.log", "crash.log", "chitalka.log"):
        for path in DIST.rglob(junk):
            path.unlink(missing_ok=True)
    for raw in (DIST / "data" / "dictionaries").glob("*.sqlite"):
        raw.unlink(missing_ok=True)

    target = ROOT / "dist" / f"Chitalka-{VERSION}-portable.zip"
    if target.exists():
        target.unlink()
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(DIST.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(DIST.parent))
    checksum = target.with_suffix(".zip.sha256")
    checksum.write_text(f"{digest(target)}  {target.name}\n", encoding="utf-8")
    print(f"Portable: {target}")
    print(f"SHA-256:  {checksum}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
