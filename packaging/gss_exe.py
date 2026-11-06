"""Entry point of gss.exe (see gss.spec).

Not gss.py: a script named gss.py would be bundled as a module called "gss" and hide the gss package.
"""

import sys

from gss.cli import main

if __name__ == "__main__":
    sys.exit(main())
