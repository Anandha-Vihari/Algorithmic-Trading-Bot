# Algorithmic Trading Bot — Blind Follower with Proxy Rotation

A fully autonomous forex trading bot that **blindly follows website signals** with **proxy rotation** to avoid rate limiting. No intelligence filtering—just open/close trades exactly as the website signals. Built for MetaTrader 5.

---

## 🎯 What It Does

```
Website Signal: "BUY EURUSD @ 1.08500, TP 1.09000, SL 1.08000"
                    ↓
Bot (via proxy): Fetches signal every 7 seconds
                    ↓
Bot: "ACTIVE status? YES → Open BUY trade with those exact SL/TP"
                    ↓
Website: "CLOSE EURUSD"
                    ↓
Bot: "YES → Close trade immediately"
```

**Zero intelligence. Zero filters. Just obey.**

---

## 📋 Quick Start

### 1. Prerequisites

```bash
pip install requests beautifulsoup4 MetaTrader5
```

### 2. Configure `config.py`

```python
URL = "http://massyart.com/ringsignal/"

# Proxies (10 rotating free proxies to avoid rate limit)
PROXY_API_URL = "https://api.proxyscrape.com/v4/free-proxy-list/get?request=display_proxies&proxy_format=protocolipport&format=text"
PROXY_CACHE_SECONDS = 300
PROXY_ROTATION_STRATEGY = "round_robin"

# Timing
SIGNAL_INTERVAL = 7      # Check website every 7 seconds

# Trading
TRADE_VOLUME = 0.01      # Lot size
MAX_POSITIONS = 10       # Max concurrent positions

# Safety
DOLLAR_STOP_LOSS = 1.50  # Emergency close if loss > $1.50

# MT5 Account
MT5_LOGIN = YOUR_LOGIN
MT5_PASSWORD = "YOUR_PASSWORD"
MT5_SERVER = "YOUR_SERVER"
MT5_EXE = r"C:\path\to\terminal64.exe"
```

### 3. Run

```bash
python main.py
```

Logs go to `bot.log`. Check it for signal events.

---

## 🏗️ Architecture

### Single-Thread Design

Simple and clear: just one signal loop.

```
Signal Thread (every 7 seconds)
├─ Fetch signals from website (via proxy rotation)
├─ Parse HTML → extract [pair, side, open, tp, sl, status]
├─ Process ACTIVE signals → open_trade()
├─ Process CLOSE signals → close_trade()
└─ Show status
```

### Signal Processing

```
For each ACTIVE signal:
  1. Not already processed? → YES (check state)
  2. Below position cap (MAX_POSITIONS)? → YES
  3. Symbol available in MT5? → YES
  4. Order accepted by broker? → YES
  5. OPEN TRADE

For each CLOSE signal:
  1. Position exists for this pair? → YES
  2. CLOSE TRADE
```

---

## 🌐 Proxy System

### Why Proxies?

Website rate-limit: ~1 request per 7 seconds = ~515 requests/hour.
Single IP gets blocked.
**Solution**: 10 rotating proxies from ProxyScrape API.

### How It Works

1. **Fetch Proxies** (every 5 minutes)
   - ProxyScrape API returns 10+ free proxies
   - Cache for 5 minutes
   - Auto-refresh

2. **Rotate on Each Request**
   - Round-robin through 10 proxies
   - Failed proxy gets 60-second timeout (3 failures)
   - Automatic retry with next proxy

3. **Fallback**
   - If all fail → skip cycle
   - Retry next cycle (7 seconds later)

**Why HTTP not HTTPS?**
- Free proxies don't support HTTPS CONNECT tunneling
- HTTP works fine (no credentials sent, just signals)

---

## 📊 Signal Format

