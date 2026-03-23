import re
import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

import httpx

from .config import Config

log = logging.getLogger("clawbot.discovery")


@dataclass
class Market:
    condition_id: str
    question: str
    end_time: float
    yes_token_id: str
    no_token_id: str
    yes_price: float = 0.5
    no_price: float = 0.5
    strike_price: float = 0.0


def extract_strike_price(question: str) -> float:
    match = re.search(r"\$?([\d,]+\.?\d*)", question)
    if match:
        return float(match.group(1).replace(",", ""))
    return 0.0


class MarketDiscovery:
    def __init__(self, config: Config):
        self.config = config
        self.markets: dict[str, Market] = {}
        self._client = httpx.AsyncClient(timeout=15)

    async def poll_once(self):
        try:
            url = f"{self.config.GAMMA_API_URL}/markets"
            params = {"active": "true", "closed": "false", "limit": "100"}
            resp = await self._client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()

            if not isinstance(data, list):
                return

            now = datetime.now(timezone.utc).timestamp() * 1000
            discovered = 0

            for m in data:
                q = (m.get("question") or "").lower()
                is_btc = "bitcoin" in q or "btc" in q
                is_5min = "5 minute" in q or "5min" in q or "five minute" in q

                if not is_btc or not is_5min:
                    continue

                end_iso = m.get("end_date_iso")
                if not end_iso:
                    continue

                end_ts = datetime.fromisoformat(end_iso.replace("Z", "+00:00")).timestamp() * 1000
                time_to_close = end_ts - now

                if time_to_close <= 0 or time_to_close > 5 * 60 * 1000:
                    continue

                tokens = m.get("tokens") or []
                yes_token = next((t for t in tokens if t.get("outcome") == "Yes"), None)
                no_token = next((t for t in tokens if t.get("outcome") == "No"), None)

                if yes_token and no_token:
                    cid = m.get("condition_id", "")
                    self.markets[cid] = Market(
                        condition_id=cid,
                        question=m.get("question", ""),
                        end_time=end_ts,
                        yes_token_id=yes_token.get("token_id", ""),
                        no_token_id=no_token.get("token_id", ""),
                        yes_price=float(yes_token.get("price", "0.5")),
                        no_price=float(no_token.get("price", "0.5")),
                        strike_price=extract_strike_price(m.get("question", "")),
                    )
                    discovered += 1

            expired = [cid for cid, mkt in self.markets.items() if mkt.end_time < now]
            for cid in expired:
                del self.markets[cid]

            if discovered > 0:
                log.info(f"Found {discovered} active 5-min BTC markets. Total tracked: {len(self.markets)}")

        except Exception as e:
            log.error(f"Discovery error: {e}")

    async def run(self):
        log.info("Market discovery started")
        while True:
            await self.poll_once()
            await asyncio.sleep(self.config.MARKET_DISCOVERY_INTERVAL)

    async def close(self):
        await self._client.aclose()
