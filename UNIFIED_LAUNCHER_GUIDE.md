# Unified Bot Launcher - Single Command Start

## Quick Start

### **One Command - Start Everything**

```bash
# Linux/Mac
python start_all_bots.py

# Windows
start_all_bots_windows.bat
```

That's it! All 4 processes start automatically:
- Signal Fetcher (central hub)
- Bot 1 (Inverter)
- Bot 2 (Follower)
- Bot 3 (Follower)

---

## Files Overview

### 1️⃣ `start_all_bots.py` (Main Launcher - Cross-platform)

**Purpose:** Start all bots + signal fetcher in uniform launcher

**Features:**
- ✅ Starts all 4 processes (signal fetcher + 3 bots)
- ✅ Managed process tracking
- ✅ Automatic restart on crash
- ✅ Graceful shutdown (Ctrl+C)
- ✅ Colored terminal output
- ✅ Real-time process monitoring
- ✅ Test mode (60s, no fetcher)

**Usage:**

```bash
# Normal mode (production)
python start_all_bots.py

# Test mode (run for 60 seconds, no signal fetcher)
python start_all_bots.py --test

# Skip signal fetcher
python start_all_bots.py --no-fetcher
```

**What it shows:**
```
══════════════════════════════════════════════════════════════════
            MULTI-ALGO TRADING BOT - UNIFIED LAUNCHER
══════════════════════════════════════════════════════════════════

Configuration:

  Mode:           PRODUCTION
  Signal Fetcher: ENABLED
  Bot 1:          Inverter Strategy
  Bot 2:          Follower Strategy
  Bot 3:          Follower Strategy

[14:23:45] SIGNAL FETCHER: STARTING - Command: python signal_fetcher.py
[14:23:45] SIGNAL FETCHER: RUNNING - PID: 12345
[14:23:47] BOT 1 (INVERTER): STARTING - Command: python main.py --bot-id 1
[14:23:47] BOT 1 (INVERTER): RUNNING - PID: 12346
[14:23:48] BOT 2 (FOLLOWER): STARTING - Command: python main.py --bot-id 2
[14:23:48] BOT 2 (FOLLOWER): RUNNING - PID: 12347
[14:23:49] BOT 3 (FOLLOWER): STARTING - Command: python main.py --bot-id 3
[14:23:49] BOT 3 (FOLLOWER): RUNNING - PID: 12348

✓ All bots started successfully!

Press Ctrl+C to stop all bots

Running Processes:

  ✓ SIGNAL FETCHER               PID: 12345      Uptime: 4.2s
  ✓ BOT 1 (INVERTER)             PID: 12346      Uptime: 2.8s
  ✓ BOT 2 (FOLLOWER)             PID: 12347      Uptime: 1.5s
  ✓ BOT 3 (FOLLOWER)             PID: 12348      Uptime: 0.2s
```

### 2️⃣ `start_all_bots_windows.bat` (Windows Batch Launcher)

**Purpose:** Windows users can double-click to start everything

**Features:**
- ✅ Opens separate terminal windows for each process
- ✅ Easy to see each bot's output independently
- ✅ Professional layout
- ✅ Automatic 2-second delays between starts

**Usage:**

```bash
# Double-click the file, or run from command prompt:
start_all_bots_windows.bat
```

**What it does:**
```
╔════════════════════════════════════════════════════════════════════╗
║       MULTI-ALGO TRADING BOT - WINDOWS LAUNCHER                   ║
╚════════════════════════════════════════════════════════════════════╝

Starting all bots...

[1/4] Starting Signal Fetcher...          (opens Window 1)
[2/4] Starting Bot 1 (Inverter)...        (opens Window 2)
[3/4] Starting Bot 2 (Follower)...        (opens Window 3)
[4/4] Starting Bot 3 (Follower)...        (opens Window 4)

✓ All bots started in background windows!

Running Processes:
 • Signal Fetcher: signal_fetcher.log
 • Bot 1 (Inverter): bot_1.log
 • Bot 2 (Follower): bot_2.log
 • Bot 3 (Follower): bot_3.log
```

