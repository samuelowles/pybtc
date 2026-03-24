import logging
import time
from typing import Optional

from .config import Config
from .market_discovery import Market, MarketDiscovery
from .risk import RiskManager

log = logging.getLogger("clawbot.gap")

MIN_BTC_MOVE_PCT = 0.0010
MIN_PM_PRICE = 0.05
MAX_PM_PRICE = 0.70
TRADE_WINDOW_SECS = 30


class GapEngine:
    def __init__(self, config: Config, discovery: MarketDiscovery, risk: RiskManager):
        self.config = config
        self.discovery = discovery
        self.risk = risk
        self.on_signal: Optional[callable] = None
        self._start_prices: dict[str, float] = {}
        self._last_log_time: dict[str, float] = {}

    def evaluate(self, spot_price: float):
        if spot_price == 0 or not self.discovery.markets:
            return

        now = time.time()

        for cid, market in self.discovery.markets.items():
            if cid not in self._start_prices:
                self._start_prices[cid] = spot_price
                log.info(
                    f"Ref price captured for {market.slug}: "
                    f"${spot_price:.2f} (closes in {market.end_time - now:.0f}s)"
                )

            time_to_close = market.end_time - now
            if time_to_close <= 0 or time_to_close > TRADE_WINDOW_SECS:
                continue

            can_trade, reason = self.risk.can_trade(cid)
            if not can_trade:
                continue

            ref_price = self._start_prices[cid]
            btc_move_pct = (spot_price - ref_price) / ref_price

            if btc_move_pct > 0:
                side = "UP"
                pm_price = market.yes_price
                token_id = market.yes_token_id
            elif btc_move_pct < 0:
                side = "DOWN"
                pm_price = market.no_price
                token_id = market.no_token_id
            else:
                continue

            abs_move = abs(btc_move_pct)
            time_factor = 1.0 - (time_to_close / TRADE_WINDOW_SECS)
            expected_pm = min(0.95, 0.5 + (abs_move * 200 * (0.5 + time_factor * 0.5)))
            gap = expected_pm - pm_price

            should_log = (now - self._last_log_time.get(cid, 0)) >= 5
            if should_log:
                self._last_log_time[cid] = now
                log.info(
                    f"TRACKING {side} | {market.slug} | ttc={time_to_close:.0f}s | "
                    f"ref=${ref_price:.2f} → spot=${spot_price:.2f} ({btc_move_pct*100:+.3f}%) | "
                    f"pm_{side.lower()}={pm_price:.2f} vs expected={expected_pm:.2f} | "
                    f"gap={gap:+.3f}"
                )

            if abs_move < MIN_BTC_MOVE_PCT:
                continue

            if pm_price < MIN_PM_PRICE or pm_price > MAX_PM_PRICE:
                continue

            if gap > self.config.GAP_THRESHOLD_PERCENT and self.on_signal:
                log.info(
                    f"🎯 SIGNAL {side} | {market.slug} | gap={gap:.3f} | "
                    f"pm={pm_price:.2f} expected={expected_pm:.2f} | "
                    f"btc_move={btc_move_pct*100:+.3f}%"
                )
                self.on_signal(
                    market=market,
                    side=side,
                    token_id=token_id,
                    current_price=pm_price,
                    gap=gap,
                    spot_price=spot_price,
                )

        expired = [cid for cid in self._start_prices if cid not in self.discovery.markets]
        for cid in expired:
            del self._start_prices[cid]
            self._last_log_time.pop(cid, None)
