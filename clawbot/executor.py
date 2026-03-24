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
            import math
            from py_clob_client.clob_types import OrderType
            from py_order_utils.builders import OrderBuilder as UtilsOrderBuilder
            from py_order_utils.signer import Signer as UtilsSigner
            from py_order_utils.model import OrderData, BUY as UtilsBuy

            client = self._get_client()

            price = round(current_price, 2)
            price_cents = int(round(price * 100))
            raw_size = size_usdc / price
            size = math.floor(raw_size * 100) / 100

            taker_amount = round(size * 1_000_000)
            taker_amount = (taker_amount // 100) * 100
            maker_amount = taker_amount * price_cents // 100

            neg_risk = client.get_neg_risk(token_id)
            fee_rate = client.get_fee_rate_bps(token_id)
            from py_clob_client.config import get_contract_config
            cfg = get_contract_config(client.signer.get_chain_id(), neg_risk)

            data = OrderData(
                maker=self.config.FUNDER_ADDRESS,
                taker="0x0000000000000000000000000000000000000000",
                tokenId=token_id,
                makerAmount=str(maker_amount),
                takerAmount=str(taker_amount),
                side=UtilsBuy,
                feeRateBps=str(fee_rate),
                nonce="0",
                signer=client.signer.address(),
                expiration="0",
                signatureType=1,
            )

            order_builder = UtilsOrderBuilder(
                cfg.exchange,
                client.signer.get_chain_id(),
                UtilsSigner(key=client.signer.private_key),
            )
            signed_order = order_builder.build_signed_order(data)
            result = client.post_order(signed_order, OrderType.GTC)

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
