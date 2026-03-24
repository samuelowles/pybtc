import logging
import time
from datetime import datetime, timezone

from .config import Config
from .market_discovery import Market
from .risk import RiskManager
from .logger import log_trade

log = logging.getLogger("clawbot.executor")


class Executor:
    def __init__(self, config: Config, risk: RiskManager):
        self.config = config
        self.risk = risk
        self._clob_client = None

    def _get_client(self):
        if self._clob_client is not None:
            return self._clob_client

        if self.config.DRY_RUN:
            return None

        from py_clob_client.client import ClobClient
        from py_clob_client.clob_types import ApiCreds

        creds = ApiCreds(
            api_key=self.config.CLOB_API_KEY,
            api_secret=self.config.CLOB_API_SECRET,
            api_passphrase=self.config.CLOB_API_PASSPHRASE,
        )
        client = ClobClient(
            host=self.config.CLOB_API_URL,
            key=self.config.PROXY_WALLET_KEY,
            chain_id=self.config.CHAIN_ID,
            creds=creds,
            signature_type=1,
            funder=self.config.FUNDER_ADDRESS,
        )
        self._clob_client = client
        return client

    def execute(
        self,
        market: Market,
        side: str,
        token_id: str,
        current_price: float,
        gap: float,
        spot_price: float,
    ):
        size_usdc = min(
            self.config.MAX_POSITION_USDC,
            self.config.MAX_POSITION_USDC * (gap / 0.5),
        )

        trade_info = {
            "side": side,
            "condition_id": market.condition_id,
            "question": market.question,
            "spot": spot_price,
            "slug": market.slug,
            "pm_price": current_price,
            "gap": round(gap, 4),
            "size_usdc": round(size_usdc, 2),
            "time_to_close": f"{market.end_time - time.time():.1f}s",
            "dry_run": self.config.DRY_RUN,
        }

        if self.config.DRY_RUN:
            estimated_profit = size_usdc * gap * 0.8
            self.risk.record_trade(market.condition_id, estimated_profit, won=True)

            log_trade(
                "dry_run_trade",
                **trade_info,
                estimated_profit=round(estimated_profit, 2),
                **self.risk.stats,
            )
            return

        try:
            from py_clob_client.order_builder.constants import BUY
            from py_clob_client.clob_types import OrderArgs, OrderType

            client = self._get_client()
            order_args = OrderArgs(
                price=current_price,
                size=size_usdc / current_price,
                side=BUY,
                token_id=token_id,
            )
            signed_order = client.create_order(order_args)
            result = client.post_order(signed_order, OrderType.FOK)

            log_trade("live_order_submitted", **trade_info, result=str(result))

            order_id = result.get("orderID") if isinstance(result, dict) else None
            if order_id:
                estimated_profit = size_usdc * gap * 0.8
                self.risk.record_trade(market.condition_id, estimated_profit, won=True)
            else:
                self.risk.record_trade(market.condition_id, 0, won=False)

        except Exception as e:
            log.error(f"Trade failed: {e}")
            log_trade("trade_error", **trade_info, error=str(e))
            self.risk.record_trade(market.condition_id, 0, won=False)
