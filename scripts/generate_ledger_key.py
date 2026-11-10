"""Generate an Ed25519 signing key for the Impact Ledger.

By default this prints a **single line of base64** for the
``LEDGER_SIGNING_KEY_B64`` environment variable. That form is deliberate:
multi-line PEM blocks and hosting-dashboard secret fields do not mix. Those
fields routinely flatten newlines or store them as literal backslash-n, and
the result is an opaque "Could not deserialize key data" crash at startup.
One line cannot be mangled.

    python scripts/generate_ledger_key.py              # single line, for env vars
    python scripts/generate_ledger_key.py --pem        # PKCS#8 PEM, for a file
    python scripts/generate_ledger_key.py --pem > var/ledger_signing_key.pem

Treat the output as a credential. Anyone holding it can forge ledger entries
that verify against the published public key, which would defeat the point of
the ledger. Put it in your platform's secret store, never in a file in the
repository, and never paste it anywhere it will be logged.
"""

from __future__ import annotations

import argparse
import base64
import sys

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate an Ed25519 signing key for the Impact Ledger."
    )
    parser.add_argument(
        "--pem",
        action="store_true",
        help="emit a PKCS#8 PEM block instead of single-line base64",
    )
    parser.add_argument(
        "--show-public",
        action="store_true",
        help="also print the public key, which is safe to share",
    )
    args = parser.parse_args()

    key = Ed25519PrivateKey.generate()

    if args.pem:
        sys.stdout.write(
            key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            ).decode()
        )
    else:
        # Raw 32-byte private key, base64, no newlines.
        sys.stdout.write(base64.b64encode(key.private_bytes_raw()).decode() + "\n")

    if args.show_public:
        public = base64.b64encode(
            key.public_key().public_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PublicFormat.Raw,
            )
        ).decode()
        sys.stderr.write(f"public key (safe to publish): {public}\n")


if __name__ == "__main__":
    main()
