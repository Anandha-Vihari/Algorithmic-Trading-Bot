# Algorithmic Trading Bot — Blind Follower with Proxy Rotation

A fully autonomous forex trading bot that **blindly follows website signals** with **10 rotating proxies** to avoid rate limiting and detection. No intelligence filtering—trades exactly what the website signals, no more, no less. Built for MetaTrader 5 on Windows.

---

## 📖 Table of Contents

1. [Overview](#overview)
2. [How It Works](#how-it-works)
3. [Key Features](#key-features)
4. [Architecture](#architecture)
5. [Installation & Setup](#installation--setup)
6. [Configuration](#configuration)
7. [Running the Bot](#running-the-bot)
8. [Signal Processing](#signal-processing)
9. [Proxy System](#proxy-system)
10. [Logs & Monitoring](#logs--monitoring)
11. [Troubleshooting](#troubleshooting)
12. [Safety & Risk Management](#safety--risk-management)
13. [Advanced Customization](#advanced-customization)
14. [FAQ](#faq)

---

## Overview

### What Is This?

This bot automatically trades forex based on signals from a website. It:

1. **Fetches** signals from a website (every 7 seconds)
2. **Parses** the HTML to extract trade instructions (pair, direction, entry, stop loss, take profit)
3. **Opens trades** when a signal is marked ACTIVE
4. **Closes trades** when the website says CLOSE
5. **Logs everything** to a file for monitoring

### Why "Blind Follower"?

The bot does **zero filtering**. It doesn't:
- Check if the signal is profitable
- Analyze market conditions
- Filter pairs
- Adjust stops
- Extend take profits
- Use trailing stops

It just reads what the website says and executes it. This is intentional—**the website is your signal provider, and you're trusting it completely.**

### Why This Project Exists

Some traders find value in:
- Following professional signal providers without manual intervention
- Automating order placement (reduces latency, prevents hesitation)
- Testing signal quality at scale (run it, log results, analyze offline)
- Distributed execution (10 proxies = harder to detect, avoid rate limits)

---

## How It Works

### The Trading Flow

```
┌──────────────────────────────────────────────────────────────┐
│                    WEBSITE SIGNAL PROVIDER                   │
│  (Shows: BUY EURUSD @ 1.08500, TP 1.09000, SL 1.08000)      │
└─────────────────────────┬──────────────────────────────────┘
                          │
                          ↓
┌──────────────────────────────────────────────────────────────┐
│                   BOT (7-second loop)                        │
│                                                              │
│  1. Pick a random proxy from 10 rotating IPs                │
│     ├─ ProxyScrape Free API refreshes every 5 minutes       │
│     └─ Temporary blacklist failed proxies for 60 seconds    │
│                                                              │
│  2. Fetch website HTML through selected proxy               │
│     ├─ If proxy fails → auto-retry with next proxy          │
│     └─ If all fail → skip this cycle, try again in 7s       │
│                                                              │
│  3. Parse HTML to extract signals                           │
│     ├─ Look for tables with: Pair, Side, Open, TP, SL      │
│     └─ Split by timeframe: short (15/30min) & long (1/4hr)  │
│                                                              │
│  4. For each ACTIVE signal:                                 │
│     ├─ Check if already processed (prevent duplicates)      │
│     ├─ Check if below position cap (MAX_POSITIONS = 10)     │
│     ├─ Check if symbol available in MT5                     │
│     └─ Send market order with website's exact SL/TP         │
│                                                              │
│  5. For each CLOSE signal:                                  │
│     ├─ Find open position for that pair                     │
│     └─ Close it immediately (respect website command)       │
│                                                              │
│  6. Log results and repeat in 7 seconds                      │
└──────────────────────────────────────────────────────────────┘
                          │
                          ↓
┌──────────────────────────────────────────────────────────────┐
│                    METATRADER 5 ACCOUNT                      │
│  (Your trading account where trades are executed)            │
└──────────────────────────────────────────────────────────────┘
```

### What Happens When a Signal Arrives

**Scenario: Website shows "BUY EURUSD @ 1.08500, TP 1.09000, SL 1.08000"**

```
Step 1: Bot detects ACTIVE status
         ✓ Signal not marked CLOSE

Step 2: Check if already opened
         ✓ First time seeing this signal (checked against processed_signals)

Step 3: Check position count
         ✓ Currently 7 open positions, max is 10 (room for 3 more)

Step 4: Validate symbol
         ✓ EURUSD exists and is tradable in MT5

Step 5: Get current price
         ✓ Tick data available: Ask = 1.08523, Bid = 1.08521

Step 6: Send order
         Type: BUY
         Volume: 0.01 lots (from config)
         Entry Price: 1.08523 (current ask)
         Stop Loss: 1.08000 (from website—no adjustment)
         Take Profit: 1.09000 (from website—no adjustment)

Step 7: Broker response
         ✓ Order accepted, ticket #123456 created
         → Log: "[14:32:01] EURUSD BUY: Order opened @ 1.08523"

Step 8: Trade is now open
         Waiting for either:
         - Website to say "CLOSE EURUSD" → bot will close it
         - Take profit to hit 1.09000 → MT5 auto-closes
         - Stop loss to hit 1.08000 → MT5 auto-closes
         - Dollar stop loss (-$1.50) → bot force-closes
```

---

## Key Features

### ✓ Proxy Rotation (10 Rotating IPs)

**Problem**: Fetching signals every 7 seconds from one IP = ~515 requests/hour = **instant rate limit/ban**

**Solution**:
- Fetch 10+ free proxies from ProxyScrape API
- Rotate through them round-robin style
- Each proxy gets ~52 requests/hour (acceptable)
- Auto-blacklist failed proxies for 60 seconds
- Automatic refresh every 5 minutes

### ✓ Fast Signal Detection (7 Seconds)

Old version checked every 66 seconds. Now every 7 seconds.

**Impact**:
- Catch signals earlier (more time for SL/TP to trigger correctly)
- 10x more signal cycles per day (from ~1,300 to ~12,300)
- Better hit rate on time-sensitive signals

### ✓ Zero Filtering

Takes 100% of signals without any logic:

| Check | Status |
|-------|--------|
| Currency blacklist | ✗ REMOVED—trade all pairs |
| R:R ratio minimum | ✗ REMOVED—trade any ratio |
| Spread limit | ✗ REMOVED—any spread is ok |
| Market hours | ✗ REMOVED—trade 24/7 |
| Confluence check | ✗ REMOVED—ignore other timeframes |
| Profit guard | ✗ REMOVED—no emergency closes for profit |
| Trailing stop | ✗ REMOVED—use website's TP exactly |
| TP extension | ✗ REMOVED—no manipulation |
| Time-based close | ✗ REMOVED—only close on signal |

**Philosophy**: The website is your entire decision-making system. No second-guessing.

### ✓ Simple State Management

Tracks which signals have been processed to prevent:
- Opening the same trade twice
- Missing close signals and forgetting about positions

Data persists across bot restarts in `processed_signals.json`.

### ✓ Emergency Dollar Stop Loss

If a position loses more than `DOLLAR_STOP_LOSS` ($1.50), the bot force-closes it immediately. Prevents catastrophic losses from:
- Overnight gaps
- Broker slippage
- Website signals going wrong

---

## Architecture

### Three Core Components

#### 1. **Signal Fetcher** (`scraper.py`)
- Maintains list of 10 rotating proxies
- Refreshes proxy list from ProxyScrape API every 5 minutes
- Implements round-robin or random rotation strategy
- Retries failed proxies with next in line
- Returns HTML page or None on total failure

#### 2. **Signal Parser** (`parser.py`)
- Parses HTML with BeautifulSoup
- Extracts tables with: Pair, Side, Open Price, TP, SL, Status
- Splits signals into two timeframes: "short" (15/30min) and "long" (1/4hr)
- Converts text to structured signal objects

#### 3. **Trade Executor** (`trader.py`)
- Connects to MT5 via Python API
- `open_trade()`: Sends market order with website's SL/TP
- `close_trade()`: Closes position by pair
- Handles symbol lookup (pair vs pair+)
- Records order results

### Single-Thread Design

```
Main Thread
│
├─ Initialize MT5
│
└─ Signal Thread (daemon) ← loops every 7 seconds
   │
   ├─ Fetch HTML (proxy rotation)
   ├─ Parse signals
   ├─ Process ACTIVE signals (open trades)
   ├─ Process CLOSE signals (close trades)
   ├─ Log status
   └─ Sleep 7 seconds → repeat
```

**Why single-threaded?**
- Simple and predictable (no race conditions)
- MT5 API isn't thread-safe (better to use sequentially)
- Easy to debug and monitor
- No complex state synchronization

### State Persistence

```
processed_signals.json
{
  "EURUSD_2026-03-18 14:32 PM UTC_BUY_short": "2026-03-18T14:32:00+00:00",
  "GBPUSD_2026-03-18 14:39 PM UTC_SELL_long": "2026-03-18T14:39:15+00:00",
  ...
}
```

When bot restarts, it loads this file and skips signals it has already processed.

---

## Installation & Setup

### Requirements

- **Windows** (MetaTrader 5 is Windows-only)
- **Python 3.8+**
- **MetaTrader 5** installed and configured
- **Demo or Live account** with a broker

### Step 1: Install Python Packages

```bash
pip install requests beautifulsoup4 MetaTrader5
```

- `requests`: HTTP client for proxy fetching and signal scraping
- `beautifulsoup4`: HTML parsing
- `MetaTrader5`: Official Python API for MT5

### Step 2: Configure the Bot

Edit `config.py`:

```python
# Website and signals
URL = "http://massyart.com/ringsignal/"

# Proxy rotation (10 free proxies from ProxyScrape)
PROXY_API_URL = "https://api.proxyscrape.com/v4/free-proxy-list/get?request=display_proxies&proxy_format=protocolipport&format=text"
PROXY_CACHE_SECONDS = 300        # Refresh every 5 minutes
PROXY_ROTATION_STRATEGY = "round_robin"  # or "random"

# Timing
SIGNAL_INTERVAL = 7              # Check website every 7 seconds

# Trading parameters
TRADE_VOLUME = 0.01              # Lot size (0.01 = 1 micro-lot = ~$1 per pip)
MAX_POSITIONS = 10               # Max concurrent positions

# Safety
DOLLAR_STOP_LOSS = 1.50          # Force-close if loss > $1.50

# MT5 Account (your credentials)
MT5_LOGIN = 24343206             # Your account number
MT5_PASSWORD = "oiAZ!5s6"        # Your password
MT5_SERVER = "VantageInternational-Demo"  # Your broker's server
MT5_EXE = r"C:\Users\h\AppData\Roaming\MetaTrader 5\terminal64.exe"
```

**Important**: Keep credentials secure. Don't commit `config.py` to public repositories.

### Step 3: Test MT5 Connection

```python
# Quick test script
import MetaTrader5 as mt5

if mt5.initialize(login=24343206, password="oiAZ!5s6", server="VantageInternational-Demo"):
    print("✓ Connected to MT5")
    info = mt5.account_info()
    print(f"  Balance: ${info.balance:.2f}")
    print(f"  Equity: ${info.equity:.2f}")
else:
    print("✗ MT5 connection failed")
    print(mt5.last_error())
```

### Step 4: Run the Bot

```bash
python main.py
```

Bot will:
1. Initialize MT5
2. Start signal loop
3. Log to `bot.log`
4. Keep running (Ctrl+C to stop)

---

## Configuration

### Essential Parameters

#### SIGNAL_INTERVAL = 7
How often (in seconds) to check the website for new signals.

- **7 seconds** (default): Fast, catches signals quickly
- **10-15 seconds**: If getting 403 rate-limit errors
- **30+ seconds**: For very conservative proxy usage

*Higher = fewer proxies needed, but slower signal detection.*

#### TRADE_VOLUME = 0.01
How much to trade per signal (in lots).

- **0.01**: 1 micro-lot ≈ $1 per pip (safe for testing)
- **0.1**: 1 mini-lot ≈ $10 per pip
- **1.0**: 1 standard lot ≈ $100 per pip

*Start with 0.01 and only increase after 2+ weeks of successful testing.*

#### MAX_POSITIONS = 10
Maximum concurrent open positions.

- **5**: Conservative (focus on top signals)
- **10**: Balanced (catch most signals)
- **20**: Aggressive (maximize trading volume)

*If you hit this limit, older signals are skipped until positions close.*

#### DOLLAR_STOP_LOSS = 1.50
Emergency cutoff: force-close any position losing more than this.

- **$0.50**: Tight safety (lose max $0.50 per trade)
- **$1.50**: Default (lose max $1.50 per trade)
- **$5.00**: Loose safety (let trades breathe)

*This is your last line of defense against gaps/slippage.*

### Proxy Parameters

#### PROXY_ROTATION_STRATEGY = "round_robin"
How to pick the next proxy:

- **"round_robin"**: Cycle 1→2→3→...→10→1→2 (predictable)
- **"random"**: Pick random each time (less predictable, potentially safer)

#### PROXY_CACHE_SECONDS = 300
How long to use the same proxy list before fetching fresh ones.

- **300** (5 min): Default, balances freshness + API load
- **600** (10 min): If ProxyScrape API is unreliable
- **60** (1 min): If proxies die quickly

---

## Running the Bot

### Basic Startup

```bash
python main.py
```

Output:
```
================================================================================
BLIND FOLLOWER BOT - STARTED
Signal interval: 7s | Max positions: 10 | Volume: 0.01
================================================================================

MT5 connected
PROXY: fetched 10 proxies from API
[14:32:05] Status: 0 opened, 0 closed
  No open positions
  Account: Balance $10000.00 | Equity $10000.00
```

### Monitor in Real-Time

Watch signal events as they happen:

```bash
tail -f bot.log
```

Example log output:
```
[14:32:00] SIGNAL: EURUSD BUY @ 1.08500 SL:1.08000 TP:1.09000
  → OPENED ✓
[14:32:05] CLOSE: EURUSD (website signal)
  → CLOSED ✓
[14:32:10] SIGNAL: GBPUSD SELL @ 1.26000 SL:1.27500 TP:1.25000
  → OPENED ✓
[14:32:15] Status: 2 opened, 1 closed
  Open positions: 1
    [GBPUSD] SELL @ 1.26002 | Profit: -$0.02
  Account: Balance $10000.00 | Equity $9999.98
```

### Stop the Bot

```
Ctrl+C
```

The bot exits cleanly. All processed signals are saved in `processed_signals.json`, so it won't re-open them on next run.

---

## Signal Processing

### What Is a Signal?

```python
{
    'pair': 'EURUSD',           # Currency pair to trade
    'side': 'BUY',              # Direction (BUY or SELL)
    'open': 1.08500,            # Entry price (reference, not used)
    'tp': 1.09000,              # Take profit target
    'sl': 1.08000,              # Stop loss level
    'frame': 'short',           # Timeframe: 'short' (15/30min) or 'long' (1/4hr)
    'status': 'ACTIVE',         # Status: 'ACTIVE' (open trade) or 'CLOSE' (close trade)
    'time': datetime(...)       # When signal was posted
}
```

### Signal States

#### ACTIVE
Website is saying "Open a trade now."

Bot will:
1. Check if already processed
2. Check if below position cap
3. Send market order with signal's exact SL/TP
4. Log the result

#### CLOSE
Website is saying "Close this trade now."

Bot will:
1. Find open position for that pair
2. Send market close order
3. Log profit/loss

### Processing Order

Each cycle processes signals in this order:

```
1. Fetch HTML from website (via proxy)
2. Parse all signals
3. Process all ACTIVE signals (oldest first)
   └─ Skip duplicates, skip if at position cap
4. Process all CLOSE signals
5. Display summary (positions, P&L)
6. Sleep 7 seconds
7. Repeat
```

### Duplicate Prevention

If same signal arrives twice (same pair, side, time, frame), bot opens it **once only**.

Detected via: `"{pair}_{time}_{side}_{frame}"` key in `processed_signals.json`

---

## Proxy System

### Why Proxies Are Critical

**Without proxies:**
- 7-second interval × 10 URLs/day = ~12,300 requests/hour from one IP
- Website blocks your IP instantly
- Bot stops getting signals

**With 10 rotating proxies:**
- 12,300 ÷ 10 = 1,230 requests/hour per IP
- Spread across devices/locations
- Much harder to detect and block

### How Proxy Rotation Works

#### 1. Fetch Proxies (every 5 minutes)

Bot calls ProxyScrape API:
```
GET https://api.proxyscrape.com/v4/free-proxy-list/get?request=display_proxies&proxy_format=protocolipport&format=text
```

Returns:
```
203.150.122.10:8080
168.195.101.5:3128
45.129.202.18:3128
... (10+ proxies)
```

Bot stores top 10, uses for next 5 minutes.

#### 2. Rotate on Each Request

**Round-Robin:**
```
Request 1: Proxy #1
Request 2: Proxy #2
...
Request 10: Proxy #10
Request 11: Proxy #1 (repeat)
```

**Random:**
```
Request 1: Proxy #7
Request 2: Proxy #2
Request 3: Proxy #9
... (random each time)
```

#### 3. Handle Failures

If proxy fails (timeout, 403, connection error):
- Mark as failed (count++)
- Auto-try next proxy in list
- After 3 failures: blacklist for 60 seconds
- If all proxies fail: skip cycle, retry in 7 seconds

#### 4. Why HTTP Not HTTPS?

Free proxies don't support HTTPS CONNECT tunneling (secure proxy tunneling protocol).

- HTTPS to `https://massyart.com/` = **FAIL** (requires CONNECT, not supported)
- HTTP to `http://massyart.com/` = **OK** (simple forwarding works)

Solution: Website serves on HTTP (not HTTPS), proxies work fine.

---

## Logs & Monitoring

### bot.log

Every signal event is logged to `bot.log`:

```
[14:32:00] WARNING: Could not fetch signals (proxy failed)
[14:32:05] SIGNAL: EURUSD BUY @ 1.08500 SL:1.08000 TP:1.09000
  → OPENED ✓
[14:32:10] SIGNAL: GBPUSD SELL @ 1.26000 SL:1.27500 TP:1.25000
  → SKIP] Symbol temporarily unavailable
[14:32:15] CLOSE: AUDNZD (website signal)
  → CLOSED ✓
[14:32:15] Status: 2 opened, 0 closed
  Open positions: 2
    [EURUSD] BUY @ 1.08523 | Profit: +$0.23
    [GBPUSD] SELL @ 1.26002 | Profit: -$0.02
  Account: Balance $10000.00 | Equity $10000.21
```

### What Each Log Line Means

| Log | Meaning |
|-----|---------|
| `[14:32:00] SIGNAL: EURUSD ...` | Website signal detected, about to open trade |
| `→ OPENED ✓` | Trade successfully opened |
| `→ SKIP] Symbol ...` | Trade skipped (reason shown) |
| `[14:32:10] CLOSE: EURUSD ...` | Website said close, executing close order |
| `→ CLOSED ✓` | Position successfully closed |
| `Status: X opened, Y closed` | Summary of this cycle (X new opens, Y closes) |
| `Open positions: N` | Current number of open trades |
| `Account: Balance X, Equity Y` | Account snapshot (balance = locked + free) |

### Console Output (Every Cycle)

Every 7 seconds console shows:
- Timestamp
- Number of trades opened/closed this cycle
- List of open positions (symbol, type BUY/SELL, entry price, profit)
- Account balance and equity

Use this to monitor bot health in real-time.

### Analyzing Results

To see how many trades opened today:

```bash
grep "OPENED ✓" bot.log | wc -l
```

To see average profit per closed trade:

```bash
grep "CLOSED ✓" bot.log | grep "Profit:" | ...
```

To find failed trades:

```bash
grep "\[SKIP\]" bot.log
```

---

## Troubleshooting

### Problem: "PROXY: all retries exhausted, returning None"

**Cause**: All 10 proxies failed. Website not fetched.

**Solutions**:
1. Increase `SIGNAL_INTERVAL` to 10-15 seconds (give proxies time to recover)
2. Check internet connection (ping google.com)
3. Verify ProxyScrape API is up:
   ```bash
   curl "https://api.proxyscrape.com/v4/free-proxy-list/get?request=display_proxies&proxy_format=protocolipport&format=text"
   ```
4. Try different `PROXY_ROTATION_STRATEGY` ("random" vs "round_robin")

### Problem: No Trades Opening

Bot fetches signals but never opens trades.

**Debug**:
1. Check `bot.log` for `[SKIP]` messages
2. Common reasons:
   - **"Symbol not available"**: Pair doesn't exist in MT5 (typo or not enabled)
   - **"No tick data"**: MT5 not connected or symbol not tradable
   - **"Position cap reached"**: Already have MAX_POSITIONS open
   - **"Order rejected"**: Stops are invalid (SL/TP too close to market)

### Problem: Getting Rate-Limited (403 Forbidden Errors)

Website is blocking your proxies.

**Solutions**:
1. Increase `SIGNAL_INTERVAL` from 7 to 15-30 seconds
2. Reduce `PROXY_ROTATION_STRATEGY` to "random" (less predictable)
3. Run bot only during specific market hours (not 24/7)
4. Lower `TRADE_VOLUME` so fewer trades = fewer requests

### Problem: Missing Signals

Bot runs but doesn't see signals that are on website.

**Debug**:
1. Check `bot.log` for "PROXY: success" messages (proxies connecting?)
2. Manually visit website (not via proxy) to verify signals are there
3. Check if signal HTML structure changed (parser might be out of date)
4. Verify `processed_signals.json` doesn't have old version of signal

### Problem: Losing Money

Trades opened but account going negative.

**Check**:
1. Is the website signal provider profitable? (Compare her results → bot results)
2. Are SL/TP being set correctly? (Log them, verify manually in MT5)
3. Is slippage eating profit? (Check order fill prices vs signal prices)
4. How many trades are hitting stop loss vs take profit? (Should be 50/50 if signals are good)

---

## Safety & Risk Management

### The DOLLAR_STOP_LOSS (Your Last Line of Defense)

This setting force-closes any position losing more than the limit.

```python
DOLLAR_STOP_LOSS = 1.50  # Force close if loss > $1.50
```

Protects against:
- **Overnight gaps** (market gaps 200 pips, SL 50 pips away = real loss)
- **Broker slippage** (SL rejected, position held, loss grows)
- **Website signals going wrong** (signal gives bad SL)
- **Black swan events** (flash crash, economic shock)

**Example**:
- Trade opened: BUY 0.01 EURUSD @ 1.08523
- Stop loss: 1.08000 (500 pips = $5 loss)
- Overnight gap down to 1.07200 (crash)
- Setting: DOLLAR_STOP_LOSS = 1.50
- Bot detects: Loss = -$13.23
- Bot action: Force-close immediately, loss capped at ~$1.50

### Position Cap (MAX_POSITIONS)

Limits how many trades can be open simultaneously.

```python
MAX_POSITIONS = 10
```

Prevents:
- **Correlation risk** (all 10 trades fail together)
- **Margin call risk** (too much risk used up)
- **Recovery bottleneck** (if losing, hard to recover with 20 open losers)

**Strategy**:
- Start with MAX_POSITIONS = 5 (conservative)
- Test for 1 week
- If profitable and stable, increase to 10
- Never go above 15 without professional risk analysis

### Trade Volume (TRADE_VOLUME)

How much capital per trade.

```python
TRADE_VOLUME = 0.01  # 1 micro-lot ≈ $1 per pip
```

**Risk Example**:
- Trade volume = 0.01 lots
- Currency pair = EURUSD
- Risk per pip = $0.10
- If stop loss is 50 pips away = $5 max loss per trade
- With 10 open positions = $50 max total risk
- With DOLLAR_STOP_LOSS = $1.50 per position = $15 max total risk

**Recommendation**:
- Start with 0.01 lots
- After 2 weeks profitable, increase to 0.05
- After 1 month profitable, increase to 0.1
- Never jump more than 2x at a time

### Monitoring Your Account

Keep close eye on:

| Metric | Check | Action |
|--------|-------|--------|
| **Daily loss** | > $5? | Stop trading for day, investigate |
| **Winning % of trades** | Should be > 40%? | If < 30%, question signal quality |
| **Avg win vs avg loss** | Should be similar? | If wins are tiny, losses huge = bad risk/reward |
| **Max consecutive losses** | How many losers in a row? | If > 5 consecutive, signal provider may be off |

---

## Advanced Customization

### Change Signal Check Interval to 5 Seconds

```python
# config.py
SIGNAL_INTERVAL = 5
```

**Impact**:
- Faster signal detection (great for time-sensitive signals)
- Higher bandwidth usage (~720 requests/hour)
- More proxies needed (~30 to stay under rate limit)

### Switch to Random Proxy Selection

```python
# config.py
PROXY_ROTATION_STRATEGY = "random"
```

**Impact**:
- Less predictable proxy pattern (harder for website to detect)
- Potentially safer for long-term operation
- May be slightly slower (some proxies might be temporarily slow)

### Increase Trade Volume (More Aggressive)

```python
# config.py
TRADE_VOLUME = 0.1  # 10x more risk
```

**Impact**:
- $10 per pip (instead of $1)
- Profits and losses are 10x larger
- Much higher margin requirement
- Good for confident traders with equity cushion

### Lower Emergency Stop Loss (More Conservative)

```python
# config.py
DOLLAR_STOP_LOSS = 0.50  # Half the original
```

**Impact**:
- Positions exit faster if losing
- Smaller losses but also less patience for signal setup
- Might exit good trades that need 10+ pip wiggle room

### Test on Demo First

**Never go live without:**

1. Run on demo account for at least 2 weeks
2. Verify signal provider is profitable (check her P&L)
3. Confirm proxy system is stable (no 403 errors)
4. Check that trades are opening with correct SL/TP
5. Monitor a few closing trades and verify profit calculation

```python
# To switch to demo:
MT5_SERVER = "VantageInternational-Demo"  # or your broker's demo

# To switch to live:
MT5_SERVER = "VantageInternational-Live"  # ONLY after 2+ weeks demo testing
```

---

## FAQ

### Q: Is this a scam?
**A**: No. This is a legitimate trading bot that executes trades based on signals from a website. Whether the *website signals* are profitable is a different question—depends on the signal provider.

### Q: Can I use this with my broker?
**A**: Only if your broker:
1. Supports MetaTrader 5 (most do)
2. Allows automated/algorithmic trading (check terms)
3. Doesn't restrict EA/script usage

### Q: How much can I make?
**A**: Depends entirely on:
- Signal provider quality
- Trade volume (TRADE_VOLUME setting)
- Market conditions
- Luck

Bot is just an execution engine. It's only as good as the signals. Garbage signals = garbage results.

### Q: What if the website goes down?
**A**: Bot can't fetch signals, so it keeps open positions but doesn't open new ones. Positions held until you manually close them or bot force-closes via DOLLAR_STOP_LOSS.

### Q: Can I run multiple bots simultaneously?
**A**: Yes, but each needs:
- Different MT5 account (don't trade same pair twice)
- Or one bot with different pairs than the other
- Or on different machines to avoid same public IP

### Q: Will the website detect and block me?
**A**: Unlikely with 10 rotating proxies. But possible if:
- Too many requests (reduce SIGNAL_INTERVAL)
- Same user-agent (uses Mozilla Firefox, should be normal)
- Getting blacklisted proxies (they auto-recover after 60s)

### Q: What's the best SIGNAL_INTERVAL value?
**A**: Start with 7 seconds. If you get 403 errors frequently, increase to 10-15. If you want faster detection and don't mind proxies dying, try 5.

### Q: Can I modify the SL/TP from the website?
**A**: Not easily without editing code. Philosophy of this bot: **trust the website completely**. If you want to adjust stops, either adjust them via website or modify `trader.py`.

### Q: Why use HTTP instead of HTTPS?
**A**: Free proxies don't support HTTPS CONNECT tunneling. It's fine because we're only fetching signals, not sensitive data. No passwords/logins transmitted.

### Q: What if a trade fills at bad slippage?
**A**: MT5 will try to fill at your SL/TP. If slippage is huge, order might be rejected. Bot will skip that signal and try next cycle.

### Q: Can I backtest this bot?
**A**: Not directly. But you can:
1. Save all signals to a file
2. Simulate opening/closing trades with those signals
3. Calculate P&L offline
4. Compare to bot's actual P&L

### Q: Is this legal?
**A**: Algorithmic trading is legal. Some brokers restrict it, so check your broker's terms. Never use to exploit glitches or market manipulation.

---

## Summary

**What the bot does:**
- Fetches signals from a website every 7 seconds
- Opens trades exactly as website signals say
- Closes trades when website signals say close
- Uses 10 rotating proxies to avoid rate limiting
- Logs everything for monitoring
- Force-closes losing trades if they exceed size limit

**What it does NOT do:**
- Analyze charts
- Use indicators
- Make intelligent decisions
- Filter "bad" signals
- Adjust stops
- Extend take profits
- Use trailing stops
- Do anything except read and execute website signals

**Key value prop:**
- Removes latency (you vs bot: bot is faster)
- 24/7 execution (works while you sleep)
- No emotions (always follows signal)
- Anti-detection (rotating proxies)
- Simple and transparent (you see all logs, understand exactly what's happening)

**Start with:**
1. Config (edit MT5 credentials)
2. Run on demo account (test 2+ weeks)
3. Log monitoring (tail -f bot.log)
4. Only go live after profitable demo period

**Good luck. Trade smart. Risk small. 🚀**

---

*Last updated: March 18, 2026*
*Version: 2.0 (Blind Follower with Proxy Rotation)*
