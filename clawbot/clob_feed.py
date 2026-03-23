import json
import asyncio
import logging

import websockets

from .config import Config
from .market_discovery import MarketDiscovery

log = logging.getLogger("clawbot.clob_feed")


class ClobFeed:
    def __init__(self, config: Config, discovery: MarketDiscovery):
        self.config = config
        self.discovery = discovery

    def _get_asset_ids(self) -> list[str]:
        ids = []
        for m in self.discovery.markets.values():
            ids.append(m.yes_token_id)
            ids.append(m.no_token_id)
        return ids

    async def run(self):
        log.info("Connecting to CLOB WS...")
        while True:
            try:
                async with websockets.connect(self.config.CLOB_WS_URL) as ws:
                    asset_ids = self._get_asset_ids()
                    if asset_ids:
                        sub = json.dumps({
                            "type": "subscribe",
                            "channel": "market",
                            "assets_ids": asset_ids,
                        })
                        await ws.send(sub)
                        log.info(f"CLOB WS subscribed to {len(asset_ids)} assets")

                    resubscribe_task = asyncio.create_task(
                        self._resubscribe_loop(ws)
                    )

                    try:
                        async for raw in ws:
                            self._handle_message(raw)
                    finally:
                        resubscribe_task.cancel()

            except (websockets.ConnectionClosed, OSError) as e:
                log.warning(f"CLOB WS closed ({e}). Reconnecting in 500ms...")
                await asyncio.sleep(0.5)
            except Exception as e:
                log.error(f"CLOB WS error: {e}. Reconnecting in 2s...")
                await asyncio.sleep(2)

    async def _resubscribe_loop(self, ws):
        while True:
            await asyncio.sleep(60)
            try:
                asset_ids = self._get_asset_ids()
                if asset_ids:
                    sub = json.dumps({
                        "type": "subscribe",
                        "channel": "market",
                        "assets_ids": asset_ids,
                    })
                    await ws.send(sub)
                    log.info(f"CLOB WS re-subscribed to {len(asset_ids)} assets")
            except Exception:
                pass

    def _handle_message(self, raw: str):
        try:
            data = json.loads(raw)

            # CLOB WS can send a list of updates or a single dict
            items = data if isinstance(data, list) else [data]

            for item in items:
                if not isinstance(item, dict):
                    continue
                asset_id = item.get("asset_id")
                price = item.get("price")
                if asset_id is None or price is None:
                    continue

                price_f = float(price)
                for m in self.discovery.markets.values():
                    if m.yes_token_id == asset_id:
                        m.yes_price = price_f
                    elif m.no_token_id == asset_id:
                        m.no_price = price_f
        except (json.JSONDecodeError, ValueError):
            pass

