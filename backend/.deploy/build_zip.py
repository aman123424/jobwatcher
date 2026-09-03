"""
build_zip.py
============

Zips backend/.deploy/package/ into backend/.deploy/jobwatcher-lambda.zip
for Lambda upload. Called by ../../deploy.ps1, not meant to be run
standalone under normal use.

Two things this deliberately does that a plain `Compress-Archive` (the
built-in PowerShell zip cmdlet) or a naive zip wouldn't:

1. Skips __pycache__/ dirs and .pyc files - Lambda never needs them,
   and installed dependencies accumulate a lot of these across their
   own submodules, needlessly inflating the zip (measured: ~19MB with
   them included vs ~12.5MB without, on this project's dependency set).

2. Does NOT skip .dist-info folders, even though they look like
   redundant install metadata - a real bug (documented in
   PROJECT_LOG.md) traced a Lambda ImportModuleError specifically to
   stripping these: `pydantic[email]`'s `email-validator` dependency
   checks its own installed metadata via `importlib.metadata` at
   import time, which needs .dist-info physically present at runtime.
"""

import sys
import zipfile
from pathlib import Path

package_dir = Path(sys.argv[1])
zip_path = Path(sys.argv[2])

if zip_path.exists():
    zip_path.unlink()

with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
    for path in package_dir.rglob("*"):
        if path.is_dir():
            continue
        if "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        zf.write(path, path.relative_to(package_dir))

size_mb = zip_path.stat().st_size / (1024 * 1024)
print(f"Zip created: {zip_path} ({size_mb:.2f} MB)")
