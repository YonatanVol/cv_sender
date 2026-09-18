"""python -m cvsender.doctor — one screen telling you what is broken and how to fix it."""
import sys

from .db.migrations import migrate
from .health import main

if __name__ == "__main__":
    migrate()
    sys.exit(main())
