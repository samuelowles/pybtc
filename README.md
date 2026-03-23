# Clawbot — Polymarket BTC Arbitrage Daemon

Exploits the lag between Binance BTC spot price and Polymarket 5-minute prediction market contract prices. When spot clearly indicates the settlement direction but the contract hasn't caught up, the bot buys the winning side and profits on correction/settlement.

## Architecture

```
Binance WS ──► Spot Price ──┐
                             ├──► Gap Engine ──► py-clob-client ──► CLOB POST /order
Gamma API  ──► Market List ──┤
CLOB WS    ──► Live Prices ──┘
```

## Quick Start (Local)

```bash
cd clawbot
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # Linux/Mac

pip install -e .
cp .env.example .env
# Edit .env with your keys

python -m clawbot.daemon      # Starts in DRY_RUN mode by default
```

## Generate CLOB API Keys

```bash
python setup_keys.py
```

Paste your Polymarket private key when prompted. The script derives your API key, secret, and passphrase using the official `py-clob-client` SDK.

## Deploy to DigitalOcean

### 1. Create a Droplet

- **Image**: Ubuntu 24.04
- **Plan**: Basic $6/mo (1 vCPU, 1 GB RAM) is sufficient
- **Region**: NYC or SFO (low latency to Polymarket/Binance)

### 2. Install Docker

```bash
ssh root@your-droplet-ip
curl -fsSL https://get.docker.com | sh
```

### 3. Upload and Run

```bash
scp -r clawbot/ root@your-droplet-ip:/opt/clawbot
ssh root@your-droplet-ip
cd /opt/clawbot
cp .env.example .env
nano .env   # Add your keys
docker compose up -d
docker compose logs -f   # Watch it run
```

### 4. Go Live

When you're comfortable with dry-run results, set `DRY_RUN=false` in `.env` and restart:

```bash
docker compose down && docker compose up -d
```

## Configuration

| Variable | Required | Default | Description |
|---|---|---|---|
| `PROXY_WALLET_KEY` | Live only | — | Polygon wallet private key |
| `POLYMARKET_CLOB_API_KEY` | Live only | — | CLOB API key |
| `POLYMARKET_CLOB_API_SECRET` | Live only | — | CLOB HMAC secret |
| `POLYMARKET_CLOB_API_PASSPHRASE` | Live only | — | CLOB passphrase |
| `POLYGON_RPC_URL` | Live only | `https://polygon-rpc.com` | Polygon RPC endpoint |
| `DRY_RUN` | — | `true` | `false` for live trading |
| `GAP_THRESHOLD_PERCENT` | — | `0.15` | Minimum gap to trigger trade |
| `MAX_POSITION_USDC` | — | `50` | Max USDC per trade |
| `MAX_DAILY_LOSS_USDC` | — | `100` | Circuit breaker |
| `COOLDOWN_SECONDS` | — | `2` | Seconds between trades |

## Risk Controls

- **Max $50 per trade** — capped position sizing
- **$100 daily loss circuit breaker** — stops all trading when hit
- **2-second cooldown** — prevents rapid-fire execution
- **Per-market deduplication** — one trade per condition ID
- **Daily PnL reset** — automatic midnight reset with logging
