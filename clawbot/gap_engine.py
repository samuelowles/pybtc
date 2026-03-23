import logging
import time
from typing import Optional

from .config import Config
from .market_discovery import Market, MarketDiscovery
from .risk import RiskManager

log = logging.getLogger("clawbot.gap")


def estimate_fair_price(winning_price: float, losing_price: float, time_to_close_ms: float) -> float:
    price_diff = abs(winning_price - losing_price)
    pct_diff = price_diff / winning_price if winning_price > 0 else 0
    time_decay = max(0.0, 1.0 - (time_to_close_ms / 60_000))
    return min(0.99, 0.5 + (pct_diff * 500 * time_decay))


class GapEngine:
    def __init__(self, config: Config, discovery: MarketDiscovery, risk: RiskManager):
        self.config = config
        self.discovery = discovery
        self.risk = risk
        self.on_signal: Optional[callable] = None

    def evaluate(self, spot_price: float):
        if spot_price == 0 or not self.discovery.markets:
            return

        now_ms = time.time() * 1000

        for cid, market in self.discovery.markets.items():
            can_trade, reason = self.risk.can_trade(cid)
            if not can_trade:
                continue

            time_to_close = market.end_time - now_ms
            if time_to_close <= 0 or time_to_close > 60_000:
                continue

            if spot_price > market.strike_price:
                fair_yes = estimate_fair_price(spot_price, market.strike_price, time_to_close)
                gap = fair_yes - market.yes_price

                if gap > self.config.GAP_THRESHOLD_PERCENT and self.on_signal:
                    self.on_signal(
                        market=market,
                        side="YES",
                        token_id=market.yes_token_id,
                        current_price=market.yes_price,
                        gap=gap,
                        spot_price=spot_price,
                    )

            elif spot_price < market.strike_price:
                fair_no = estimate_fair_price(market.strike_price, spot_price, time_to_close)
                gap = fair_no - market.no_price

                if gap > self.config.GAP_THRESHOLD_PERCENT and self.on_signal:
                    self.on_signal(
                        market=market,
                        side="NO",
                        token_id=market.no_token_id,
                        current_price=market.no_price,
                        gap=gap,
                        spot_price=spot_price,
                    )
