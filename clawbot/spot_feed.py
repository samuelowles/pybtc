import json
import asyncio
import logging
from typing import Callable, Optional

import websockets

from .config import Config

log = logging.getLogger("clawbot.spot")


class SpotFeed:
    def __init__(self, config: Config, on_price_update: Callable[[float, float], None]):
        self.config = config
        self.on_price_update = on_price_update
        self.current_price: float = 0.0
        self.prev_price: float = 0.0

    async def run(self):
        log.info("Connecting to Binance WS...")
        while True:
            try:
                async with websockets.connect(self.config.BINANCE_WS_URL) as ws:
                    log.info("Binance WS connected")
                    async for raw in ws:
                        try:
                            data = json.loads(raw)
                            if "c" in data:
                                self.prev_price = self.current_price
                                self.current_price = float(data["c"])
                                self.on_price_update(self.current_price, self.prev_price)
                        except (json.JSONDecodeError, ValueError):
                            pass
            except (websockets.ConnectionClosed, OSError) as e:
                log.warning(f"Binance WS closed ({e}). Reconnecting in 500ms...")
                await asyncio.sleep(0.5)
            except Exception as e:
                log.error(f"Binance WS error: {e}. Reconnecting in 2s...")
                await asyncio.sleep(2)