### 3️⃣ `stop_all_bots.bat` (Windows Batch Stopper - Enhanced)

**Purpose:** Gracefully stop all bots on Windows

**Usage:**

```bash
stop_all_bots.bat
```

### 4️⃣ `stop_all_bots_linux.py` (Linux/Mac Stopper)

**Purpose:** Gracefully stop all bots on Linux/Mac

**Features:**
- ✅ Graceful shutdown (SIGTERM)
- ✅ Force kill option (SIGKILL)
- ✅ Process verification
- ✅ Color-coded output

**Usage:**

```bash
# Graceful shutdown
python stop_all_bots_linux.py

# Force kill (if graceful doesn't work)
python stop_all_bots_linux.py --force
```

---

## Terminal Identification (After Start)

When all bots are running:

```
Bot 1 (from bot_1.log):
  [MT5] Connected to account 24727931 (BOT-INVERTER)
  [INIT] Signal interval: 7s | Trade volume: 0.01
  [RECOVERY] Positions recovered: 0 keys

Bot 2 (from bot_2.log):
  [MT5] Connected to account 24727943 (BOT-FOLLOWER)
  [INIT] Signal interval: 7s | Trade volume: 0.02
  [RECOVERY] Positions recovered: 0 keys

Bot 3 (from bot_3.log):
  [MT5] Connected to account 24727961 (BOT-FOLLOWER)
  [INIT] Signal interval: 7s | Trade volume: 0.015
  [RECOVERY] Positions recovered: 0 keys

Signal Fetcher (from signal_fetcher.log):
  [FETCHER] Publishing signals every 10 seconds
  [FETCHER] Cycle 1: Fetched 5 signals...
```

---

## Platform-Specific Instructions

### **Linux / macOS / WSL**

```bash
# Start all bots
python start_all_bots.py

# Watch in real-time
# - Each process logged to: bot_1.log, bot_2.log, bot_3.log, signal_fetcher.log

# Stop all bots (from another terminal)
python stop_all_bots_linux.py
```

### **Windows (Native)**

```bash
# Method 1: Double-click
→ Double-click start_all_bots_windows.bat

# Method 2: Command Prompt
cmd> start_all_bots_windows.bat

# Method 3: PowerShell
PS> .\start_all_bots_windows.bat

# Stop all (optional - windows close automatically)
→ Double-click stop_all_bots.bat
  OR
→ Close each terminal window
```

### **Windows (WSL - Windows Subsystem for Linux)**

```bash
wsl $ python start_all_bots.py
```

---

## Process Architecture

```
start_all_bots.py (main orchestrator)
│
├─→ signal_fetcher.py (signals.json publisher)
│   └─ Logs: signal_fetcher.log
│   └─ Account: SHARED (central)
│
├─→ main.py --bot-id 1 (BOT 1 - Inverter)
│   ├─ Logs: bot_1.log
│   ├─ Account: 24727931 (unique)
│   ├─ Files: positions_store_bot_1.json, trailing_stop_meta_bot_1.json
│   └─ Strategy: Mirror (13:00-17:00 IST)
│
├─→ main.py --bot-id 2 (BOT 2 - Follower)
│   ├─ Logs: bot_2.log
│   ├─ Account: 24727943 (unique)
│   ├─ Files: positions_store_bot_2.json, trailing_stop_meta_bot_2.json
│   └─ Strategy: Mirror
│
└─→ main.py --bot-id 3 (BOT 3 - Follower)
    ├─ Logs: bot_3.log
    ├─ Account: 24727961 (unique)
    ├─ Files: positions_store_bot_3.json, trailing_stop_meta_bot_3.json
    └─ Strategy: Mirror
```

**Each process is independent:**
- ✅ Separate MT5 session
- ✅ Separate file state
- ✅ Separate logging
- ✅ Can be killed individually without affecting others

---

## Monitoring While Running

### **Check Log Files**

