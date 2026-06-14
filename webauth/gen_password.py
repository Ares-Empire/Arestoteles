#!/usr/bin/env python3
"""Generate AUTH_PASSWORD_HASH (+ a fresh AUTH_SESSION_SECRET if missing) for the
web login gate. Prints .env lines; does NOT write them (secrets stay out of git).

Usage:  python webauth/gen_password.py 'the-password'
Scrypt params match webauth/server.py.
"""

import hashlib
import os
import secrets
import sys

N, R, P, DKLEN, MAXMEM = 16384, 8, 1, 32, 64 * 1024 * 1024


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, n=N, r=R, p=P, dklen=DKLEN, maxmem=MAXMEM)
    # ":" separator (not "$") so the value survives docker-compose env_file interpolation
    return f"scrypt:{salt.hex()}:{dk.hex()}"


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: python webauth/gen_password.py 'the-password'")
    print(f"AUTH_PASSWORD_HASH={hash_password(sys.argv[1])}")
    if not os.environ.get("AUTH_SESSION_SECRET"):
        print(f"AUTH_SESSION_SECRET={secrets.token_urlsafe(48)}")
