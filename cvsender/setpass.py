"""Set the passphrase that guards remote access.

    python -m cvsender.setpass

Required before the app may bind to anything other than localhost, because the
confirm endpoints fire real, irreversible applications. The passphrase is never
echoed, never stored in plaintext, and never logged.
"""
from __future__ import annotations

import getpass
import sys

from . import auth
from .db.migrations import migrate


def main(argv=None) -> int:
    migrate()
    if auth.is_configured():
        print("A passphrase is already set. Enter the current one to change it.")
        if not auth.verify_passphrase(getpass.getpass("Current passphrase: ")):
            print("Wrong passphrase.")
            return 1
    first = getpass.getpass(f"New passphrase (min {auth.MIN_LEN} chars): ")
    if first != getpass.getpass("Repeat: "):
        print("They don't match.")
        return 1
    try:
        auth.set_passphrase(first)
    except ValueError as e:
        print(f"{e}")
        return 1
    print("Passphrase set. Remote access is now allowed (./run2.sh --remote).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
