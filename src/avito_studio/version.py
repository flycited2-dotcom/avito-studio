"""Release and paired-Bridge build metadata."""
from __future__ import annotations

import re
import sys
from pathlib import Path

__version__ = "0.3.0"
_SHA = re.compile(r"[0-9a-f]{40}\Z")


def bridge_revision() -> str:
    """Return the exact paired Bridge revision, or a safe development label."""
    bundle_root = getattr(sys, "_MEIPASS", "")
    candidates = []
    if bundle_root:
        candidates.append(Path(bundle_root) / "build-metadata" / "bridge.lock")
    candidates.append(Path(__file__).resolve().parents[2] / "bridge.lock")
    for path in candidates:
        try:
            revision = path.read_text(encoding="ascii").strip()
        except (OSError, UnicodeError):
            continue
        if _SHA.fullmatch(revision):
            return revision
    return "development"