```bash
# Watch Bot 1 in real-time
tail -f bot_1.log

# Watch Bot 2
tail -f bot_2.log

# Watch Signal Fetcher
tail -f signal_fetcher.log

# Watch all at once (in separate terminals)
watch -n 1 'tail -20 bot_1.log; echo "---"; tail -20 bot_2.log; echo "---"; tail -20 bot_3.log'
```

### **Check Processes**

```bash
# Linux/Mac: List all bot processes
ps aux | grep -E "main.py|signal_fetcher"

# Windows: Use Task Manager
# → Look for python.exe instances
```

### **Check Position Files**

```bash
# View all positions across bots
cat positions_store_bot_*.json | jq '.'

# Watch Bot 1's positions in real-time
watch -n 2 'cat positions_store_bot_1.json | jq .'
```

---

## Error Handling

### **If a Bot Crashes**

**Linux/Mac with start_all_bots.py:**
- ✅ Auto-restarts automatically (built-in restart logic)
- ✅ Logs crash details

**Windows with .bat files:**
- ⚠️ You'll see "Command ended" in that window
- → Either restart manually or use Python launcher

**Solution:** Use `start_all_bots.py` for auto-restart capability

### **If Signal Fetcher Crashes**

**Impact:** Bots will continue running with stale signals
- Logs will show: `[SIGNAL] No new signals received`
- Trades won't open until fetcher restarts

**Solution:**
```bash
# Restart individually
python signal_fetcher.py

# OR restart everything
python start_all_bots.py
```

### **If Everything Freezes**

```bash
# Option 1: Graceful shutdown
python stop_all_bots_linux.py

# Option 2: Force kill (last resort)
python stop_all_bots_linux.py --force

# Option 3: Manual (Linux/Mac)
pkill -f "main.py"
pkill -f "signal_fetcher"

# Option 4: Manual (Windows)
taskkill /F /IM python.exe
```

---

## Production Checklist

Before starting:

- ✅ Config files updated with real MT5 credentials
- ✅ `config_bot1.py` has login 24727931
- ✅ `config_bot2.py` has login 24727943
- ✅ `config_bot3.py` has login 24727961
- ✅ Signal fetcher URL is correct in `config.py`
- ✅ MT5 terminals installed and executable paths correct

Start production:

```bash
python start_all_bots.py
```

Monitor:

```bash
# Terminal 2: Watch logs
tail -f bot_1.log bot_2.log bot_3.log signal_fetcher.log

# Terminal 3: Check status periodically
watch -n 5 'ls -lh *.log positions_store_bot_*.json'
```

Stop (when ready):

```bash
# From original terminal: Press Ctrl+C
# OR from another terminal:
python stop_all_bots_linux.py
```

---

## File Summary

| File | Purpose | Platform | Usage |
|------|---------|----------|-------|
| `start_all_bots.py` | Main unified launcher | Linux/Mac/WSL | `python start_all_bots.py` |
| `start_all_bots_windows.bat` | Windows GUI launcher | Windows | Double-click or `start_all_bots_windows.bat` |
| `stop_all_bots.bat` | Windows stopper | Windows | `stop_all_bots.bat` |
| `stop_all_bots_linux.py` | Linux/Mac stopper | Linux/Mac/WSL | `python stop_all_bots_linux.py` |

---

## Summary - One Click, All Bots Running

```bash
# Before: Start each bot in 4 separate terminals
Terminal 1> python signal_fetcher.py
Terminal 2> python main.py --bot-id 1
Terminal 3> python main.py --bot-id 2
Terminal 4> python main.py --bot-id 3

# After: ONE command
Terminal 1> python start_all_bots.py

✅ Done! All 4 processes running, each in isolated session
✅ Each bot has its own MT5 account (24727931, 24727943, 24727961)
✅ Each bot has its own files (bot_1.log, bot_2.log, bot_3.log)
✅ Each bot logs independently to bot_X.log
✅ Central signal fetcher runs continuously
✅ Press Ctrl+C to stop everything gracefully
```
