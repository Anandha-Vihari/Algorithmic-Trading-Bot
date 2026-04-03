# Windows Quick Start - Multi-Algo Trading Bot

## 🚀 Start All Bots (Single Command)

```batch
START_ALL_BOTS.bat
```

That's it! This single file will:
- ✅ Start Signal Fetcher (central signal hub)
- ✅ Start Bot 1 (Account 24727931 - Inverter)
- ✅ Start Bot 2 (Account 24727943 - Follower)
- ✅ Start Bot 3 (Account 24727961 - Follower)

Each bot runs in its own window for independent monitoring.

---

## 📋 What Happens When You Run START_ALL_BOTS.bat

1. **Validates** Python installation
2. **Starts** each process in sequence with brief delays
3. **Displays** rich startup summary showing:
   - Terminal identification (accounts)
   - File isolation paths
   - Running processes
   - Bot strategies
   - Usage instructions

4. **Opens** 4 separate windows:
   - `Signal Fetcher` window
   - `Bot 1 - Inverter` window
   - `Bot 2 - Follower` window
   - `Bot 3 - Follower` window

---

## 🎯 Terminal Isolation Verified

Each bot **automatically** connects to its unique terminal:

```
Bot 1 (Inverter)
├─ Account: 24727931
├─ Login:   MsBc!hO5
├─ File:    positions_store_bot_1.json
└─ Log:     bot_1.log

Bot 2 (Follower)
├─ Account: 24727943
├─ Login:   Uo4N$&Zw
├─ File:    positions_store_bot_2.json
└─ Log:     bot_2.log

Bot 3 (Follower)
├─ Account: 24727961
├─ Login:   Vr3Vn#2I
├─ File:    positions_store_bot_3.json
└─ Log:     bot_3.log
```

✅ **Zero confusion** - Each bot knows its terminal
✅ **No cross-contamination** - Positions stay in correct account
✅ **Fully isolated** - File state + terminal state synchronized

---

## 📊 Monitor Bots

Each bot window shows **real-time activity**:
- Signals fetched
- Trades opened/closed
- Position tracking
- Account balance & equity
- Error messages

**View logs anytime:**
```batch
type bot_1.log
type bot_2.log
type bot_3.log
type signal_fetcher.log
```

---

## 🛑 Stop All Bots

```batch
STOP_ALL_BOTS.bat
```

This gracefully stops all running processes:
- ✅ Closes windows properly (GRACEFUL shutdown first)
- ✅ Saves all positions to JSON files
- ✅ Persists trade history
- ✅ Verifies all processes stopped

---

## 📈 View Trading Analytics

After bots are running, open analytics dashboard:

```batch
python dashboard.py
```

Then browse to: `http://localhost:8501`

Dashboard shows:
- Equity curves per bot
- Win rate / PnL
- MFE/MAE analysis
- Trade performance metrics
- Real-time balance tracking

---

## 🔧 Configuration

All bot configurations are pre-set:

**config.py** (global)
```python
MT5_SERVER = "VantageInternational-Demo"
MT5_EXE = r"D:\MT5s\1\terminal64.exe"
```

**config_bot1.py** (Inverter)
```python
BOT_ID = 1
MT5_LOGIN = 24727931
MT5_PASSWORD = "MsBc!hO5"
TRADE_VOLUME = 0.01
USE_SIGNAL_INVERTER = True
STRATEGY = "mirror"
```

**config_bot2.py** (Follower)
```python
BOT_ID = 2
MT5_LOGIN = 24727943
MT5_PASSWORD = "Uo4N$&Zw"
TRADE_VOLUME = 0.02
USE_SIGNAL_INVERTER = False
STRATEGY = "mirror"
```

**config_bot3.py** (Follower)
```python
BOT_ID = 3
MT5_LOGIN = 24727961
MT5_PASSWORD = "Vr3Vn#2I"
TRADE_VOLUME = 0.015
USE_SIGNAL_INVERTER = False
STRATEGY = "mirror"
```

---

## ✅ Verification Checklist

After starting, verify:

```
☐ START_ALL_BOTS.bat runs without errors
☐ 4 windows open (Signal Fetcher + Bot 1/2/3)
☐ Each window shows initialization messages
☐ Log files created: bot_1.log, bot_2.log, bot_3.log, signal_fetcher.log
☐ Each window shows "[MT5] Connected to account XXXXXX"
☐ Bot 1 shows: "[MT5] Connected to account 24727931"
☐ Bot 2 shows: "[MT5] Connected to account 24727943"
☐ Bot 3 shows: "[MT5] Connected to account 24727961"
☐ No "login failed" errors
☐ No "terminal not found" errors
☐ Each bot starts fetching signals within 10 seconds
```

---

## 🚨 Troubleshooting

