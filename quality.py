#!/usr/bin/env python3
"""Load the readable project-actionability implementation fragments.

The implementation is split only to keep GitHub API writes reviewable. The
fragments concatenate to the validated source without generated code or network
access. A sentinel module name prevents fragment-level ``__main__`` guards from
terminating before later precision layers are loaded.
"""
from pathlib import Path
import sys

_MODULE_NAME = __name__
_IS_MAIN = _MODULE_NAME == "__main__"
_RUNTIME_NAME = "quality_runtime"
_FRAGMENT_DIR = Path(__file__).resolve().parent / ".quality-src"
_SOURCE = "".join(
    path.read_text(encoding="utf-8")
    for path in sorted(_FRAGMENT_DIR.glob("part-*.pyfrag"))
)
if not _SOURCE:
    raise RuntimeError("project actionability source fragments are missing")

# dataclasses resolves annotations through sys.modules[cls.__module__].
# Register the synthetic name before executing the fragments so classes defined
# while __name__ is temporarily changed remain introspectable.
sys.modules[_RUNTIME_NAME] = sys.modules[_MODULE_NAME]
globals()["__name__"] = _RUNTIME_NAME
try:
    exec(compile(_SOURCE, str(Path(__file__).resolve()), "exec"), globals(), globals())
finally:
    globals()["__name__"] = _MODULE_NAME

if _IS_MAIN:
    raise SystemExit(main())
