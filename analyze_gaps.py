"""
Clawbot Gap Analysis — Historical Backtester

Pulls recent resolved BTC 5-minute markets from Gamma API,
cross-references with Binance kline data, and identifies
where price-lag arbitrage opportunities existed.
"""

import asyncio
import httpx
import time
import json
from datetime import datetime, timezone

GAMMA_API = "https://gamma-api.polymarket.com"
BINANCE_API = "https://api.binance.com/api/v3"
SLUG_PREFIX = "btc-updown-5m-"
INTERVAL_SECS = 300


async def get_recent_markets(client: httpx.AsyncClient, count: int = 50):
    """Fetch recent resolved BTC 5-minute markets."""
    now = int(time.time())
    markets = []

    for offset in range(0, count * INTERVAL_SECS, INTERVAL_SECS):
        ts = ((now - offset) // INTERVAL_SECS) * INTERVAL_SECS
        slug = f"{SLUG_PREFIX}{ts}"
        try:
            resp = await client.get(f"{GAMMA_API}/events?slug={slug}")
            data = resp.json()
            if isinstance(data, list) and len(data) > 0:
                event = data[0]
                event_markets = event.get("markets", [])
                if event_markets:
                    m = event_markets[0]
                    outcome = m.get("outcome", "")
                    prices = json.loads(m.get("outcomePrices", '["0.5","0.5"]'))
                    markets.append({
                        "slug": slug,
                        "timestamp": ts,
                        "question": m.get("question", ""),
                        "outcome": outcome,
                        "resolved": m.get("closed", False),
                        "yes_price": float(prices[0]) if prices else 0.5,
                        "no_price": float(prices[1]) if len(prices) > 1 else 0.5,
                        "end_time": ts + INTERVAL_SECS,
                    })
        except Exception as e:
            continue

    return markets


async def get_btc_klines(client: httpx.AsyncClient, start_ts: int, end_ts: int):
    """Fetch 1-second BTC klines from Binance for a time range."""
    try:
        resp = await client.get(
            f"{BINANCE_API}/klines",
            params={
                "symbol": "BTCUSDT",
                "interval": "1s",
                "startTime": start_ts * 1000,
                "endTime": end_ts * 1000,
                "limit": 300,
            },
        )
        data = resp.json()
        if isinstance(data, list):
            return [
                {
                    "time": int(k[0]) // 1000,
                    "open": float(k[1]),
                    "high": float(k[2]),
                    "low": float(k[3]),
                    "close": float(k[4]),
                }
                for k in data
            ]
    except Exception as e:
        print(f"  Binance error: {e}")
    return []


def analyze_market(market: dict, klines: list):
    """Analyze a single market for price-lag opportunities."""
    if not klines:
        return None

    start_ts = market["timestamp"]
    end_ts = start_ts + INTERVAL_SECS

    start_price = klines[0]["close"]
    end_price = klines[-1]["close"] if klines else start_price

    btc_moved_up = end_price > start_price
    btc_move_pct = (end_price - start_price) / start_price * 100

    actual_winner = "UP" if btc_moved_up else "DOWN"

    last_30s_klines = [k for k in klines if k["time"] >= end_ts - 30]
    last_60s_klines = [k for k in klines if k["time"] >= end_ts - 60]

    snapshots = []
    for seconds_before in [60, 45, 30, 20, 15, 10, 5]:
        target_ts = end_ts - seconds_before
        closest = min(klines, key=lambda k: abs(k["time"] - target_ts), default=None)
        if closest:
            btc_at_point = closest["close"]
            btc_pct = (btc_at_point - start_price) / start_price * 100
            direction = "UP" if btc_at_point > start_price else "DOWN"
            correct = direction == actual_winner
            snapshots.append({
                "seconds_before_close": seconds_before,
                "btc_price": btc_at_point,
                "btc_move_from_start_pct": round(btc_pct, 4),
                "predicted_direction": direction,
                "was_correct": correct,
            })

    prediction_accuracy = {}
    for s in snapshots:
        prediction_accuracy[s["seconds_before_close"]] = s["was_correct"]

    return {
        "slug": market["slug"],
        "question": market["question"][:60],
        "start_price": start_price,
        "end_price": end_price,
        "btc_move_pct": round(btc_move_pct, 4),
        "actual_winner": actual_winner,
        "pm_yes_final": market["yes_price"],
        "pm_no_final": market["no_price"],
        "outcome": market["outcome"],
        "snapshots": snapshots,
        "prediction_accuracy": prediction_accuracy,
    }


async def main():
    print("=" * 70)
    print("  Clawbot Gap Analysis — Historical Backtester")
    print("=" * 70)

    async with httpx.AsyncClient(timeout=15) as client:
        print("\n[1/3] Fetching recent BTC 5-minute markets...")
        markets = await get_recent_markets(client, count=30)
        resolved = [m for m in markets if m.get("resolved")]
        print(f"  Found {len(markets)} markets, {len(resolved)} resolved")

        if not resolved:
            print("  No resolved markets found. Try again later.")
            return

        results = []
        print(f"\n[2/3] Analyzing {len(resolved)} markets with Binance data...\n")

        for i, market in enumerate(resolved[:20]):
            print(f"  [{i+1}/{min(20, len(resolved))}] {market['slug']}...", end=" ")
            klines = await get_btc_klines(
                client,
                market["timestamp"],
                market["timestamp"] + INTERVAL_SECS,
            )
            if klines:
                result = analyze_market(market, klines)
                if result:
                    results.append(result)
                    print(f"BTC {result['btc_move_pct']:+.3f}% → {result['actual_winner']}")
                else:
                    print("no data")
            else:
                print("no klines")
            await asyncio.sleep(0.2)

        print(f"\n[3/3] Results Summary")
        print("=" * 70)

        correct_at = {60: 0, 45: 0, 30: 0, 20: 0, 15: 0, 10: 0, 5: 0}
        total = len(results)

        for r in results:
            for secs, was_correct in r["prediction_accuracy"].items():
                if was_correct:
                    correct_at[secs] += 1

        print(f"\n  Direction prediction accuracy (does BTC direction at T-X match final outcome?):")
        print(f"  {'Seconds before close':<25} {'Correct':<10} {'Accuracy':<10}")
        print(f"  {'-'*45}")
        for secs in sorted(correct_at.keys(), reverse=True):
            acc = correct_at[secs] / total * 100 if total > 0 else 0
            print(f"  T-{secs:<3}s{' '*18} {correct_at[secs]}/{total}{' '*5} {acc:.0f}%")

        print(f"\n  BTC move distribution (start to end):")
        moves = [abs(r["btc_move_pct"]) for r in results]
        if moves:
            print(f"    Average: {sum(moves)/len(moves):.4f}%")
            print(f"    Max:     {max(moves):.4f}%")
            print(f"    Min:     {min(moves):.4f}%")

        big_moves = [r for r in results if abs(r["btc_move_pct"]) > 0.05]
        print(f"\n  Markets with BTC move >0.05%: {len(big_moves)} / {total}")

        print(f"\n  Detailed market-by-market:")
        print(f"  {'Slug':<30} {'BTC Move':<12} {'Winner':<8} {'PM Yes':<10} {'PM No':<10}")
        print(f"  {'-'*70}")
        for r in results:
            print(
                f"  {r['slug'][-20:]:<30} {r['btc_move_pct']:+.4f}%{' '*4} "
                f"{r['actual_winner']:<8} {r['pm_yes_final']:<10.2f} {r['pm_no_final']:<10.2f}"
            )

        print(f"\n  Snapshots for most volatile market:")
        if results:
            most_volatile = max(results, key=lambda r: abs(r["btc_move_pct"]))
            print(f"  {most_volatile['slug']} (BTC {most_volatile['btc_move_pct']:+.4f}%)")
            print(f"  {'T-X':<10} {'BTC Price':<15} {'Move%':<12} {'Direction':<10} {'Correct?'}")
            for s in most_volatile["snapshots"]:
                print(
                    f"  T-{s['seconds_before_close']:<3}s   "
                    f"${s['btc_price']:<12.2f} {s['btc_move_from_start_pct']:+.4f}%{' '*4} "
                    f"{s['predicted_direction']:<10} {'✓' if s['was_correct'] else '✗'}"
                )


if __name__ == "__main__":
    asyncio.run(main())