### Python not found
```
✗ ERROR: Python is not installed or not in PATH
```
**Fix:** Install Python 3.8+ from python.org, add to PATH

### MT5 errors
```
RuntimeError: MT5 login failed for account XXXXX
```
**Check:**
- MT5 terminal is installed at correct path
- Credentials are correct
- Network connection is active

### Position files locked
**Restart:** Run STOP_ALL_BOTS.bat, wait 5 seconds, run START_ALL_BOTS.bat

### Bots not trading
1. Check Signal Fetcher window - is it fetching signals?
2. Check bot logs: `type bot_1.log` etc
3. Verify MT5 has tradable symbols
4. Check signal age (must be < 30 minutes old)

---

## 📁 File Structure

```
/
├── START_ALL_BOTS.bat              ← Single launcher for all bots
├── STOP_ALL_BOTS.bat               ← Graceful shutdown
├── config.py                       ← Global settings
├── config_bot1.py                  ← Bot 1 config (24727931)
├── config_bot2.py                  ← Bot 2 config (24727943)
├── config_bot3.py                  ← Bot 3 config (24727961)
├── main.py                         ← Bot execution engine
├── signal_fetcher.py               ← Central signal publisher
├── trader.py                       ← MT5 order execution
├── strategy.py                     ← Signal transformation
├── bot_1.log                       ← Bot 1 real-time log
├── bot_2.log                       ← Bot 2 real-time log
├── bot_3.log                       ← Bot 3 real-time log
├── signal_fetcher.log              ← Signal fetcher log
├── positions_store_bot_1.json      ← Bot 1 open positions
├── positions_store_bot_2.json      ← Bot 2 open positions
├── positions_store_bot_3.json      ← Bot 3 open positions
├── trades_history.jsonl            ← All trades (for analytics)
└── [other system files...]
```

---

## 🌟 Key Features

### ✅ Terminal Isolation
- Each bot connects to unique MT5 account
- No credential sharing
- Complete trade segregation
- Verified at startup

### ✅ File Isolation
- Per-bot position tracking
- Per-bot log files
- No file contention
- Atomic writes for safety

### ✅ Concurrent Execution
- All 3 bots run simultaneously
- Independent signal processing
- Parallel MT5 connections
- No race conditions

### ✅ Crash Safety
- Automatic position recovery on restart
- State persisted to JSON
- Atomic file operations
- No data loss on failure

### ✅ Rich Monitoring
- Real-time windows per bot
- Log files for analysis
- Dashboard for analytics
- Signal tracking included

---

## 🎓 How It Works

```
START_ALL_BOTS.bat
    ├─→ signal_fetcher.py
    │   ├─ Scrapes website every 10s
    │   ├─ Publishes to signals.json
    │   └─ Logs to signal_fetcher.log
    │
    ├─→ main.py --bot-id 1
    │   ├─ Loads config_bot1.py (24727931)
    │   ├─ Connects to MT5 account 24727931
    │   ├─ Reads signals.json
    │   ├─ Applies inverter strategy
    │   ├─ Opens/closes trades
    │   ├─ Logs to bot_1.log
    │   └─ Saves state to positions_store_bot_1.json
    │
    ├─→ main.py --bot-id 2
    │   ├─ Loads config_bot2.py (24727943)
    │   ├─ Connects to MT5 account 24727943
    │   ├─ Reads signals.json
    │   ├─ Applies mirror strategy
    │   ├─ Opens/closes trades
    │   ├─ Logs to bot_2.log
    │   └─ Saves state to positions_store_bot_2.json
    │
    └─→ main.py --bot-id 3
        ├─ Loads config_bot3.py (24727961)
        ├─ Connects to MT5 account 24727961
        ├─ Reads signals.json
        ├─ Applies mirror strategy
        ├─ Opens/closes trades
        ├─ Logs to bot_3.log
        └─ Saves state to positions_store_bot_3.json
```

---

## 💡 Pro Tips

1. **Multiple Monitors?** Arrange bot windows side-by-side for easy monitoring

2. **Automated Backups?** Copy log files/JSON states regularly

3. **Performance Tuning?** Adjust TRADE_VOLUME in config_botX.py

4. **Testing First?** Run with small TRADE_VOLUME before production

5. **24/7 Running?** Run on dedicated Windows machine or VM

---

## 📞 Support

For issues:
1. Check bot log files: `type bot_X.log | tail -50`
2. Verify credentials in config files
3. Confirm MT5 installation and connectivity
4. Review SYSTEM_ARCHITECTURE.md for detailed architecture

---

## ✨ You're Ready!

```bash
START_ALL_BOTS.bat
```

All bots will start automatically with proper terminal isolation.

**Enjoy multi-algo trading!** 🚀
