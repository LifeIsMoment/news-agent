#!/usr/bin/env python3
"""Load the readable project-actionability implementation fragments.

The implementation is split only to keep GitHub API writes reviewable. The
fragments concatenate to the validated source without generated code or network
access.
"""
from pathlib import Path

_FRAGMENT_DIR = Path(__file__).resolve().parent / ".quality-src"
_SOURCE = "".join(
    path.read_text(encoding="utf-8")
    for path in sorted(_FRAGMENT_DIR.glob("part-*.pyfrag"))
)
if not _SOURCE:
    raise RuntimeError("project actionability source fragments are missing")
exec(compile(_SOURCE, str(Path(__file__).resolve()), "exec"), globals(), globals())
