"""Tests for gss. Run from the project folder with: python -m unittest

They build fake Packages folders in a temp directory and never touch real saves."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