```python
{
  'pair': 'EURUSD',
  'side': 'BUY',           # Follow this direction (not reversed)
  'open': 1.08500,         # Entry price reference
  'tp': 1.09000,           # Take profit target (use as-is)
  'sl': 1.08000,           # Stop loss (use as-is)
  'frame': 'short',        # 15/30min or 1/4hr
  'status': 'ACTIVE' or 'CLOSE',
  'time': datetime(...)
}
```

---

## ⚙️ Configuration

### Essential Parameters

```python
SIGNAL_INTERVAL = 7
  # Check website every N seconds
  # Increase to 10-15 if getting rate-limited (403 errors)

TRADE_VOLUME = 0.01
  # 0.01 = 1 micro-lot ≈ $1 per pip
  # Decrease for safer testing

MAX_POSITIONS = 10
  # Max concurrent positions
  # Reduce to 5 if too much trading action

DOLLAR_STOP_LOSS = 1.50
  # Emergency close if loss exceeds this
  # Tighten to $0.60 for safer trading
```

### Proxy Parameters

```python
PROXY_ROTATION_STRATEGY = "round_robin"
  # "round_robin": cycle through proxies 1→2→3→...→10→1
  # "random": pick random proxy each time

PROXY_CACHE_SECONDS = 300
  # Refresh proxy list every 5 minutes
  # Increase to 600 if API is flaky
```

---

## 📝 Logs & Output

### bot.log (Signal Events)

```
[14:32:00] SIGNAL: EURUSD BUY @ 1.08500 SL:1.08000 TP:1.09000
  → OPENED ✓
[14:32:05] CLOSE: EURUSD (website signal)
  → CLOSED ✓
```

### Console (every cycle)

```
[14:32:05] Status: 1 opened, 1 closed
  Open positions: 1
    [EURUSD] BUY @ 1.08523 | Profit: +$0.45
  Account: Balance $10000.00 | Equity $10000.45
```

---

## 🔧 Troubleshooting

### Proxies Not Working

```
Problem: "PROXY: all retries exhausted, returning None"

Solutions:
1. Increase SIGNAL_INTERVAL (give proxies time to recover)
2. Check internet connection
3. Verify ProxyScrape API is responding:
   curl https://api.proxyscrape.com/v4/free-proxy-list/...
```

### No Trades Opening

```
Problem: Signals appear in log but no trades open

Debug:
1. Check bot.log for [SKIP] messages
2. Common reasons:
   - Symbol not available in MT5
   - MT5 not connected
   - Order rejected by broker (invalid stops, slippage)
   - Already at MAX_POSITIONS
```

### Losing Money

```
Verify:
1. Website signals are profitable
2. MT5 SL/TP match website exactly
3. Position cap not preventing good trades
4. Proxy rotation actually working (check logs)
```

---

## 📁 Files

| File | Purpose |
|------|---------|
| `main.py` | Signal loop, threading, basic state tracking |
| `scraper.py` | Website fetch + proxy rotation (10 proxies) |
| `parser.py` | HTML parsing (BeautifulSoup) |
| `trader.py` | MT5 API (open_trade, close_trade) |
| `state.py` | Processed signal tracking (prevent duplicates) |
| `config.py` | Configuration (URL, proxies, MT5 credentials) |
| `bot.log` | Signal event log |

---

## ⚠️ Disclaimers

- **Risk**: Automated trading can lose money. Start small.
- **Testing**: Use demo account for at least 1 week before live.
- **Signals**: Bot is only as good as website signals. Garbage in = garbage out.
- **Monitoring**: Don't leave unattended for days.
- **Broker**: Some brokers restrict algorithmic trading—check terms.

---

## 🚀 Why This Approach?

1. **Simple** - Easy to debug and monitor
2. **Reliable** - No complex logic = no unexpected bugs
3. **Fast** - 7-second signal detection (was 66s)
4. **Robust** - Proxy rotation avoids IP bans
5. **Transparent** - You see exactly what's happening in logs

**Trade what the website says, nothing more.**

---

## License

Educational use only. Trade at your own risk. 🚀
