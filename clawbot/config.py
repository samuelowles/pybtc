import os
import sys
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    PROXY_WALLET_KEY: str = ""
    POLYGON_RPC_URL: str = "https://polygon-rpc.com"

    CLOB_API_KEY: str = ""
    CLOB_API_SECRET: str = ""
    CLOB_API_PASSPHRASE: str = ""

    GAMMA_API_URL: str = "https://gamma-api.polymarket.com"
    CLOB_API_URL: str = "https://clob.polymarket.com"
    CLOB_WS_URL: str = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
    BINANCE_WS_URL: str = "wss://stream.binance.com:9443/ws/btcusdt@ticker"
    CTF_EXCHANGE_ADDRESS: str = "0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E"
    CHAIN_ID: int = 137

    GAP_THRESHOLD_PERCENT: float = 0.15
    MARKET_DISCOVERY_INTERVAL: int = 30
    MAX_POSITION_USDC: float = 50.0
    MAX_DAILY_LOSS_USDC: float = 100.0
    COOLDOWN_SECONDS: float = 2.0
    DRY_RUN: bool = True

    @classmethod
    def from_env(cls) -> "Config":
        cfg = cls(
            PROXY_WALLET_KEY=os.getenv("PROXY_WALLET_KEY", ""),
            POLYGON_RPC_URL=os.getenv("POLYGON_RPC_URL", cls.POLYGON_RPC_URL),
            CLOB_API_KEY=os.getenv("POLYMARKET_CLOB_API_KEY", ""),
            CLOB_API_SECRET=os.getenv("POLYMARKET_CLOB_API_SECRET", ""),
            CLOB_API_PASSPHRASE=os.getenv("POLYMARKET_CLOB_API_PASSPHRASE", ""),
            GAP_THRESHOLD_PERCENT=float(os.getenv("GAP_THRESHOLD_PERCENT", "0.15")),
            MARKET_DISCOVERY_INTERVAL=int(os.getenv("MARKET_DISCOVERY_INTERVAL", "30")),
            MAX_POSITION_USDC=float(os.getenv("MAX_POSITION_USDC", "50")),
            MAX_DAILY_LOSS_USDC=float(os.getenv("MAX_DAILY_LOSS_USDC", "100")),
            COOLDOWN_SECONDS=float(os.getenv("COOLDOWN_SECONDS", "2")),
            DRY_RUN=os.getenv("DRY_RUN", "true").lower() != "false",
        )
        return cfg

    def validate(self):
        secrets = {
            "PROXY_WALLET_KEY": self.PROXY_WALLET_KEY,
            "POLYMARKET_CLOB_API_KEY": self.CLOB_API_KEY,
            "POLYMARKET_CLOB_API_SECRET": self.CLOB_API_SECRET,
            "POLYMARKET_CLOB_API_PASSPHRASE": self.CLOB_API_PASSPHRASE,
        }
        missing = [k for k, v in secrets.items() if not v]

        if missing and not self.DRY_RUN:
            print(f"[FATAL] Missing env vars for live trading: {', '.join(missing)}", file=sys.stderr)
            sys.exit(1)
        if missing:
            print(f"[WARN] Missing env vars ({', '.join(missing)}). Running in DRY_RUN mode.")
