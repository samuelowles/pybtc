import logging
import time
from typing import Optional

from .config import Config
from .market_discovery import Market, MarketDiscovery
from .risk import RiskManager

log = logging.getLogger("clawbot.gap")

# === STRATEGY 1: Window Delta (T-10s directional) ===
WINDOW_DELTA_MIN_MOVE = 0.0001  # 0.01% minimum BTC move
EXECUTE_AT_SECS = 10  # fire at exactly T-10 seconds
EXECUTE_WINDOW = 3  # execute between T-13 and T-10
MIN_PM_PRICE = 0.10
MAX_PM_PRICE = 0.65
GAP_THRESHOLD = 0.05

# === STRATEGY 2: Spread Lock (risk-free arbitrage) ===
SPREAD_LOCK_MAX_COST = 0.98  # buy both if YES + NO < $0.98 (2% profit)
SPREAD_LOCK_WINDOW = 30  # scan during last 30 seconds


class GapEngine:
    def __init__(self, config: Config, discovery: MarketDiscovery, risk: RiskManager):
        self.config = config
        self.discovery = discovery
        self.risk = risk
        self.on_signal: Optional[callable] = None
        self.on_spread_signal: Optional[callable] = None
        self._start_prices: dict[str, float] = {}
        self._last_log_time: dict[str, float] = {}
        self._last_spread_log: dict[str, float] = {}

    def evaluate(self, spot_price: float):
        if spot_price == 0 or not self.discovery.markets:
            return

        now = time.time()

        for cid, market in self.discovery.markets.items():
            if cid not in self._start_prices:
                self._start_prices[cid] = spot_price
                log.info(
                    f"REF {market.slug}: ${spot_price:.2f} "
                    f"(closes in {market.end_time - now:.0f}s)"
                )

            time_to_close = market.end_time - now
            if time_to_close <= 0:
                continue

            # ──────────────────────────────────────────────
            #  STRATEGY 2: Spread Lock (any time in last 30s)
            # ──────────────────────────────────────────────
            if time_to_close <= SPREAD_LOCK_WINDOW:
                combined = market.yes_price + market.no_price
                spread_profit = 1.0 - combined

                should_log_spread = (now - self._last_spread_log.get(cid, 0)) >= 5
                if should_log_spread:
                    self._last_spread_log[cid] = now
                    log.info(
                        f"SPREAD {market.slug} | ttc={time_to_close:.0f}s | "
                        f"yes={market.yes_price:.3f} no={market.no_price:.3f} "
                        f"sum={combined:.3f} profit={spread_profit:+.3f}"
                    )

                if combined < SPREAD_LOCK_MAX_COST and spread_profit > 0.01:
                    can_trade, _ = self.risk.can_trade(f"spread_{cid}")
                    if can_trade and self.on_spread_signal:
                        log.info(
                            f"🔒 SPREAD LOCK {market.slug} | "
                            f"yes={market.yes_price:.3f} + no={market.no_price:.3f} "
                            f"= {combined:.3f} | PROFIT={spread_profit:.3f}"
                        )
                        self.on_spread_signal(
                            market=market,
                            yes_price=market.yes_price,
                            no_price=market.no_price,
                            spread_profit=spread_profit,
                        )

            # ──────────────────────────────────────────────
            #  STRATEGY 1: Window Delta (T-13 to T-10)
            # ──────────────────────────────────────────────
            if time_to_close > (EXECUTE_AT_SECS + EXECUTE_WINDOW) or time_to_close < EXECUTE_AT_SECS:
                continue

            can_trade, reason = self.risk.can_trade(cid)
            if not can_trade:
                continue

            ref_price = self._start_prices[cid]
            window_delta = (spot_price - ref_price) / ref_price

            if window_delta > 0:
                side = "UP"
                pm_price = market.yes_price
                token_id = market.yes_token_id
            elif window_delta < 0:
                side = "DOWN"
                pm_price = market.no_price
                token_id = market.no_token_id
            else:
                continue

            abs_delta = abs(window_delta)
            expected_pm = min(0.95, 0.5 + (abs_delta * 200))
            gap = expected_pm - pm_price

            should_log = (now - self._last_log_time.get(cid, 0)) >= 2
            if should_log:
                self._last_log_time[cid] = now
                log.info(
                    f"DELTA {side} | {market.slug} | ttc={time_to_close:.0f}s | "
                    f"ref=${ref_price:.2f} spot=${spot_price:.2f} "
                    f"delta={window_delta*100:+.4f}% | "
                    f"pm={pm_price:.3f} exp={expected_pm:.3f} gap={gap:+.3f}"
                )

            if abs_delta < WINDOW_DELTA_MIN_MOVE:
                continue
            if pm_price < MIN_PM_PRICE or pm_price > MAX_PM_PRICE:
                continue

            if gap > GAP_THRESHOLD and self.on_signal:
                log.info(
                    f"🎯 SIGNAL {side} | {market.slug} | "
                    f"delta={window_delta*100:+.4f}% | "
                    f"pm={pm_price:.3f} exp={expected_pm:.3f} gap={gap:.3f} | "
                    f"ttc={time_to_close:.0f}s"
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
            self._last_spread_log.pop(cid, None)
