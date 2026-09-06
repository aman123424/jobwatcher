"""
Tiny shared helper so every feature-adapter module in this package can
`from ._backend_path import ensure_backend_on_path` once, instead of
each repeating its own sys.path.insert - see dbconn.py's own docstring
for why fitmodel imports backend/scoring directly rather than
re-deriving equivalent logic (schema/behavior drift risk).
"""

import sys
from pathlib import Path

_BACKEND_DIR = str(Path(__file__).parent.parent.parent / "backend")


def ensure_backend_on_path() -> None:
    if _BACKEND_DIR not in sys.path:
        sys.path.insert(0, _BACKEND_DIR)
