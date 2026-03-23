import logging
import time
from typing import Optional

from .config import Config
from .market_discovery import Market, MarketDiscovery
from .risk import RiskManager

log = logging.getLogger("clawbot.gap")


def estimate_fair_price(spot_price: float, ref_price: float, time_to_close_s: float) -> float:
    """Estimate fair Up/Down probability given spot vs reference price and time remaining."""
    if ref_price <= 0 or spot_price <= 0:
        return 0.5
    price_diff = abs(spot_price - ref_price)
    pct_diff = price_diff / ref_price
    time_decay = max(0.0, 1.0 - (time_to_close_s / 60.0))
    return min(0.99, 0.5 + (pct_diff * 500 * time_decay))


class GapEngine:
    def __init__(self, config: Config, discovery: MarketDiscovery, risk: RiskManager):
        self.config = config
        self.discovery = discovery
        self.risk = risk
        self.on_signal: Optional[callable] = None
        self._start_prices: dict[str, float] = {}

    def capture_start_price(self, condition_id: str, spot_price: float):
        if condition_id not in self._start_prices:
            self._start_prices[condition_id] = spot_price
            log.info(f"Captured start price for {condition_id[:16]}...: ${spot_price:.2f}")

    def evaluate(self, spot_price: float):
        if spot_price == 0 or not self.discovery.markets:
            return

        now = time.time()

        for cid, market in self.discovery.markets.items():
            can_trade, reason = self.risk.can_trade(cid)
            if not can_trade:
                continue

            time_to_close = market.end_time - now
            if time_to_close <= 0 or time_to_close > 60:
                continue

            # Capture reference price if we haven't yet
            if cid not in self._start_prices:
                self.capture_start_price(cid, spot_price)

            ref_price = self._start_prices.get(cid, spot_price)

            if spot_price > ref_price:
                fair_up = estimate_fair_price(spot_price, ref_price, time_to_close)
                gap = fair_up - market.yes_price

                if gap > self.config.GAP_THRESHOLD_PERCENT and self.on_signal:
                    self.on_signal(
                        market=market,
                        side="UP",
                        token_id=market.yes_token_id,
                        current_price=market.yes_price,
                        gap=gap,
                        spot_price=spot_price,
                    )

            elif spot_price < ref_price:
                fair_down = estimate_fair_price(spot_price, ref_price, time_to_close)
                gap = fair_down - market.no_price

                if gap > self.config.GAP_THRESHOLD_PERCENT and self.on_signal:
                    self.on_signal(
                        market=market,
                        side="DOWN",
                        token_id=market.no_token_id,
                        current_price=market.no_price,
                        gap=gap,
                        spot_price=spot_price,
                    )

        # Purge stale start prices
        expired = [cid for cid in self._start_prices if cid not in self.discovery.markets]
        for cid in expired:
            del self._start_prices[cid]
