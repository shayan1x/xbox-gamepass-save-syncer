"""Run gss straight from a downloaded copy, without installing it: python gss.py <command>"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from gss.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
