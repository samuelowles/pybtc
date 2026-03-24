import signal
import asyncio
import logging
import time

import httpx

from .config import Config
from .logger import setup_logging, log_trade
from .risk import RiskManager
from .market_discovery import MarketDiscovery
from .spot_feed import SpotFeed
from .clob_feed import ClobFeed
from .gap_engine import GapEngine
from .executor import Executor

log = logging.getLogger("clawbot.daemon")

BANNER = """
═══════════════════════════════════════════════════════
  Clawbot — Polymarket BTC Arbitrage Daemon (Python)
═══════════════════════════════════════════════════════"""


class Daemon:
    def __init__(self):
        self.config = Config.from_env()
        self.config.validate()

        self.risk = RiskManager(
            max_daily_loss=self.config.MAX_DAILY_LOSS_USDC,
            cooldown_seconds=self.config.COOLDOWN_SECONDS,
        )
        self.discovery = MarketDiscovery(self.config)
        self.executor = Executor(self.config, self.risk)
        self.gap_engine = GapEngine(self.config, self.discovery, self.risk)
        self.gap_engine.on_signal = self._on_trade_signal
        self.gap_engine.on_spread_signal = self._on_spread_signal

        self.spot_feed = SpotFeed(self.config, on_price_update=self._on_spot_update)
        self.clob_feed = ClobFeed(self.config, self.discovery)

    def _on_spot_update(self, price: float, prev_price: float):
        self.gap_engine.evaluate(price)

    def _on_trade_signal(self, **kwargs):
        self.executor.execute(**kwargs)

    def _on_spread_signal(self, **kwargs):
        self.executor.execute_spread(**kwargs)

    async def _preflight_check(self):
        """Verify connectivity to Binance and Gamma API before entering main loop."""
        print("  Preflight checks:")

        # Check Gamma API
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(f"{self.config.GAMMA_API_URL}/events?slug=btc-updown-5m-0")
                resp.raise_for_status()
                print("    ✅ Gamma API reachable")
        except Exception as e:
            print(f"    ❌ Gamma API unreachable: {e}")
            return False

        # Check Binance WS connectivity via REST
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get("https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT")
                resp.raise_for_status()
                btc_price = resp.json().get("price", "?")
                print(f"    ✅ Binance reachable (BTC=${btc_price})")
        except Exception as e:
            print(f"    ❌ Binance unreachable: {e}")
            return False

        print()
        return True

    async def _stats_reporter(self):
        """Log session stats every 5 minutes."""
        start = time.time()
        while True:
            await asyncio.sleep(300)
            uptime = time.time() - start
            mins = int(uptime // 60)
            stats = self.risk.stats
            tracked = len(self.discovery.markets)
            log_trade(
                "session_stats",
                uptime_min=mins,
                tracked_markets=tracked,
                **stats,
            )

    async def run(self):
        print(BANNER)
        mode = "🔶 DRY RUN (simulation)" if self.config.DRY_RUN else "🟢 LIVE TRADING"
        print(f"  Mode:            {mode}")
        print(f"  Gap threshold:   {self.config.GAP_THRESHOLD_PERCENT * 100:.1f}%")
        print(f"  Max position:    ${self.config.MAX_POSITION_USDC}")
        print(f"  Max daily loss:  ${self.config.MAX_DAILY_LOSS_USDC}")
        print(f"  Cooldown:        {self.config.COOLDOWN_SECONDS}s")
        print("═══════════════════════════════════════════════════════\n")

        if not await self._preflight_check():
            print("[FATAL] Preflight checks failed. Exiting.")
            return

        loop = asyncio.get_event_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, self._shutdown)
            except NotImplementedError:
                pass

        await self.discovery.poll_once()

        tasks = [
            asyncio.create_task(self.discovery.run(), name="discovery"),
            asyncio.create_task(self.spot_feed.run(), name="spot_feed"),
            asyncio.create_task(self.clob_feed.run(), name="clob_feed"),
            asyncio.create_task(self._stats_reporter(), name="stats"),
        ]

        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            log.info("Daemon shutting down...")
        finally:
            await self.discovery.close()

    def _shutdown(self):
        log.info("Shutdown signal received")
        for task in asyncio.all_tasks():
            task.cancel()


def main():
    setup_logging()
    daemon = Daemon()
    asyncio.run(daemon.run())


if __name__ == "__main__":
    main()
