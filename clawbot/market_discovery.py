import json
import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx

from .config import Config

log = logging.getLogger("clawbot.discovery")

SLUG_PREFIX = "btc-updown-5m-"
INTERVAL_SECS = 300  # 5 minutes


@dataclass
class Market:
    condition_id: str
    question: str
    end_time: float      # epoch seconds
    start_time: float    # epoch seconds
    yes_token_id: str    # "Up" outcome token
    no_token_id: str     # "Down" outcome token
    yes_price: float = 0.5
    no_price: float = 0.5
    slug: str = ""


def _next_boundaries(now_ts: float, count: int = 3) -> list[int]:
    """Return the next `count` 5-minute boundary timestamps from now."""
    current_boundary = int(now_ts // INTERVAL_SECS) * INTERVAL_SECS
    return [current_boundary + (i * INTERVAL_SECS) for i in range(count)]


class MarketDiscovery:
    def __init__(self, config: Config):
        self.config = config
        self.markets: dict[str, Market] = {}
        self._client = httpx.AsyncClient(timeout=15)
        self._poll_count = 0

    async def _fetch_event_by_slug(self, slug: str) -> dict | None:
        url = f"{self.config.GAMMA_API_URL}/events"
        params = {"slug": slug}
        try:
            resp = await self._client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, list) and len(data) > 0:
                return data[0]
        except Exception as e:
            log.debug(f"Slug query failed for {slug}: {e}")
        return None

    async def poll_once(self):
        self._poll_count += 1
        now = datetime.now(timezone.utc).timestamp()

        # Compute candidate slugs for current + next 2 boundaries
        boundaries = _next_boundaries(now, count=3)
        slugs = [f"{SLUG_PREFIX}{ts}" for ts in boundaries]

        discovered = 0

        # Fire all slug queries concurrently
        tasks = [self._fetch_event_by_slug(slug) for slug in slugs]
        results = await asyncio.gather(*tasks)

        for slug, event in zip(slugs, results):
            if event is None:
                continue

            event_markets = event.get("markets", [])
            if not event_markets:
                continue

            m = event_markets[0]

            if not m.get("acceptingOrders"):
                continue

            cid = m.get("conditionId", "")
            if cid in self.markets:
                continue

            # Parse token IDs from clobTokenIds JSON string
            clob_ids_raw = m.get("clobTokenIds", "[]")
            try:
                clob_ids = json.loads(clob_ids_raw) if isinstance(clob_ids_raw, str) else clob_ids_raw
            except json.JSONDecodeError:
                clob_ids = []

            if len(clob_ids) < 2:
                log.warning(f"Market {slug} has {len(clob_ids)} token IDs, skipping")
                continue

            # Parse outcome prices
            prices_raw = m.get("outcomePrices", "[]")
            try:
                prices = json.loads(prices_raw) if isinstance(prices_raw, str) else prices_raw
            except json.JSONDecodeError:
                prices = ["0.5", "0.5"]

            # Parse end and start times
            end_date = m.get("endDate", "")
            start_time_str = m.get("eventStartTime", m.get("startDate", ""))
            try:
                end_ts = datetime.fromisoformat(end_date.replace("Z", "+00:00")).timestamp()
            except (ValueError, AttributeError):
                continue

            try:
                start_ts = datetime.fromisoformat(start_time_str.replace("Z", "+00:00")).timestamp()
            except (ValueError, AttributeError):
                start_ts = end_ts - INTERVAL_SECS

            time_to_close = end_ts - now

            # Only track markets closing within 10 minutes (room for 1 full cycle + buffer)
            if time_to_close <= 0 or time_to_close > 600:
                continue

            self.markets[cid] = Market(
                condition_id=cid,
                question=m.get("question", event.get("title", "")),
                end_time=end_ts,
                start_time=start_ts,
                yes_token_id=clob_ids[0],  # "Up" token
                no_token_id=clob_ids[1],   # "Down" token
                yes_price=float(prices[0]) if len(prices) > 0 else 0.5,
                no_price=float(prices[1]) if len(prices) > 1 else 0.5,
                slug=slug,
            )
            discovered += 1

        # Purge expired markets
        expired = [cid for cid, mkt in self.markets.items() if mkt.end_time < now]
        for cid in expired:
            del self.markets[cid]

        if self._poll_count <= 5 or discovered > 0:
            log.info(
                f"Poll #{self._poll_count}: checked slugs {[s.split('-')[-1] for s in slugs]}, "
                f"discovered={discovered}, tracked={len(self.markets)}"
            )

        if discovered > 0:
            for mkt in self.markets.values():
                ttc = mkt.end_time - now
                log.info(
                    f"  → {mkt.question[:60]} | slug={mkt.slug} | "
                    f"Up={mkt.yes_price} Down={mkt.no_price} | closes in {ttc:.0f}s"
                )

    async def run(self):
        log.info("Market discovery started (slug-based, 5min BTC)")
        while True:
            await self.poll_once()
            await asyncio.sleep(self.config.MARKET_DISCOVERY_INTERVAL)

    async def close(self):
        await self._client.aclose()
