"""Entry point of the packaged background service.

PyInstaller needs a plain script to start from, and the service itself
is a package with relative imports. This file is that script and does
nothing else.
"""

import multiprocessing
import sys

from service.main import main

if __name__ == "__main__":
    # Without this a packaged program that starts a further process of
    # itself would start the whole application again.
    multiprocessing.freeze_support()
    sys.exit(main())
