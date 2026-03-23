#!/usr/bin/env python3
"""
Generate Polymarket CLOB API credentials from your private key.
Uses py-clob-client to derive API key, secret, and passphrase.

Usage:
    python setup_keys.py
"""

import sys
import os


def main():
    print("═══════════════════════════════════════════════════════")
    print("  Polymarket CLOB API Key Generator")
    print("  Your key never leaves this machine.")
    print("═══════════════════════════════════════════════════════\n")

    private_key = input("Paste your Polymarket private key (0x...): ").strip()
    if not private_key.startswith("0x") or len(private_key) < 64:
        print("Invalid private key format.", file=sys.stderr)
        sys.exit(1)

    try:
        from py_clob_client.client import ClobClient

        client = ClobClient(
            host="https://clob.polymarket.com",
            key=private_key,
            chain_id=137,
            signature_type=1,
        )

        creds = client.create_or_derive_api_creds()

        print("\n═══════════════════════════════════════════════════════")
        print("  ✅ CLOB API Credentials Generated!")
        print("═══════════════════════════════════════════════════════")
        print(f"  API Key:      {creds.api_key}")
        print(f"  Secret:       {creds.api_secret}")
        print(f"  Passphrase:   {creds.api_passphrase}")
        print("═══════════════════════════════════════════════════════")
        print("\nAdd these to your .env file as:")
        print("  POLYMARKET_CLOB_API_KEY        → API Key")
        print("  POLYMARKET_CLOB_API_SECRET     → Secret")
        print("  POLYMARKET_CLOB_API_PASSPHRASE → Passphrase")
        print("═══════════════════════════════════════════════════════")

    except Exception as e:
        print(f"\nFailed to derive credentials: {e}", file=sys.stderr)
        print("\nAlternative: Generate keys manually at:")
        print("  https://polymarket.com/settings?tab=builder")
        print("  Click '+ Create New' under Builder Keys.")
        sys.exit(1)


if __name__ == "__main__":
    main()
