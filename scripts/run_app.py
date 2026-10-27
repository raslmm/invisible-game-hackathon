"""Start the dependency-free local demo server."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from invisible_game.webapp import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
