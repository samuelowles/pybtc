#!/usr/bin/env python3
"""Diagnose wallet, balance, and signature issues."""
import os
import json
import httpx

from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds

KEY = os.getenv("PROXY_WALLET_KEY", "")
FUNDER = os.getenv("FUNDER_ADDRESS", "")

# USDC on Polygon
USDC_ADDRESS = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
USDC_ABI_BALANCEOF = "0x70a08231"

print("=" * 60)
print("  CLAWBOT WALLET DIAGNOSTICS")
print("=" * 60)

for sig_type in [0, 1, 2]:
    try:
        kwargs = dict(
            host="https://clob.polymarket.com",
            key=KEY,
            chain_id=137,
            signature_type=sig_type,
        )
        if sig_type == 2 and FUNDER:
            kwargs["funder"] = FUNDER

        c = ClobClient(**kwargs)
        creds = c.create_or_derive_api_creds()
        c.set_api_creds(creds)

        addr = c.get_address()
        print(f"\nsig_type={sig_type}: trading_address={addr}")
        print(f"  api_key={creds.api_key}")

        # Check USDC balance via RPC
        rpc = os.getenv("POLYGON_RPC_URL", "https://polygon-rpc.com")
        padded_addr = "0x" + addr[2:].lower().zfill(64)
        call_data = USDC_ABI_BALANCEOF + padded_addr[2:]

        resp = httpx.post(rpc, json={
            "jsonrpc": "2.0",
            "method": "eth_call",
            "params": [{"to": USDC_ADDRESS, "data": call_data}, "latest"],
            "id": 1,
        }, timeout=10)
        result = resp.json().get("result", "0x0")
        balance = int(result, 16) / 1e6
        print(f"  USDC balance: ${balance:.2f}")

    except Exception as e:
        print(f"\nsig_type={sig_type}: ERROR: {e}")

# Also check EOA balance directly
print(f"\n--- EOA Check ---")
from eth_account import Account
acct = Account.from_key(KEY)
print(f"EOA address (from private key): {acct.address}")
print(f"FUNDER env: {FUNDER}")

padded_eoa = "0x" + acct.address[2:].lower().zfill(64)
call_data = USDC_ABI_BALANCEOF + padded_eoa[2:]
rpc = os.getenv("POLYGON_RPC_URL", "https://polygon-rpc.com")
resp = httpx.post(rpc, json={
    "jsonrpc": "2.0",
    "method": "eth_call",
    "params": [{"to": USDC_ADDRESS, "data": call_data}, "latest"],
    "id": 1,
}, timeout=10)
result = resp.json().get("result", "0x0")
balance = int(result, 16) / 1e6
print(f"EOA USDC balance: ${balance:.2f}")

print("\n" + "=" * 60)
