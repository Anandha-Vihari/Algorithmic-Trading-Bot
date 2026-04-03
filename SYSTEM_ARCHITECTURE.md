# Multi-Bot Trading System: Complete Architecture & Workflow

**Version:** 2.4 (Production-Grade with V3 Integration)
**Status:** Fully operational, documented for maintainability
**Date:** 2026-04-03

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [High-Level Architecture](#high-level-architecture)
3. [Bot-Level Workflow](#bot-level-workflow)
4. [Main Loop Flow (Detailed)](#main-loop-flow-detailed)
5. [Data Flow](#data-flow)
6. [File System Design](#file-system-design)
7. [Strategy System](#strategy-system)
8. [Execution Engine: Counter Diff Logic](#execution-engine-counter-diff-logic)
9. [MT5 Integration](#mt5-integration)
10. [Risk Management](#risk-management)
11. [Analytics System](#analytics-system)
12. [Multi-Bot Architecture](#multi-bot-architecture)
13. [Failure Handling](#failure-handling)
14. [System Guarantees](#system-guarantees)
15. [Known Limitations](#known-limitations)

---

## Executive Summary

The **Multi-Bot Trading System** is a production-grade algorithmic trading platform that:

- **Runs 3 independent bot instances** (bot1, bot2, bot3) with separate MT5 accounts
- **Fetches signals** from a website, transforms them per strategy, and executes trades
- **Guarantees deterministic behavior** through content-hash deduplication (4 layers)
- **Maintains complete bot isolation** with per-bot file storage and atomic operations
- **Implements sophisticated risk management** via virtual SL, trailing stops, and max loss
- **Tracks trade analytics** with MFE/MAE and persistent history

**Core Principle:** The website is the single source of truth. The system maintains bots' trade state = website state, never opening trades the bot didn't signal, never closing trades prematurely.

---

## High-Level Architecture

### Component Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                    CENTRAL COMPONENTS                           │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  scraper.py          parser.py              signal_fetcher.py  │
│  ├─ Proxy rotation    ├─ HTML parsing       ├─ IPC via         │
│  └─ Retry logic       └─ Signal extraction      signals.json    │
│                                                                 │
└──────────────────────────┬──────────────────────────────────────┘
                           │ signals.json (IPC shared state)
                           ↓
┌──────────────────────────────────────────────────────────────────┐
│  BOT 1 INSTANCE (bot_1.log, positions_store_bot_1.json, ...)    │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ MAIN LOOP (every 7 seconds)                             │   │
│  ├─────────────────────────────────────────────────────────┤   │
│  │                                                          │   │
│  │  1. Read signals (signal_reader)                        │   │
│  │     ├─ Read signals.json (shared IPC)                   │   │
│  │     └─ Filter signals_to_open / signals_to_manage       │   │
│  │                                                          │   │
│  │  2. Apply strategy (strategy.transform_signal())        │   │
│  │     ├─ Mirror: Pass through unchanged                  │   │
│  │     ├─ Reverse: Invert side + swap TP/SL               │   │
│  │     └─ Time-Based: Decide mode from signal.time IST     │   │
│  │                                                          │   │
│  │  3. Build execution keys                                │   │
│  │     └─ key = (pair, side, tp, sl)                       │   │
│  │                                                          │   │
│  │  4. Counter diff (STATE DIFFERENCER)                    │   │
│  │     ├─ prev_keys vs curr_keys                           │   │
│  │     ├─ opened = new signals (not in positions)          │   │
│  │     └─ closed = gone signals (not in curr_keys)         │   │
│  │                                                          │   │
│  │  5. Execute trades (TRADER via MT5)                     │   │
│  │     ├─ For each opened: open_trade()                    │   │
│  │     └─ For each closed: close_position_by_ticket()      │   │
│  │                                                          │   │
│  │  6. Update state                                        │   │
│  │     ├─ Update position_store                            │   │
│  │     ├─ Update trailing stop                             │   │
│  │     ├─ Update MFE/MAE tracker                           │   │
│  │     └─ Save all atomically                              │   │
│  │                                                          │   │
│  │  7. Risk management                                     │   │
│  │     ├─ Virtual SL: Spread-aware SL management           │   │
│  │     ├─ Trailing Stop: Phase-based SL tightening         │   │
│  │     └─ Max Loss: Close positions by max loss            │   │
│  │                                                          │   │
│  │  8. Logging & analytics                                 │   │
│  │     ├─ Operational logs (bot_1.log)                     │   │
│  │     └─ Trade history (appended to trades_history.jsonl) │   │
│  │                                                          │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                  │
│  STATE MANAGERS:                                                 │
│  ├─ Config (config_bot_1.py)         - Bot-specific setup       │
│  ├─ Positions (positions_store_bot_1.json) - Open trades        │
│  ├─ Trailing Stop (trailing_stop_meta_bot_1.json) - SL stages   │
│  └─ Virtual SL (in-memory, GC'd after signal closes)            │
│                                                                  │
│  MT5 CONNECTION: Login 24446623 → Terminal /MT5/bot_1           │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

### Data Flow Overview

```
Website
  ↓
scraper.py (fetch HTML via proxies)
  ↓
parser.py (extract structured signals)
  ↓
signal_fetcher.py (publish to signals.json)
  ↓
signals.json (IPC: shared signal state)
  ├─ version: int (incremented on each update)
  ├─ hash: str (SHA256 of signal content)
  ├─ signals: list (actual trading signals)
  └─ status: "OK" or "ERROR"
  ↓
[Bot 1, Bot 2, Bot 3 independently read signals.json]
  ↓
signal_reader.py (read + filter for this bot)
  ├─ Validate hash (content dedup layer 1)
  ├─ Filter by signal age (< 30 min)
  └─ Return: signals_to_open, signals_to_manage
  ↓
strategy.transform_signal() (deterministic transformation)
  ↓
STATE DIFFERENCER (Counter diff)
  ├─ Compute opened = new signals
  └─ Compute closed = gone signals
  ↓
TRADER (MT5 execution)
  ├─ open_trade() for opened signals
  └─ close_position_by_ticket() for closed signals
  ↓
POSITION STORE (atomic JSON update)
  ├─ Add/remove tickets
  └─ Track position info
  ↓
RISK MANAGERS (passive, monitoring)
  ├─ Virtual SL: spread-aware SL management
  ├─ Trailing Stop: phase-based SL tightening
  └─ Max Loss: close by cumulative loss
  ↓
ANALYTICS (lightweight tracking)
  ├─ MFE/MAE per ticket
  ├─ Trade history JSONL
  └─ Dashboard data
```

---

## Bot-Level Workflow

### Initialization Phase (Startup)

When a bot starts, it performs the following initialization steps:

```
1. CLI ARGUMENT PARSING
   ├─ Parse --bot-id argument (1, 2, or 3)
   └─ Optional --no-mt5 flag for testing

2. STDOUT REDIRECTION (BEFORE OTHER IMPORTS)
   ├─ Redirect sys.stdout to bot_N.log
   └─ Ensures all output captured to per-bot log

3. CONFIG LOADING (NO sys.modules hacks)
   ├─ Load ConfigManager(BOT_ID)
   ├─ Read config_bot_N.py
   └─ Validate required fields:
      ├─ BOT_ID, BOT_NAME, TRADE_VOLUME
      ├─ MT5_LOGIN, MT5_PASSWORD, MT5_SERVER, MT5_EXE
      ├─ STRATEGY (mirror/reverse/time_based)
      └─ USE_SIGNAL_INVERTER, FOLLOW_HOURS_IST_START, FOLLOW_HOURS_IST_END

4. STRATEGY INITIALIZATION
   ├─ Get strategy from config
   ├─ Create strategy instance
   └─ Extract risk flags:
      ├─ should_apply_trailing()
      └─ should_apply_max_loss()

5. MT5 INITIALIZATION
   ├─ Check if MT5 terminal running
   ├─ If not: launch MT5_EXE with subprocess
   ├─ Call mt5.initialize()
   ├─ Call mt5.login(MT5_LOGIN, MT5_PASSWORD, MT5_SERVER)
   └─ Verify connection successful

6. STATE RECOVERY (FROM DISK)
   ├─ Load positions_store_bot_N.json (position state)
   ├─ Load trailing_stop_meta_bot_N.json (trailing stop state)
   ├─ Load processed_signals_bot_N.json (signal dedup layer 4)
   └─ Validate consistency (positions make sense)

7. COMPONENT INITIALIZATION
   ├─ OperationalSafety (retry/monitoring logic)
   ├─ VirtualSLManager (spread-aware SL tracking)
   ├─ TrailingStopManager (phase-based SL)
   ├─ SignalReader (signal filtering + format normalization)
   ├─ V3ExecutionFlow (execution-aware logic)
   └─ MFE/MAE Tracker (trade excursion tracking, in-memory dict)

8. READY FOR MAIN LOOP
   └─ Print startup banner with all config + state info
```

### File Isolation Design

Each bot uses **exclusively bot-specific file names** to prevent concurrent access conflicts:

```
BOT 1 FILES:
├─ bot_1.log                          (output log)
├─ positions_store_bot_1.json         (open trade tracking)
├─ trailing_stop_meta_bot_1.json      (SL stage tracking)
└─ processed_signals_bot_1.json       (dedup layer 4, 24h history)

BOT 2 FILES:
├─ bot_2.log
├─ positions_store_bot_2.json
├─ trailing_stop_meta_bot_2.json
└─ processed_signals_bot_2.json

BOT 3 FILES:
├─ bot_3.log
├─ positions_store_bot_3.json
├─ trailing_stop_meta_bot_3.json
└─ processed_signals_bot_3.json

SHARED (IPC):
├─ signals.json                       (published by signal_fetcher, read by all bots)
└─ signals_backup.json                (fallback if signals.json corrupted)

ANALYTICS (SHARED):
└─ trades_history.jsonl               (append-only, one trade per line)
```

**Why per-bot files prevent corruption:**
- Each bot only reads/writes its own files
- No simultaneous writes to same file (impossible)
- Race condition: impossible (file is locked by one bot only)
- Atomic operations ensure consistency on crash

**MT5 Account Isolation:**

```
Bot 1 ←→ MT5 Terminal /MT5/bot_1 ←→ Account 24446623 (VantageInternational-Demo)
Bot 2 ←→ MT5 Terminal /MT5/bot_2 ←→ Account 24446624 (VantageInternational-Demo)
Bot 3 ←→ MT5 Terminal /MT5/bot_3 ←→ Account 24446625 (VantageInternational-Demo)
```

Each bot connects to a unique MT5 terminal path and login account, ensuring complete isolation at the broker level.

---

## Main Loop Flow (Detailed)

The main loop runs every ~7 seconds (SIGNAL_INTERVAL from config). Here is the **exact step-by-step flow**:

### Step 1: Fetch Signals

**Code Location:** `main.py` lines ~327+, `signal_reader.py`

```
1a. Read signals.json (central IPC file)
    ├─ SignalReader.read_signals_safe() attempts read
    │  ├─ Try primary: signals.json
    │  ├─ Fallback to backup: signals_backup.json if primary fails
    │  └─ Retry logic: up to 3 attempts with exponential backoff
    └─ Extract payload: version, hash, timestamp, signals list

1b. Validate signal quality
    ├─ Check hash field exists (if empty = ERROR status from fetcher)
    ├─ Validate signals are properly formatted
    └─ Skip cycle if validation fails

1c. Filter signals by age
    ├─ MAX_SIGNAL_AGE = 1800 seconds (30 minutes)
    ├─ For each signal:
    │  ├─ Calculate age = now - signal.time
    │  └─ Keep if age < 30 minutes (fresh)
    └─ ACTIVE signals only (ignore CLOSE signals from website)

1d. Categorize signals into arrays
    ├─ signals_to_open: fresh ACTIVE signals (< 30 min old)
    │  └─ These are NEW signals we should open trades on
    ├─ signals_to_manage: ALL ACTIVE signals (any age)
    │  └─ These define what should be open (for closing stale trades)
    └─ Output:
       └─ Example: signals_to_open=[EURUSD BUY, GBPUSD SELL]
                   signals_to_manage=[EURUSD BUY, GBPUSD SELL, USDJPY BUY from yesterday]
```

**Data Structure (Signal object):**

```python
Signal {
    "pair": "EURUSD",           # Trading pair
    "side": "BUY" or "SELL",    # Direction
    "open_price": 1.0800,       # Entry price from website
    "tp": 1.0850,               # Take profit level
    "sl": 1.0750,               # Stop loss level
    "time": datetime(UTC),      # CRITICAL: Signal publish time (UTC)
    "frame": "short" or "long", # Timeframe on website
    "status": "ACTIVE",         # ACTIVE or CLOSE (only accept ACTIVE)
    "close_price": None,        # (only if CLOSE)
    "close_reason": None,       # (only if CLOSE)
}
```

#### Deduplication Layer 1: Content Hash Check

```
1e. Check content hash (LAYER 1 DEDUP: content identity)
    ├─ This prevents re-opening SAME signal multiple times
    ├─ If hash == last_hash_seen:
    │  └─ Print "[SKIP] Hash unchanged" → entire cycle skipped
    └─ If hash != last_hash_seen:
       └─ This is NEW content, proceed with processing

WHY THIS WORKS:
- hash = SHA256(signal_content)
- If website publishes {EURUSD BUY 1.0800, GBPUSD SELL 1.2600}
- And bot opens both
- And signal_fetcher publishes same content again
- hash will be identical → bot skips cycle → no duplicate opens
```

---

### Step 2: Apply Strategy Transformation

**Code Location:** `strategy.py`, called from `main.py`

```
2a. For each signal in signals_to_open, apply strategy
    └─ transformed_signal = strategy.transform_signal(signal)

    Example 1 (Mirror Strategy):
    ├─ Input:  EURUSD BUY @ 1.0800, TP=1.0850, SL=1.0750
    └─ Output: EURUSD BUY @ 1.0800, TP=1.0850, SL=1.0750 (NO CHANGE)

    Example 2 (Reverse Strategy):
    ├─ Input:  EURUSD BUY @ 1.0800, TP=1.0850, SL=1.0750
    └─ Output: EURUSD SELL @ 1.0800, TP=1.0750, SL=1.0850 (SIDE INVERTED, TP/SL SWAPPED)

    Example 3 (Time-Based Strategy):
    ├─ Check signal.time hour in IST timezone
    ├─ If 16:00-20:00 IST (4 PM - 8 PM): MIRROR (use as-is)
    └─ Otherwise: REVERSE (invert + swap)

2b. Store transformation result
    ├─ transformed_signal is a COPY of signal
    └─ Original signal is NEVER mutated (immutable design)
```

**Why Signal Time (not wall-clock time)?**

- Signal time is **deterministic** (baked into signal import)
- Wall-clock time is **non-deterministic** (changes every second)
- If bot restarts mid-trade, same signal always produces same transformation
- Ensures trades never flip from MIRROR to REVERSE mid-cycle

---

### Step 3: Build Execution Keys

**Code Location:** `main.py` lines ~370+, `signal_manager.py`

```
3a. For each transformed signal, create execution key
    ├─ key = SignalKey.build(pair, side, tp, sl)
    └─ Example: ("EURUSD", "BUY", 1.085, 1.075)

3b. Key normalization (rounding)
    ├─ TP and SL rounded to 3 decimal places
    ├─ Precision is configurable per symbol if needed
    └─ Example: 1.08500 → 1.085

3c. Build two Counter objects:
    │
    ├─ curr_counter = Counter(current_signal_keys)
    │  └─ How many of each key type in TODAY'S active signals
    │     Example: {("EURUSD", "BUY", 1.085, 1.075): 1,
    │              ("GBPUSD", "SELL", 1.26, 1.27): 1}
    │
    └─ prev_counter = Counter(prev_keys_from_positions_store)
       └─ How many of each key type we have OPEN in MT5
          Example: {("EURUSD", "BUY", 1.085, 1.075): 2,
                   ("GBPUSD", "SELL", 1.26, 1.27): 1}

3d. Compute diff
    ├─ opened = curr_counter - prev_counter
    │  └─ Keys we have signal for but NO open position
    │     Example: Count=1 for ("EURUSD", "BUY")
    │     → Open 1 position for this key
    │
    └─ closed = prev_counter - curr_counter
       └─ Keys we have OPEN but NO signal for anymore
          Example: Count=2 for ("GBPUSD", "SELL")
          → Close 2 positions for this key
```

**Why Counter diff?**

This approach is **elegant and foolproof**:
- **No guessing**: We don't try to match individual trades
- **Snapshot-based**: Website state at each moment is ground truth
- **Counts matter**: If signal appears 3 times (unlikely), we open 3 positions
- **Simple logic**: Opens and closes fall out naturally from count difference

---

### Step 4: Execute Trades (Opens)

**Code Location:** `main.py` lines ~591+, `trader.py` lines ~126+

```
4a. For each key in opened with count N:
    └─ N = how many new positions to open for this key

4b. Find matching signal
    ├─ signals_list.find(lambda s: key == SignalKey.build(s))
    └─ Get ONE signal (all signals with same key are equivalent)

4c. LAYER 2 DEDUP CHECK: Virtual SL cooldown
    ├─ Was this key recently closed by bot?
    │  └─ If yes: skip (virtual SL cooldown prevents reopen)
    └─ Advances when signal disappears from website signal list

4d. LAYER 3 DEDUP CHECK: Position store
    ├─ Check: Does position_store already track this key?
    │  └─ If yes: skip (don't duplicate)
    └─ position_store = persistent memory of what we opened

4e. LAYER 4 DEDUP CHECK: Processed signals (24h history)
    ├─ signal_id = hash(signal_time, key)
    ├─ Check: Is signal_id in processed_signals_bot_N.json?
    │  └─ If yes: skip (same signal processed within 24h)
    └─ Prevents reopening after bot restart

4f. Execute trade via MT5
    └─ Call: open_trade(signal, volume=config['TRADE_VOLUME'])

       open_trade() steps:
       ├─ 4f-i:   symbol = "EURUSD" or "EURUSD+" if not found
       ├─ 4f-ii:  mt5.symbol_select(symbol, True)
       ├─ 4f-iii: tick = mt5.symbol_info_tick(symbol)
       │          └─ Get current bid/ask prices
       ├─ 4f-iv:  price = tick.ask (if BUY) or tick.bid (if SELL)
       │          └─ Use market price
       ├─ 4f-v:   Validate and adjust SL/TP
       │          ├─ Check broker minimum distance (trade_stops_level, trade_freeze_level)
       │          └─ Adjust if needed (safety feature)
       ├─ 4f-vi:  Calculate adaptive deviation based on spread
       │          ├─ JPY pairs: max(100, 3x spread)
       │          └─ Other: max(50, 2x spread)
       ├─ 4f-vii: Build order request:
       │          {
       │            "action": TRADE_ACTION_DEAL,
       │            "symbol": pair,
       │            "volume": volume,
       │            "type": ORDER_TYPE_BUY/SELL,
       │            "price": market_price,
       │            "tp": adjusted_tp,
       │            "sl": adjusted_sl,
       │            "deviation": adaptive_deviation,
       │            "magic": 777,
       │            "comment": "blind",
       │            "type_filling": ORDER_FILLING_IOC,
       │            "type_time": ORDER_TIME_GTC
       │          }
       └─ 4f-viii: mt5.order_send(request) with retry logic (MAX_RETRIES=3)
          └─ If successful: result.retcode = 10009 (TRADE_RETCODE_DONE)
             └─ Extract ticket number: result.order

4g. Register position
    ├─ position_store.add_ticket(key, ticket)
    └─ Track this ticket in our memory

4h. Register with risk managers
    ├─ virtual_sl.add_position(ticket, pair, side, sl, tp, entry)
    ├─ trailing_stop_mgr.register_position(ticket, side, tp, sl)
    └─ Initialize MFE/MAE tracker for this ticket

4i. Mark signal as processed
    ├─ signal_id = get_signal_id(signal)
    └─ processed_signal_ids.add(signal_id)
```

---

### Step 5: Close Stale Trades

**Code Location:** `main.py` lines ~710+

```
5a. Build current_signal_keys from signals_to_manage
    ├─ These are ALL active signals (any age, defines what SHOULD be open)
    └─ current_signal_keys = {key for sig in signals_to_manage}

5b. Get all currently open positions
    ├─ open_keys = positions_store.get_all_keys()
    └─ These are positions we currently track

5c. For each open key NOT in current_signal_keys:
    ├─ key NOT in current_signal_keys → signal disappeared from website
    └─ → This trade should be closed

5d. Get tickets for this key
    └─ tickets = positions_store.get_tickets(key)

5e. For each ticket:
    ├─ Check virtual SL hasn't already marked this for cooldown
    │  └─ If marked: skip (reopen prevention)
    └─ Otherwise: close_position_by_ticket(ticket)

       close_position_by_ticket() steps:
       ├─ 5e-i:   mt5.position_get_ticket(ticket)
       │          └─ Verify position still exists on broker
       ├─ 5e-ii:  Get current price (bid for SELL, ask for BUY)
       ├─ 5e-iii: Build close request:
       │          {
       │            "action": TRADE_ACTION_DEAL,
       │            "symbol": position.symbol,
       │            "volume": position.volume,
       │            "type": OPPOSITE_SIDE (if opened BUY, close with SELL)
       │            "position": ticket,
       │            "deviation": adaptive_deviation,
       │            "magic": 777,
       │            "comment": "close",
       │            "type_filling": ORDER_FILLING_IOC,
       │            "type_time": ORDER_TIME_GTC
       │          }
       └─ 5e-iv:  mt5.order_send(request) with retry logic

5f. Update state
    ├─ position_store.remove_ticket(key, ticket)
    ├─ virtual_sl.remove_position(ticket)
    └─ trailing_stop_mgr.close_position(ticket)

5g. Log MFE/MAE
    └─ Log maximum favorable/adverse excursion seen for this position
```

---

### Step 6: Risk Management (Passive Monitoring)

**Code Location:** `main.py` lines ~730+, `virtual_sl.py`, `trailing_stop.py`

Risk management runs **passively after executions** (does not drive execution):

#### 6a. Virtual SL: Spread-Aware Stop Loss

```
Virtual SL protects against spread widening falsely triggering SL.

MECHANISM:
├─ For each open position, calculate virtual SL
├─ virtual_sl = original_sl - (current_spread × spread_factor)
│  └─ Example: if spread=0.0005, factor=1.5 → shift SL by 0.00075
├─ If price hits virtual_sl: close position BEFORE broker hits real SL
└─ Prevents premature closes from temporary spread spikes

LIFECYCLE-DRIVEN REOPEN PREVENTION:
├─ When bot closes position (via virtual SL or signal closure):
│  └─ Mark key as closed_by_bot with timestamp
├─ This key CANNOT be reopened while marked
├─ Key is unmarked ONLY when:
│  ├─ a) Signal completely disappears from website
│  └─ b) Signal stayed missing for >20 seconds (debouncing)
└─ Prevents "reopen loop" from brief signal flickers

CODE FLOW:
├─ virtual_sl.check_positions()
│  ├─ For ticket in metadata:
│  │  ├─ Get current price
│  │  ├─ Calculate current spread
│  │  ├─ Track max_spread_seen (prevent tightening after spike)
│  │  ├─ Calculate virtual_sl = broker_sl - (spread × factor)
│  │  ├─ If price has crossed virtual_sl:
│  │  │  ├─ close_position_by_ticket(ticket)
│  │  │  └─ mark_closed_by_bot(key)
│  │  └─ Otherwise: continue monitoring
│  └─ virtual_sl.cleanup_closed_signals(current_keys)
│     ├─ For each key marked closed_by_bot:
│     │  ├─ Check: is key in current_keys?
│     │  ├─ If NOT in current_keys (signal gone):
│     │  │  ├─ Check: has it been gone > 20 seconds?
│     │  │  ├─ If yes: remove from closed_by_bot
│     │  │  │           (reopen is now allowed)
│     │  │  └─ If no: wait longer
│     │  └─ If in current_keys (signal returned): wait
│     └─ This ensures single-signal-flicker doesn't cause reopen
```

#### 6b. Trailing Stop: Phase-Based SL Tightening

```
Trailing stop gradually tightens SL as trade moves in our favor.

MECHANISM:
├─ Track position in phases:
│  ├─ Phase 1: position young (<30 min), SL = original
│  ├─ Phase 2: position middle (30-60 min), SL = breakeven
│  ├─ Phase 3: position old (>60 min), SL = lock in 50% profit
│  └─ Phases are CUMULATIVE (once entered, can't go backwards)
├─ This is PASSIVE: trailing stop doesn't FORCE closes
├─ Trailing stop only TIGHTENS broker's SL via modify_order
└─ Broker is still responsible for close

IMPLEMENTATION:
├─ trailing_stop_mgr.check_positions()
│  ├─ For ticket in registry:
│  │  ├─ Calculate position age = now - entry_time
│  │  ├─ Determine phase based on age
│  │  ├─ Calculate new SL for this phase
│  │  ├─ If new SL > current broker SL (always moving favorable direction):
│  │  │  └─ mt5.order_modify() → tighten SL on broker
│  │  └─ Otherwise: no change
│  └─ persist metadata (atomic write)
└─ Remember: SL can NEVER move against us (safety)

STORAGE:
└─ trailing_stop_meta_bot_N.json stores:
   {
     "position_meta_bot_N": {
       "phase_1": {...},
       "phase_2": {...},
       "phase_3": {...}
     }
   }
```

#### 6c. Max Loss: Cumulative Protection

```
Max loss closes positions if cumulative loss exceeds threshold.

MECHANISM:
├─ For each ticket, calculate: current_loss = entry - current_price
│  └─ Example: BUY @ 1.0800, now 1.0750 → loss = 0.0050
├─ Sum loss across ALL tickets: total_loss = sum(all losses)
├─ If total_loss > MAX_LOSS_THRESHOLD:
│  └─ Close ALL positions (circuit breaker)
└─ This only happens if strategy.should_apply_max_loss() = True

CODE FLOW:
├─ For each position in registry:
│  ├─ Get current price
│  ├─ Calculate loss = entry - current (if BUY)
│  │              or = current - entry (if SELL)
│  └─ Check: is loss > threshold?
│     ├─ If yes: close_position_by_ticket(ticket)
│     └─ LOG: reason = max_loss_hit
│
├─ RISK: Order of operations matters
│  ├─ Close positions one at a time (don't cascade)
│  └─ Re-evaluate after each close

ENABLED BY STRATEGY:
└─ Max loss is optional per strategy:
   ├─ MirrorStrategy.should_apply_max_loss() = True
   ├─ ReverseStrategy.should_apply_max_loss() = False
   └─ TimeBasedStrategy.should_apply_max_loss() = True
```

---

### Step 7: State Persistence

**Code Location:** `main.py` lines ~187+, `atomic_io.py`

```
7a. Save position store
    ├─ positions.to_dict() → JSON-serializable dict
    ├─ atomic_write_json(positions_store_bot_N.json, dict)
    └─ Atomic: write to temp file, then os.replace()

7b. Save processed signals (24h dedup layer 4)
    ├─ data = {signal_id: timestamp for signal_id in processed_signal_ids}
    ├─ Prune: keep only signals < 24 hours old
    └─ atomic_write_json(processed_signals_bot_N.json, data)

7c. Save trailing stop metadata
    ├─ trailing_stop_mgr._save_position_meta()
    └─ Already atomic (uses atomic_io internally)

7d. Safe read/write pattern
    ├─ WRITE:
    │  ├─ Open temp file: fd, path = tempfile.mkstemp()
    │  ├─ Write JSON to temp
    │  ├─ Close temp
    │  └─ os.replace(temp_path, final_path) ← ATOMIC
    │
    └─ READ:
       ├─ Try read with retry logic (max 3 attempts)
       ├─ On read conflict: sleep 0.1s and retry
       └─ On permanent failure: return None gracefully
```

---

### Step 8: Logging & Analytics

**Code Location:** `main.py` lines ~800+, `trades_history.jsonl`

```
8a. Execution logs
    ├─ Printed to bot_N.log (timestamped)
    ├─ Format:
    │  [TRADE_OPEN] T{ticket} EURUSD BUY @ 1.0800 (SL=1.0750, TP=1.0850)
    │  [TRADE_CLOSE] T{ticket} EURUSD BUY | MFE=+0.0050 MAE=-0.0025
    │  [TRAIL] Tightened SL on T{ticket} from 1.0750 to 1.0770
    └─ Also logged to operational_safety.log for monitor integration

8b. Trade history (JSONL)
    ├─ Append-only line-delimited JSON
    ├─ One trade per line (immutable history)
    │
    └─ Schema:
       {
         "timestamp": "2026-04-03T15:30:45Z",
         "bot_id": 1,
         "symbol": "EURUSD",
         "side": "BUY",
         "volume": 0.01,
         "entry_price": 1.0800,
         "tp": 1.0850,
         "sl": 1.0750,
         "entry_time": "2026-04-03T15:30:00Z",
         "close_time": "2026-04-03T15:35:22Z",
         "close_price": 1.0820,
         "close_reason": "TP_HIT",
         "pnl": 0.0020,       # profit (close_price - entry_price)
         "pnl_pct": 0.20,     # % of risk taken
         "max_profit": 0.0050,   # MFE
         "max_loss": -0.0010,    # MAE
       }

8c. MFE/MAE tracking (in-memory during trade lifetime)
    ├─ mfe_mae_tracker = {ticket: {"max_profit": float, "max_loss": float}}
    ├─ Updated every cycle:
    │  ├─ Get current price
    │  ├─ BUY: MFE = max(high_price - entry), MAE = min(low_price - entry)
    │  └─ SELL: MFE = max(entry - low_price), MAE = min(entry - high_price)
    └─ When trade closes: copy MFE/MAE to history and delete from tracker
```

---

## Data Flow

### Signal Data Path

```
┌─────────────────────────────────────────────────────────────────┐
│ MAGNETIC FLOW (Website Signal IPC)                              │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Website (HTML)                                                 │
│    ↓                                                            │
│  scraper.py (fetch_page with proxy rotation)                   │
│    ↓                                                            │
│  parser.py (parse_signals → extract rows, validate SL/TP)      │
│    ↓                                                            │
│  signal_fetcher.py (continuous, every 10s)                     │
│    ├─ Compute SHA256(signals_content)                          │
│    ├─ Build payload: {version, hash, timestamp, signals, status}
│    └─ atomic_write_json(signals.json)                          │
│    └─ shutil.copy(signals.json, signals_backup.json)           │
│                                                                  │
│  signals.json (IPC: Shared state)                               │
│    ↓ (read by all 3 bots, every 7 seconds)                      │
│    ├─ Bot 1: signal_reader.read_signals_safe()                 │
│    ├─ Bot 2: signal_reader.read_signals_safe()                 │
│    └─ Bot 3: signal_reader.read_signals_safe()                 │
│         │                                                       │
│         ├─ Validate hash (DEDUP LAYER 1)                        │
│         ├─ Filter by age (signals < 30 min)                     │
│         └─ Return: signals_to_open, signals_to_manage           │
│                                                                  │
│  [Each bot independently processes its signals]                 │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### Position Data Path

```
┌─────────────────────────────────────────────────────────────────┐
│ POSITION LIFECYCLE (Local bot state, MT5 as source of truth)    │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  OPEN TRADE FLOW:                                                │
│  ─────────────────                                               │
│  1. Signal from website (signals.json)                          │
│  2. Strategy transforms signal                                  │
│  3. Counter diff: diff["opened"] signals                        │
│  4. open_trade(signal, volume)                                  │
│     └─ mt5.order_send() → ticket returned                       │
│  5. position_store.add_ticket(key, ticket)                      │
│  6. atomic_write_json(positions_store_bot_N.json)               │
│                                                                  │
│  STATE IN MEMORY (during trade):                                 │
│  ────────────────────────────────                                │
│  positions_store = {                                             │
│    ("EURUSD", "BUY", 1.085, 1.075): [1001, 1002],  # 2 tickets  │
│    ("GBPUSD", "SELL", 1.260, 1.270): [2001],       # 1 ticket   │
│  }                                                    │          │
│                                                      │          │
│  CLOSE TRADE FLOW:                                   │          │
│  ────────────────                                    │          │
│  1. Signal disappears from website                   │          │
│  2. Counter diff: diff["closed"] signals             │          │
│  3. close_position_by_ticket(ticket)                 │          │
│     └─ mt5.order_send(OPPOSITE_SIDE) → closed       │          │
│  4. position_store.remove_ticket(key, ticket)        │          │
│  5. atomic_write_json(positions_store_bot_N.json)    │          │
│                                                      │          │
│  STATE ON DISK:                                       │          │
│  ──────────────                                        │          │
│  positions_store_bot_1.json = {                      │          │
│    "keys": {                                          │          │
│      "EURUSD_BUY_1.085_1.075": {                     │          │
│        "tickets": [1001, 1002],                      │          │
│        "pair": "EURUSD",                             │          │
│        "side": "BUY",                                │          │
│        "tp": 1.085,                                  │          │
│        "sl": 1.075                                   │          │
│      },                                               │          │
│      "GBPUSD_SELL_1.260_1.270": {...}              │          │
│    }                                                  │          │
│  }                                                    │          │
│                                                      │          │
└─────────────────────────────────────────────────────┘
```

### Trade History Data Path

```
┌─────────────────────────────────────────────────────────────────┐
│ ANALYTICS (Immutable trade history)                             │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  When trade closes:                                              │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │ 1. Collect trade data:                                    │  │
│  │    - entry_time, entry_price, entry_side                │  │
│  │    - close_time, close_price, close_reason              │  │
│  │    - MFE/MAE from tracker                               │  │
│  │    - Calculate PnL = (close_price - entry_price) * vol  │  │
│  │                                                          │  │
│  │ 2. Build JSON record:                                    │  │
│  │    {                                                     │  │
│  │      "timestamp": close_time,                           │  │
│  │      "bot_id": 1,                                        │  │
│  │      "symbol": "EURUSD",                                │  │
│  │      "side": "BUY",                                      │  │
│  │      "volume": 0.01,                                     │  │
│  │      "entry_price": 1.0800,                             │  │
│  │      "close_price": 1.0820,                             │  │
│  │      "pnl": 0.0020,                                      │  │
│  │      "max_profit": 0.0050,                               │  │
│  │      "max_loss": -0.0010,                                │  │
│  │      ...                                                 │  │
│  │    }                                                     │  │
│  │                                                          │  │
│  │ 3. Append to trades_history.jsonl:                       │  │
│  │    {json_line}\n                                         │  │
│  │                                                          │  │
│  │ APPEND-ONLY: No updates, no deletes                     │  │
│  │ One trade = one immutable line                          │  │
│  │                                                          │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                  │
│  File after 100 trades:                                          │
│  ───────────────────────                                         │
│  {trade_1}\n                                                     │
│  {trade_2}\n                                                     │
│  ...                                                             │
│  {trade_100}\n                                                    │
│                                                                  │
│  Dashboard.py reads this file:                                   │
│  ──────────────────────────────                                  │
│  ├─ df = pd.read_json("trades_history.jsonl", lines=True)       │
│  ├─ Calculate metrics:                                           │
│  │  ├─ Win rate = won_trades / total_trades                     │
│  │  ├─ Average PnL                                               │
│  │  ├─ Sharpe ratio                                              │
│  │  ├─ Max drawdown                                              │
│  │  ├─ MFE/MAE distribution                                      │
│  │  └─ Per-symbol performance                                    │
│  └─ Display in Streamlit app                                     │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## File System Design

### Per-Bot Isolation

**Goal:** Eliminate any possibility of concurrent access conflicts

```
BOT 1 INSTANCE (Process Group 1)
├─ bot_1.log
│  └─ All output redirected here (sys.stdout redirection)
│
├─ positions_store_bot_1.json
│  ├─ Tracks open positions for Bot 1
│  ├─ Read at startup (recovery)
│  ├─ Written after each cycle (persist state)
│  └─ Format: {key: [ticket1, ticket2, ...]}
│
├─ trailing_stop_meta_bot_1.json
│  ├─ SL stage tracking for Bot 1
│  ├─ Read during TrailingStopManager init
│  ├─ Written by TrailingStopManager._save_position_meta()
│  └─ Format: {"phase_1": {...}, "phase_2": {...}, ...}
│
└─ processed_signals_bot_1.json
   ├─ Last 24h of processed signal IDs
   ├─ Used for DEDUP LAYER 4
   ├─ Loaded at startup, updated each cycle
   └─ Format: {signal_id: timestamp, ...}

BOT 2 INSTANCE (Process Group 2)
├─ bot_2.log
├─ positions_store_bot_2.json
├─ trailing_stop_meta_bot_2.json
└─ processed_signals_bot_2.json

BOT 3 INSTANCE (Process Group 3)
├─ bot_3.log
├─ positions_store_bot_3.json
├─ trailing_stop_meta_bot_3.json
└─ processed_signals_bot_3.json
```

### Shared IPC Files

```
signals.json (PRIMARY)
├─ Published by: signal_fetcher.py (central process, every 10s)
├─ Read by: All 3 bots (every 7s cycle)
├─ Atomically written (temp → replace)
├─ Format:
│  {
│    "version": 42,
│    "hash": "abc123...",
│    "timestamp": "2026-04-03T15:30:45Z",
│    "status": "OK" or "ERROR",
│    "signals": [
│      {"pair": "EURUSD", "side": "BUY", "open": 1.0800, ...},
│      {...}
│    ]
│  }
└─ Size: ~5-50 KB (typically 40-60 signals)

signals_backup.json (FALLBACK)
├─ Created by: signal_fetcher.py after successful write
├─ Read by: Bots if signals.json corrupted
├─ Contains: Last known good signal state
└─ Prevents total signal loss if signals.json write fails mid-cycle

config_bot_1.py, config_bot_2.py, config_bot_3.py
├─ Read-only configuration files
├─ Each bot loads its own config
└─ Define: BOT_ID, TRADE_VOLUME, MT5 credentials, STRATEGY, etc.
```

### Analytics Files

```
trades_history.jsonl (APPEND-ONLY)
├─ Written by: All 3 bots (append only)
├─ One trade per line (JSON newline-delimited)
├─ Schema: {timestamp, bot_id, symbol, side, ..., pnl, max_profit, max_loss}
├─ Atomic appends: No interleaving possible (file system level)
└─ Read by: dashboard.py for analytics

bot_1.log, bot_2.log, bot_3.log (APPEND)
├─ Written by: Each bot process
├─ sys.stdout redirected to these files at startup
├─ Format: [TIMESTAMP] [TAG] message
└─ Human-readable debugging
```

### Why This Design is Safe

```
NO RACE CONDITIONS:
├─ Each bot ONLY reads its own files
├─ Each bot ONLY writes its own files
├─ Shared IPC (signals.json) written atomically by ONE process
└─ Trades history uses atomic append (OS level)

NO DATA CORRUPTION:
├─ Atomic writes prevent partial writes on crash
├─ Temp file + os.replace() is atomic at filesystem level
├─ Each bot has independent state (no dependencies)
└─ Fallback signals_backup.json prevents total signal loss

NO DEADLOCKS:
├─ No explicit locking needed
├─ File-level isolation prevents contention
├─ Each bot runs independently (no synchronization)
└─ Trades history append is sequential (no conflicts)

RESTART SAFE:
├─ All state on disk in bot-specific files
├─ Stateless processes: can kill/restart any bot anytime
├─ State recovery loads all files atomically
└─ No in-process state is lost
```

---

## Strategy System

### Strategy Abstraction

All strategies inherit from `BaseStrategy` and implement:

```python
class BaseStrategy(ABC):

    @abstractmethod
    def transform_signal(self, signal) -> Signal:
        """Return transformed copy of signal."""
        pass

    @abstractmethod
    def should_apply_trailing(self) -> bool:
        """Whether trailing stop is enabled."""
        pass

    @abstractmethod
    def should_apply_max_loss(self) -> bool:
        """Whether max loss protection is enabled."""
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        """Strategy identifier: 'mirror', 'reverse', 'time_based'."""
        pass
```

### Strategy Implementations

#### Strategy 1: Mirror

```
DEFINITION: Follow signals exactly as published

transform_signal(signal):
    ├─ Return copy of signal UNCHANGED
    └─ side, tp, sl all preserved

should_apply_trailing(): True
├─ Enable trailing stop SL tightening

should_apply_max_loss(): True
└─ Enable max loss protection

USE CASE:
├─ Conservative approach
├─ Trust website signals completely
└─ Maximize profit with risk management
```

#### Strategy 2: Reverse

```
DEFINITION: Always invert signal direction

transform_signal(signal):
    ├─ NEW side = "SELL" if BUY else "BUY"
    └─ NEW tp, sl = SWAP(tp, sl)

Example:
├─ Input:  EURUSD BUY, TP=1.0850, SL=1.0750
└─ Output: EURUSD SELL, TP=1.0750, SL=1.0850
           (side inverted, tp/sl swapped)

should_apply_trailing(): False
├─ No trailing stop (contrarian strategy)

should_apply_max_loss(): False
└─ No max loss (full risk taking)

USE CASE:
├─ Contrarian betting (inverse signals)
├─ No risk management (assumes expertise)
└─ Higher volatility, higher return potential
```

#### Strategy 3: Time-Based Hybrid

```
DEFINITION: Mode selected by signal timestamp (IST)

Rules (based on signal.time hour in IST):
├─ 16:00 - 20:00 IST (4 PM - 8 PM):  MIRROR mode
│  └─ transform_signal(signal) returns signal unchanged
│
└─ All other hours: REVERSE mode
   └─ transform_signal(signal) inverts side + swaps tp/sl

CRITICAL: Use signal.time, NOT wall-clock time
├─ Why? Determinism + restart safety
├─ Same signal always produces same output
├─ No mid-trade flipping if bot restarts

should_apply_trailing(): True
├─ Enable trailing stop regardless of mode

should_apply_max_loss(): True
└─ Enable max loss regardless of mode

Implementation Example:
```python
def transform_signal(self, signal):
    hour, sig_time_ist = self._get_signal_hour_ist(signal)
    is_mirror = 16 <= hour < 20  # 4 PM to 8 PM IST

    if is_mirror:
        return signal  # MIRROR mode
    else:
        # REVERSE mode
        sig = deepcopy(signal)
        sig.side = "SELL" if sig.side == "BUY" else "BUY"
        sig.tp, sig.sl = sig.sl, sig.tp
        return sig
```

USE CASE:
├─ Adaptive strategy based on market hours
├─ Follow signals during active hours (4-8 PM IST)
├─ Invert during quiet hours
└─ Balances conservative + contrarian approaches
```

### Strategy Configuration

```
Each bot configures its strategy in config_bot_N.py:

config_bot_1.py:
  STRATEGY = "mirror"
  → Bot 1 follows signals exactly

config_bot_2.py:
  STRATEGY = "reverse"
  → Bot 2 inverts all signals

config_bot_3.py:
  STRATEGY = "time_based"
  → Bot 3 uses hybrid time-based logic

At startup:
├─ strategy = get_strategy(config['STRATEGY'])
├─ Extract risk flags:
│  ├─ trailing_stop_enabled = strategy.should_apply_trailing()
│  └─ max_loss_enabled = strategy.should_apply_max_loss()
└─ Print configuration banner
```

---

## Execution Engine: Counter Diff Logic

### Why Counter Diff?

The execution engine uses **Counter-based diff** (from Python's `collections.Counter`) because it is:

- **Simple**: No guessing, just count differences
- **Robust**: Works with any signal stream
- **Deterministic**: Same signals → same execution
- **Snapshot-based**: Website state at each moment is ground truth

### How It Works

```
GOAL: Keep bot's open positions = website's active signals

PRINCIPLE: Website signal list is snapshot of what SHOULD be open

MECHANISM:
──────────

1. LOAD CURRENT STATE
   ├─ Load signals from website (IPC via signals.json)
   ├─ Load positions from disk (positions_store_bot_N.json)
   └─ Load MT5 live positions (to verify positions_store accuracy)

2. BUILD COUNTERS
   ├─ Transform signals per strategy
   ├─ Extract keys: key = (pair, side, tp, sl)
   └─ Build two Counters:
      ├─ curr_counter = Counter(keys_in_current_signals)
      │  └─ Example: {("EURUSD", "BUY", 1.085, 1.075): 1}
      │             Count=1 means 1 active signal with this params
      │
      └─ prev_counter = Counter(keys_in_positions_store)
         └─ Example: {("EURUSD", "BUY", 1.085, 1.075): 2}
                    Count=2 means we have 2 open positions with this params

3. COMPUTE DIFF
   ├─ opened = curr_counter - prev_counter
   │  └─ Positive counts = how many NEW positions to open
   │     Example: {("EURUSD", "BUY", 1.085, 1.075): 1}
   │                      → Open 1 position for this key
   │
   ├─ closed = prev_counter - curr_counter
   │  └─ Positive counts = how many positions to CLOSE
   │     Example: {("GBPUSD", "SELL", 1.260, 1.270): 2}
   │                      → Close 2 positions for this key
   │
   └─ unchanged = curr_counter & prev_counter
      └─ Intersection = positions that stay open
         Example: {("USDJPY", "BUY", 149.0, 148.0): 1}
                       → Do nothing, keep this open

4. EXECUTE DIFFERENCES
   ├─ For each key in opened:
   │  └─ open_trade() that many times
   │
   └─ For each key in closed:
      └─ close_position_by_ticket() that many times

5. UPDATE STATE
   ├─ Record opened positions in positions_store
   ├─ Remove closed positions from positions_store
   └─ Persist to disk (atomic write)
```

### Example Walkthrough

```
SCENARIO 1: New Signal Arrives
─────────────────────────────────
Previous state:
├─ Signals: EURUSD BUY @ 1.0800 (1 signal)
└─ Positions: 1 open trade (tracking EURUSD BUY)

New website refresh:
├─ Signals: EURUSD BUY @ 1.0800 + GBPUSD SELL @ 1.2600 (2 signals)
└─ Why? New signal published, old one still active

Counter diff:
├─ prev_counter: {("EURUSD", "BUY", 1.085, 1.075): 1}
├─ curr_counter: {("EURUSD", "BUY", 1.085, 1.075): 1,
│                 ("GBPUSD", "SELL", 1.260, 1.270): 1}
│
├─ opened: {("GBPUSD", "SELL", 1.260, 1.270): 1}
│  → Open 1 GBPUSD SELL position
│
└─ closed: {} (empty, nothing closed)

Result:
├─ Execute: open_trade(GBPUSD SELL)
├─ Update positions_store with new ticket
└─ Bot now has 2 open trades (EURUSD + GBPUSD)

───────────────────────────────────────────

SCENARIO 2: Signal Closes
──────────────────────────
Previous state:
├─ Signals: EURUSD BUY + GBPUSD SELL (2 signals, 2 positions)
└─ Positions: 2 open trades

New website refresh:
├─ Signals: GBPUSD SELL only (EURUSD BUY disappeared)
└─ Why? Website closed the EURUSD BUY signal

Counter diff:
├─ prev_counter: {("EURUSD", "BUY", 1.085, 1.075): 1,
│                 ("GBPUSD", "SELL", 1.260, 1.270): 1}
│
├─ curr_counter: {("GBPUSD", "SELL", 1.260, 1.270): 1}
│
├─ opened: {} (nothing new)
│
└─ closed: {("EURUSD", "BUY", 1.085, 1.075): 1}
   → Close 1 EURUSD BUY position

Result:
├─ Execute: close_position_by_ticket(ticket_of_EURUSD_BUY)
├─ Remove EURUSD key from positions_store
└─ Bot now has 1 open trade (GBPUSD)

───────────────────────────────────────────

SCENARIO 3: Multiple Signals Same Type
─────────────────────────────────────────
Previous state:
├─ Signals: EURUSD BUY (1 signal)
└─ Positions: 1 open trade

New website refresh:
├─ Signals: EURUSD BUY + EURUSD BUY + EURUSD BUY (3 times)
└─ Why? Website lists same signal 3 times (rare but possible)

Counter diff:
├─ prev_counter: {("EURUSD", "BUY", 1.085, 1.075): 1}
├─ curr_counter: {("EURUSD", "BUY", 1.085, 1.075): 3}
│
└─ opened: {("EURUSD", "BUY", 1.085, 1.075): 2}
   → Open 2 MORE EURUSD BUY positions

Result:
├─ Execute: open_trade(EURUSD BUY) twice
├─ Update positions_store: now 3 tickets for same key
└─ Bot has 3 open EURUSD BUY positions at same params
   (different tickets, opened at slightly different times/prices)
```

### Why This Prevents Duplicates

```
DUPLICATE PREVENTION LAYERS:

Layer 1: Content Hash (signals.json)
├─ If website publishes signal_content_A at t=10
├─ Signal fetcher computes hash_A = SHA256(signal_content_A)
├─ At t=20, if website publishes SAME content: hash_A again
├─ Signal reader checks: hash == last_hash?
├─ YES → Skip entire cycle (no dedup needed)
└─ Prevents re-execution of identical signal multiple times

Layer 2: Virtual SL Cooldown
├─ If bot closes position due to virtual SL spread spike
├─ Mark key as "closed_by_bot" temporarily
├─ Prevent reopen until signal disappears (debounced 20s)
└─ Prevents rapid reopen-close loops from spread jiggles

Layer 3: Position Store Check
├─ Before open_trade(): check if key already in positions_store
├─ If already there: skip (already tracking this position)
└─ Catches duplicates even if signals somehow bypass layers 1-2

Layer 4: Processed Signals (24h history)
├─ Track every signal_id we've processed
├─ Retain 24h history: load on startup, prevent re-exec after restart
├─ If bot restarts, same signal within 24h won't reopen
└─ Full restart safety guarantee
```

---

## MT5 Integration

### MT5 Initialization

```
init_mt5() in trader.py:

1. Check if MT5 already initialized
   ├─ mt5.initialize()
   └─ If returns True: already running

2. If not initialized: Launch terminal
   ├─ subprocess.Popen(MT5_EXE, creationflags=CREATE_NO_WINDOW)
   ├─ Wait 10 seconds (terminal startup time)
   └─ Retry mt5.initialize()

3. Login
   ├─ mt5.login(MT5_LOGIN, MT5_PASSWORD, MT5_SERVER)
   └─ Verify successful

4. Get account info
   ├─ account_info = mt5.account_info()
   ├─ Extract: balance, margin, equity
   └─ Used for monitoring/verification

5. Ready for trading
   └─ Either mt5.order_send() or mt5.symbol_info()
```

### MT5 Terminal Isolation

```
Each bot connects to INDEPENDENT terminal instance:

Bot 1:
├─ Terminal path: D:\MT5s\MetaTrader 5\terminal64.exe
├─ Terminal ID: /MT5/bot_1 (in init flow)
├─ Login: 24446623
├─ Server: VantageInternational-Demo
└─ Result: Separate broker connection, separate accounts, separate positions

Bot 2:
├─ Terminal path: D:\MT5s\MetaTrader 5\terminal64.exe
├─ Terminal ID: /MT5/bot_2
├─ Login: 24446624
├─ Server: VantageInternational-Demo
└─ Result: Separate broker connection (different account)

Bot 3:
├─ Terminal path: D:\MT5s\MetaTrader 5\terminal64.exe
├─ Terminal ID: /MT5/bot_3
├─ Login: 24446625
├─ Server: VantageInternational-Demo
└─ Result: Separate broker connection (third account)

MT5 Multi-Terminal Setup:
├─ Each MT5 instance is independent Windows process
├─ Each loads different terminal profile (/MT5/bot_N)
├─ Each logs into different account (24446623, 24446624, 24446625)
├─ NO account sharing
├─ NO position mixing
└─ Complete isolation at MT5 level
```

### Order Execution

```
open_trade(signal, volume) flow:

1. Extract signal params
   ├─ pair = signal.pair (e.g., "EURUSD")
   ├─ side = signal.side (e.g., "BUY")
   ├─ tp = signal.tp (take profit)
   └─ sl = signal.sl (stop loss)

2. Ensure symbol available in MT5
   ├─ mt5.symbol_select(pair, True)
   ├─ Alternate: try pair + "+" suffix
   └─ Get symbol_info(pair)

3. Get current price
   ├─ tick = mt5.symbol_info_tick(pair)
   ├─ Ask price = tick.ask
   └─ Bid price = tick.bid

4. Determine order type & price
   ├─ If side == "BUY":
   │  ├─ order_type = ORDER_TYPE_BUY
   │  └─ price = ask (market price to buy)
   │
   └─ If side == "SELL":
      ├─ order_type = ORDER_TYPE_SELL
      └─ price = bid (market price to sell)

5. Validate and adjust SL/TP
   ├─ Get broker constraints:
   │  ├─ trade_stops_level (minimum pips from price)
   │  └─ trade_freeze_level (minimum pips between orders)
   ├─ Use MAXIMUM of both (most restrictive)
   ├─ If SL/TP violate: move them to broker minimum
   └─ Ensures order won't be rejected

6. Calculate adaptive deviation
   ├─ For JPY pairs: max(100, 3 × current_spread)
   ├─ For others: max(50, 2 × current_spread)
   └─ Higher deviation = more slippage tolerance

7. Build order request
   ├─ {
   │    "action": TRADE_ACTION_DEAL,
   │    "symbol": pair,
   │    "volume": volume (e.g., 0.01 lots),
   │    "type": ORDER_TYPE_BUY or SELL,
   │    "price": ask_or_bid,
   │    "tp": adjusted_tp,
   │    "sl": adjusted_sl,
   │    "deviation": adaptive_deviation,
   │    "magic": 777 (magic number, all trades same),
   │    "comment": "blind",
   │    "type_filling": ORDER_FILLING_IOC (fill or kill),
   │    "type_time": ORDER_TIME_GTC (good till cancel)
   │  }

8. Execute with retry logic
   ├─ for attempt in range(MAX_RETRIES=3):
   │  ├─ result = mt5.order_send(request)
   │  ├─ Check result.retcode
   │  ├─ If retcode == 10009 (TRADE_RETCODE_DONE): SUCCESS
   │  ├─ Otherwise: retry with backoff
   │  └─ Extract result.order as ticket
   │
   └─ Return (success: bool, ticket: int)

9. On success
   ├─ ticket = result.order
   ├─ Return (True, ticket)
   └─ Caller adds to position_store

10. On failure
    ├─ Return (False, None)
    └─ Caller skips this signal
```

### Order Close

```
close_position_by_ticket(ticket) flow:

1. Get position info
   ├─ position = mt5.positions_get(ticket=ticket)
   ├─ Verify position exists (handle if already closed by broker)
   └─ Extract: symbol, volume, type (BUY/SELL)

2. Get current price
   ├─ tick = mt5.symbol_info_tick(position.symbol)
   ├─ Bid = tick.bid
   └─ Ask = tick.ask

3. Determine close price
   ├─ If position is BUY: close_price = bid (sell side)
   ├─ If position is SELL: close_price = ask (buy side)
   └─ Use opposite side to close

4. Build close request
   ├─ {
   │    "action": TRADE_ACTION_DEAL,
   │    "symbol": position.symbol,
   │    "volume": position.volume,
   │    "type": order_type (opposite of position.type),
   │    "position": ticket (close THIS exact position),
   │    "deviation": adaptive_deviation,
   │    "magic": 777,
   │    "comment": "close",
   │    "type_filling": ORDER_FILLING_IOC,
   │    "type_time": ORDER_TIME_GTC
   │  }

5. Execute with retry logic (same as open)
   ├─ mt5.order_send(request)
   └─ Verify retcode == 10009

6. Update state
   ├─ Remove from position_store
   ├─ Remove from virtual_sl tracking
   ├─ Log MFE/MAE
   └─ Persist state
```

### MT5 Magic Number & Comment

```
ALL trades use same magic number: 777

WHY:
├─ Magic number = identifier for bot's trades vs other EA trades
├─ Single magic = simpler filtering
├─ Alternative: use different magic per bot (not needed here)
└─ All trades tagged as "blind" in comment

COMMENT tags:
├─ "blind" = opened by blind follower bot
├─ "close" = closed by blind follower bot
└─ Used for log parsing and debugging
```

---

## Risk Management

### Virtual SL: Spread-Aware Stop Loss

**Problem it solves:** Spread widening can falsely trigger SL, causing premature closes

```
MECHANISM:
──────────

1. TRACK MAX SPREAD
   ├─ For each open position, track max_spread_seen
   ├─ Prevents SL from tightening AFTER a spread spike (safety)
   └─ Example: max_spread_seen = 0.0008 pips

2. CALCULATE VIRTUAL SL
   ├─ virtual_sl = broker_sl - (current_spread × spread_factor)
   ├─ spread_factor = 1.5 (configurable)
   ├─ If current_spread > max_spread_seen:
   │  └─ Update max_spread_seen
   ├─ Example:
   │  ├─ broker_sl = 1.0750
   │  ├─ current_spread = 0.0005
   │  ├─ factor = 1.5
   │  └─ virtual_sl = 1.0750 - (0.0005 × 1.5) = 1.07475
   │
   └─ virtual_sl is NEVER tightened (only loosened if spread widens)

3. MONITOR FOR CROSS
   ├─ If price crosses virtual_sl:
   │  ├─ Close position immediately
   │  └─ Mark key as "temporarily_closed_by_virtual_sl"
   │
   └─ If price doesn't cross: continue tracking

WHY THIS WORKS:
├─ Spread spike: from 0.0005 to 0.0010
├─ Without virtual SL: broker hits SL at 1.0750 (bad luck)
├─ With virtual SL: bot closes at 1.0748 (controlled)
└─ Prevents false SL hits due to temporary spread widening
```

**Reopen Prevention (Lifecycle-driven):**

```
REOPEN RULES:
─────────────

1. After bot closes position (via virtual SL)
   ├─ Mark key as "closed_by_bot" with timestamp
   └─ Set reopen_allowed = False

2. Reopen is ONLY allowed when:
   ├─ Signal completely disappears from website
   ├─ Signal stays missing for >20 seconds (debounce)
   └─ THEN: remove from closed_by_bot dict

3. Prevention of reopen loop:
   ├─ Scenario: Spread spike, virtual SL closes, spread returns
   ├─ Without cooldown: immediately reopen (wrong!)
   ├─ With cooldown: wait for signal to fully disappear
   └─ Ensures intentional close (signal end), not fluke

IMPLEMENTATION:
├─ virtual_sl.closed_by_bot = {key: timestamp}
├─ virtual_sl.signal_missing_since = {key: timestamp}
├─ Each cycle:
│  ├─ Check if closed_by_bot key is in current_keys
│  ├─ If NOT in current_keys:
│  │  ├─ Check: elapsed_time > reset_confirm_seconds (20s)?
│  │  ├─ If yes: remove from closed_by_bot
│  │  └─ If no: wait longer
│  └─ If in current_keys: keep closed
└─ This debouncing prevents false reopens from signal flickers
```

### Trailing Stop: Phase-Based SL Tightening

**Mechanism:**

```
PHASES (based on trade age from entry):

Phase 1: Newborn (< 30 minutes)
├─ SL = original from signal
├─ Rationale: Let trade breathe, don't close prematurely
└─ No modification

Phase 2: Young (30-60 minutes)
├─ SL = breakeven (entry price)
├─ Rationale: Set SL to break even, profit is mine
└─ mt5.order_modify() to update broker's SL

Phase 3: Adult (> 60 minutes)
├─ SL = lock_in_50% (entry + 50% of TP distance)
├─ Rationale: Lock in half profit, can't lose anymore
├─ Example:
│  ├─ Entry: 1.0800
│  ├─ TP: 1.0850 (distance = 0.0050)
│  ├─ Phase 3 SL = 1.0800 + (0.0050 × 0.5) = 1.0825
│  └─ Can move 0.0025 in our favor, 0 in our disfavor
│
└─ mt5.order_modify() to update broker's SL

GUARANTEES:
├─ SL NEVER moves against us (always favorable direction)
├─ Each phase is CUMULATIVE (can't go backwards)
├─ SL can only move closer to profitable side
└─ Broker SL is ground truth (bot only tightens, never loosens)

STORAGE:
└─ trailing_stop_meta_bot_N.json tracks:
   {
     "phase_1": {ticket: metadata},
     "phase_2": {ticket: metadata},
     "phase_3": {ticket: metadata}
   }
```

**Why phase-based (not continuous)?**

- Simpler logic: 3 discrete states instead of continuous curve
- Predictable behavior: same age → same SL
- No overly-aggressive tightening: gradual progression
- Safety: SL only moves favorable direction
- Restart-safe: phases persist to disk

### Max Loss: Cumulative Circuit Breaker

```
MECHANISM:
──────────

1. Calculate PnL for each open position
   ├─ For BUY: loss = entry_price - current_price
   ├─ For SELL: loss = current_price - entry_price
   └─ If loss > 0: we're losing money

2. Sum all losses
   ├─ total_loss = sum(loss for all positions)
   ├─ Example:
   │  ├─ Position 1: loss = -0.0010
   │  ├─ Position 2: loss = -0.0015
   │  └─ total_loss = -0.0025
   │
   └─ Negative loss = actual profit (ignore)

3. Check threshold
   ├─ MAX_LOSS_THRESHOLD = defined in strategy or config
   ├─ If total_loss > MAX_LOSS_THRESHOLD:
   │  ├─ Trigger circuit breaker
   │  └─ Close ALL positions immediately
   │
   └─ Otherwise: continue

4. Close all positions
   ├─ for ticket in all_tickets:
   │  └─ close_position_by_ticket(ticket)
   │
   └─ Log: reason = "max_loss_hit"

WHY THIS WORKS:
├─ Stops cascade of losses
├─ "Circuit breaker" pattern: stop damage before it's catastrophic
├─ Cumulative loss: prevents "1000 small losses" issue
└─ All positions close simultaneously (no cascade)

ENABLED BY STRATEGY:
├─ MirrorStrategy: max_loss = True (uses it)
├─ ReverseStrategy: max_loss = False (no protection)
└─ TimeBasedStrategy: max_loss = True (uses it)
```

---

## Analytics System

### MFE/MAE Tracking

**Purpose:** Track maximum favorable and adverse excursion for each trade

```
DEFINITIONS:
─────────────

MFE (Maximum Favorable Excursion):
├─ Maximum profit seen during trade lifetime
├─ Example: Entry @ 1.0800, price touched 1.0850, close @ 1.0820
├─ MFE = 1.0850 - 1.0800 = 0.0050
└─ Shows best-case scenario achieved

MAE (Maximum Adverse Excursion):
├─ Maximum loss seen during trade lifetime
├─ Example: Entry @ 1.0800, price touched 1.0750, close @ 1.0820
├─ MAE = 1.0750 - 1.0800 = -0.0050
└─ Shows worst pain endured

TRACKING = in-memory dict:
├─ mfe_mae_tracker[ticket] = {
│    "max_profit": 0.0050,
│    "max_loss": -0.0050
│  }
│
└─ Updated every cycle (extremely lightweight)

CALCULATION:
├─ For each ticket in tracker:
│  ├─ Get position info from MT5
│  ├─ Get current price
│  ├─ For BUY:
│  │  ├─ current_profit = current_price - entry_price
│  │  ├─ Update max_profit = max(max_profit, current_profit)
│  │  └─ Update max_loss = min(max_loss, current_profit)
│  │
│  └─ For SELL:
│     ├─ current_profit = entry_price - current_price
│     ├─ Update max_profit = max(max_profit, current_profit)
│     └─ Update max_loss = min(max_loss, current_profit)
│
└─ O(n) per cycle, very fast
```

### Trade History (JSONL)

**Format:**

```json
{
  "timestamp": "2026-04-03T15:35:22Z",       # When trade closed
  "bot_id": 1,                                # Which bot
  "symbol": "EURUSD",                         # Trading pair
  "side": "BUY",                              # Direction
  "volume": 0.01,                             # Lot size
  "entry_price": 1.0800,                      # Open price
  "tp": 1.0850,                               # Original TP
  "sl": 1.0750,                               # Original SL
  "entry_time": "2026-04-03T15:30:00Z",      # When opened
  "close_time": "2026-04-03T15:35:22Z",      # When closed
  "close_price": 1.0820,                      # Close price
  "close_reason": "TP_HIT",                   # Why closed
  "pnl": 0.0020,                              # Profit = close - entry
  "pnl_pct": 0.20,                            # % return
  "max_profit": 0.0050,                       # MFE
  "max_loss": -0.0010,                        # MAE
  "trade_duration_seconds": 322,              # How long open
  "strategy": "mirror",                       # Which strategy
  "signal_age_at_open": 15                    # Signal age when opened (seconds)
}
```

**Why JSONL (not JSON array)?**

- **Append-only:** One trade per line, append without re-read/write
- **Atomic:** Each append is atomic (filesystem-level)
- **Streaming:** Can read incrementally
- **No conflicts:** Multiple bots can append simultaneously (OS level)
- **Simple:** Easy to parse: `for line in file: json.loads(line)`

### Dashboard Analytics

**Data source:** trades_history.jsonl

```
dashboard.py reads JSONL and computes:

1. PERFORMANCE METRICS
   ├─ Win rate = won_trades / total_trades
   ├─ Average PnL
   ├─ Total return
   ├─ Sharpe ratio
   └─ Max drawdown

2. TRADE DISTRIBUTION
   ├─ Win distribution
   ├─ Loss distribution
   ├─ By symbol
   └─ By bot

3. EFFICIENCY
   ├─ efficiency = pnl / max_profit
   │  └─ How much of the max favorable move we captured
   ├─ Trades achieving MFE
   └─ Trades hitting SL

4. TIME SERIES
   ├─ Equity curve
   ├─ Win/loss by date
   ├─ Trade frequency
   └─ Average duration

5. PER-SYMBOL PERFORMANCE
   ├─ Win rate per symbol
   ├─ Average PnL per symbol
   └─ Volume per symbol
```

---

## Multi-Bot Architecture

### Independence Principle

```
Each bot runs as independent process:

┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│   BOT 1      │    │   BOT 2      │    │   BOT 3      │
│ PID: 1001    │    │ PID: 1002    │    │ PID: 1003    │
├──────────────┤    ├──────────────┤    ├──────────────┤
│ Single loop  │    │ Single loop  │    │ Single loop  │
│ 7s cycle     │    │ 7s cycle     │    │ 7s cycle     │
├──────────────┤    ├──────────────┤    ├──────────────┤
│ Config:      │    │ Config:      │    │ Config:      │
│  bot_1.py    │    │  bot_2.py    │    │  bot_3.py    │
│  strategy:   │    │  strategy:   │    │  strategy:   │
│  mirror      │    │  reverse     │    │  time_based  │
├──────────────┤    ├──────────────┤    ├──────────────┤
│ Private:     │    │ Private:     │    │ Private:     │
│ pos_1.json   │    │ pos_2.json   │    │ pos_3.json   │
│ trail_1.json │    │ trail_2.json │    │ trail_3.json │
│ bot_1.log    │    │ bot_2.log    │    │ bot_3.log    │
│ MT5 acct 623 │    │ MT5 acct 624 │    │ MT5 acct 625 │
│ terminal /1  │    │ terminal /2  │    │ terminal /3  │
└──────────────┘    └──────────────┘    └──────────────┘
     │                    │                    │
     └────┬───────────────┼────────────────┬──┘
          │ IPC: signals.json              │
          │ (read-only for each bot)       │
          │ (written by signal_fetcher)    │
          │                                │
          ├ Shared output (append-only):   │
          │ trades_history.jsonl           │
          │                                │
          └ No other shared state
```

**Key Points:**

- **Process isolation:** Each bot is separate OS process
- **Terminal isolation:** Each bot connected to different MT5 account
- **File isolation:** Each bot uses bot-specific file names
- **Configuration isolation:** Each bot loads its own config
- **Strategy isolation:** Each bot runs own strategy
- **No locking required:** Natural isolation prevents conflicts

### Concurrency Safety

```
NO RACE CONDITIONS because:

1. SIGNALS.JSON (shared read-only)
   ├─ Written atomically by signal_fetcher
   ├─ Temp file → os.replace() (atomic)
   ├─ All bots read safely (no write conflicts)
   └─ Each bot sees consistent snapshot

2. POSITION FILES (per-bot)
   ├─ Bot 1 only reads/writes positions_store_bot_1.json
   ├─ Bot 2 only reads/writes positions_store_bot_2.json
   ├─ Bot 3 only reads/writes positions_store_bot_3.json
   └─ ZERO contention (each bot has own file)

3. TRADES_HISTORY.JSONL (append-only)
   ├─ Each bot appends one line per closed trade
   ├─ Append operations are atomic at filesystem level
   ├─ No interleaving of lines (OS guarantees)
   └─ No corruption possible

4. MT5 ACCOUNTS (separate accounts)
   ├─ Bot 1 → Account 24446623
   ├─ Bot 2 → Account 24446624
   ├─ Bot 3 → Account 24446625
   └─ Broker prevents position mixing (different accounts)

5. LOGS (per-bot)
   ├─ Bot 1 writes to bot_1.log
   ├─ Bot 2 writes to bot_2.log
   ├─ Bot 3 writes to bot_3.log
   └─ No log conflicts (separate files)
```

### Concurrency Example

```
SCENARIO: All 3 bots running simultaneously

T=0s:
├─ signal_fetcher starts
└─ Bot 1,2,3 wait on startup

T=3s:
├─ signal_fetcher: fetch website, parse, compute hash, write signals.json
├─ signals.json = {version: 1, hash: abc123, signals: [EURUSD, GBPUSD]}
└─ All bots ready to read

T=7s: BOT 1 CYCLE
├─ Read signals.json (version 1, hash abc123)
├─ Transform per mirror strategy
├─ Execute: open EURUSD BUY
├─ Update positions_store_bot_1.json
└─ Log to bot_1.log

T=7s: BOT 2 CYCLE (simultaneously)
├─ Read signals.json (same version 1, hash abc123)
├─ Transform per reverse strategy (invert!)
├─ Execute: open EURUSD SELL (opposite)
├─ Update positions_store_bot_2.json
└─ Log to bot_2.log

T=7s: BOT 3 CYCLE (simultaneously)
├─ Read signals.json (same version 1, hash abc123)
├─ Transform per time_based strategy
├─ Execute: open signal based on IST hour
├─ Update positions_store_bot_3.json
└─ Log to bot_3.log

RESULT:
├─ All 3 bots executed independently
├─ Each bot opened own position (different MT5 accounts)
├─ No conflicts, no races, no corruption
└─ Complete isolation despite concurrent execution

T=10s: signal_fetcher
├─ Fetch website again
├─ If new signals: version=2, hash=different
├─ atomic_write(signals.json, new_payload)
└─ All bots will see new signals next cycle

T=14s: BOT 1 CYCLE
├─ Read signals.json (version 2, hash=different)
├─ Hash != last_hash, so proceed
├─ Execute new trades
└─ Continue...
```

---

## Failure Handling

### Network Failures (Scraper)

```
FAILURE: Cannot reach website (proxy error, timeout, etc.)

HANDLING:
──────────

scraper.py:
├─ Attempt 1: Try proxy 1
├─ On error: mark_proxy_failed(proxy1)
├─ Attempt 2: Try proxy 2
├─ Attempt 3: Try proxy 3
├─ All failed: return None
└─ MAX_RETRIES = 3

signal_fetcher.py:
├─ On scraper.fetch_page() → None:
│  ├─ Don't panic
│  ├─ Keep previous signals.json state as-is
│  ├─ Update status field to "ERROR"
│  └─ Continue next cycle (retry in 10s)
│
└─ This ensures signals.json always VALID (even if stale)

Bots:
├─ Read signals.json
├─ Check status field
├─ If "ERROR":
│  ├─ Print warning
│  ├─ Use last known good signals
│  └─ Continue trading
│
└─ No disruption to bot cycles
```

### Parser Failures

```
FAILURE: Website HTML changed format, parser can't extract signals

HANDLING:
──────────

parser.py:
├─ Try parse_signals(html)
├─ On exception:
│  ├─ Log error to stderr
│  └─ Return empty list []
│
└─ Graceful degradation

signal_fetcher.py:
├─ If signals_list = []:
│  ├─ Set status = "ERROR"
│  ├─ Keep previous signals in signals.json
│  └─ Continue (retry next cycle)
│
└─ Older signals don't disappear

Bots:
├─ If signals empty but not stale (old version):
│  ├─ Continue previous signals (open old positions)
│  └─ Try to close stale positions if they disappeared
│
└─ No crashes, graceful degradation
```

### MT5 Connection Failures

```
FAILURE: MT5 terminal not running, login failed, order rejected

HANDLING:
──────────

TERMINAL NOT RUNNING:
├─ init_mt5() in trader.py
├─ mt5.initialize() returns False
├─ Launch subprocess.Popen(MT5_EXE)
├─ Wait 10 seconds
├─ Retry mt5.initialize()
└─ If still fails: raise RuntimeError (crash bot, restart)

ORDER REJECTION:
├─ open_trade() calls mt5.order_send()
├─ result.retcode != 10009 (TRADE_RETCODE_DONE)
├─ Retry logic: for attempt in range(MAX_RETRIES=3)
├─ Backoff: sleep between retries
├─ Eventually: return (False, None)
└─ Bot marks trade as failed, continues

POSITION LOOKUP FAILURE:
├─ mt5.positions_get(mag=777) fails
├─ Gracefully handle None result
├─ Reconstruct from positions_store backup
└─ LOG: "Reconstructed positions from store"
```

### File I/O Failures

```
FAILURE: positions_store_bot_N.json cannot be written (disk full, permissions)

HANDLING:
──────────

WRITE FAILURE:
├─ atomic_write_json() attempts write
├─ tempfile.mkstemp() fails or os.replace() fails
├─ Function returns False
├─ Caller checks return value:
│  ├─ If False: log error, continue
│  └─ Position state in-memory is intact
│
└─ Next cycle tries persist again (retry pattern)

READ FAILURE:
├─ safe_read_json(file, max_retries=3)
├─ Attempt 1: Try read
├─ On error: sleep 0.1s
├─ Attempt 2-3: Retry with backoff
├─ Eventually: return None (no data available)
├─ Caller:
│  ├─ If positions = None → load from MT5
│  └─ If processed_signals = None → start fresh (safer: more caution)
│
└─ Graceful fallback

BOTH FAIL:
├─ positions_store_bot_N.json corrupted + backup missing
├─ Bot calls: reconstruct_positions_from_mt5()
├─ Matches MT5 live positions to signals (fuzzy matching)
├─ Recreates position_store from scratch
├─ Continues trading with reconstructed state
└─ Complete recovery possible
```

### Stale Data Handling

```
FAILURE: signals.json not updated for 2 minutes (fetcher hung or crashed)

HANDLING:
──────────

DETECTION:
├─ Each bot reads signals.json
├─ Checks timestamp field
├─ age = now - timestamp
├─ Dynamic stale threshold = 2 × SIGNAL_FETCHER_INTERVAL (e.g., 20s)
├─ If age > threshold:
│  ├─ Signal data is stale
│  └─ LOG: "[STALE] {age}s > {threshold}s"
│
└─ Cycle skipped (don't open trades on stale signals)

CONSEQUENCE:
├─ No new trades opened (safe, don't guess)
├─ Existing positions stay open (risk management still runs)
├─ Virtual SL and trailing stops still monitor
├─ Max loss still enforced
└─ Next cycle re-evaluates when fetcher recovers

RECOVERY:
├─ If signal_fetcher restarts → publishes new signals
├─ Bots detect new version or hash
├─ Resume trading normally
└─ No manual intervention needed
```

---

## System Guarantees

### Deduplication Guarantees

```
✔ LAYER 1: Content Hash (SHA256)
  ├─ If signal_content unchanged: hash same → skip cycle
  └─ Prevents re-open of identical signal multiple times

✔ LAYER 2: Virtual SL Cooldown (Lifecycle-driven)
  ├─ If bot closes position: mark key temporarily closed
  └─ Reopen only when signal disappears (debounced)

✔ LAYER 3: Position Store (State tracking)
  ├─ If key already in positions_store: skip
  └─ Don't duplicate positions already tracked

✔ LAYER 4: Processed Signals (24h history)
  ├─ If signal_id processed < 24h ago: skip
  └─ Prevents re-open after restart

RESULT:
└─ Same signal CANNOT execute twice (4-layer protection)
```

### Isolation Guarantees

```
✔ FILE ISOLATION
  ├─ Each bot uses bot-specific files: positions_store_bot_N.json
  ├─ No concurrent access to same file
  └─ Race condition: impossible

✔ MT5 ACCOUNT ISOLATION
  ├─ Each bot connects to different account: 24446623, 24446624, 24446625
  ├─ Broker prevents position mixing
  └─ Account level: complete isolation

✔ PROCESS ISOLATION
  ├─ Each bot is independent OS process (separate PID)
  ├─ Separate memory space
  └─ One bot crash doesn't affect others

✔ VALUE ISOLATION
  ├─ Signals.json is read-only from bot perspective
  ├─ Atomic writes by fetcher ensure consistency
  └─ Bots never see partial writes

RESULT:
└─ Bots cannot interfere (complete isolation)
```

### Persistence Guarantees

```
✔ ATOMIC WRITES (Crash-safe)
  ├─ Write to temp file
  ├─ Close file
  ├─ os.replace(temp, final) ← ATOMIC
  └─ On crash: either old or new file survives, no corruption

✔ STATE RECOVERY
  ├─ All state on disk in bot-specific files
  ├─ Load on startup (StateRecovery class)
  ├─ Validate consistency
  └─ Resume with full context

✔ RESTART SAFETY
  ├─ Kill bot, restart bot
  ├─ Loads same state from disk
  ├─ Resumes from same position
  └─ Deterministic recovery

RESULT:
└─ No in-process state is lost (always recoverable)
```

### Execution Guarantees

```
✔ DETERMINISM
  ├─ Same signals, same strategy, same MT5 state → same execution
  ├─ All transformations are pure functions (no side effects)
  ├─ Timestamps deterministic (not wall-clock dependent)
  └─ Reproducible behavior

✔ NO DOUBLE EXECUTION
  ├─ 4-layer dedup prevents same signal opening twice
  ├─ Counter diff logic prevents artificial duplicates
  └─ Processed signals tracking prevents restart re-execution

✔ ORDER PRESERVATION
  ├─ Signals processed in order received
  ├─ No out-of-order execution
  └─ Position store tracks all tickets

RESULT:
└─ Execution is predictable and auditable
```

---

## Known Limitations

### 1. Website Format Dependency

```
LIMITATION:
─────────────
System depends on website HTML format for signals

IMPACT:
├─ If website redesigns: parser fails
├─ If HTML element names change: extraction fails
└─ No signals published → bots halt (can't trade)

MITIGATION:
├─ Parser tries multiple fallback selectors
├─ Graceful degradation on parse error
├─ Alert logs when format changes
└─ Manual update needed (not auto-adaptive)

REALITY:
└─ This is inherent to scraping-based signals (not a flaw)
```

### 2. Proxy Dependency

```
LIMITATION:
─────────────
System relies on free proxy API (ProxyScrape)

IMPACT:
├─ Free proxies are unreliable
├─ Low uptime, frequent failures
├─ Rate limiting possible
└─ Website may block proxies

MITIGATION:
├─ Round-robin and random proxy rotation
├─ Blacklist failed proxies (temp 60s TTL)
├─ Retry logic (max 3 attempts)
├─ Graceful failure (keep old signals)

REALITY:
├─ Works in practice (low dependency on single proxy)
└─ Paid proxy API would be more reliable
```

### 3. Network Latency

```
LIMITATION:
─────────────
Order execution subject to network delays

IMPACT:
├─ Order sent at t=100ms, broker receives at t=150ms
├─ Price moved 5 pips in 50ms (possible in volatile markets)
├─ Actual execution price ≠ signal price
└─ Slippage is real cost

MITIGATION:
├─ Adaptive deviation: max(50, 2× spread) for non-JPY
├─ Virtual SL: spread-aware SL management
├─ Price drift validation: skip if > 5 pips from signal
└─ Trailing stops: lock in gains gradually

REALITY:
├─ Slippage is inherent to any order-based system
└─ Mitigation reduces impact, doesn't eliminate it
```

### 4. MT5 Availability

```
LIMITATION:
─────────────
System cannot trade if MT5 terminal offline

IMPACT:
├─ Terminal crash: no new orders
├─ Network disconnect: lost connection
├─ Broker shutdown (maintenance): closed
└─ No trades during downtime

MITIGATION:
├─ Auto-launch MT5 terminal if crashed
├─ Retry connection logic
├─ Log connection failures
└─ Manual restart needed for extended outages

REALITY:
├─ MT5 very stable in practice
└─ Outages rare (typically <1h per month)
```

### 5. Capital Allocation

```
LIMITATION:
─────────────
System doesn't allocate capital dynamically

IMPACT:
├─ Fixed volume per trade (e.g., 0.01 lots)
├─ Doesn't scale based on account equity
├─ Doesn't reduce on losing streaks
└─ No position sizing logic

MITIGATION:
├─ Manual config adjustment: change TRADE_VOLUME in config
├─ Restart bot: picks up new volume
└─ Monitor equity: reduce volume if needed

FUTURE:
├─ Could implement Kelly criterion (position sizing)
└─ Could implement dynamic risk-based scaling
```

### 6. Risk Management Limitations

```
LIMITATION:
─────────────
Virtual SL is best-effort, not guaranteed

IMPACT:
├─ If MT5 connection lost: virtual SL can't close
├─ If price gaps (gap risk): virtual SL may be too late
├─ If disconnection: position still open on broker
└─ Not equivalent to hard stop loss

MITIGATION:
├─ Broker SL is always active (safety net)
├─ Reconnection logic re-opens positions
├─ Regular monitoring of discrepancies
└─ Keep close eye during volatile hours

REALITY:
├─ This is inherent to soft stops vs broker SL
└─ Broker SL is ultimate protection
```

### 7. Signal Quality

```
LIMITATION:
─────────────
System quality depends entirely on signal quality

IMPACT:
├─ If signals are bad: bot loses money
├─ If signals are random: bot breaks even minus spreads
├─ No internal signal generation
├─ System is neutral (executes what it's told)

ASSUMPTION:
└─ Signals are worthwhile (positive expectancy)

REALITY:
├─ Garbage in → garbage out
└─ GIGO principle applies
```

---

## Summary

This Multi-Bot Trading System is a **production-grade trading platform** that:

1. **Fetches signals** from a website with proxy rotation and error handling
2. **Transforms signals** per strategy (Mirror, Reverse, Time-Based)
3. **Executes trades** via MT5 with retry logic and validation
4. **Manages risk** via virtual SL, trailing stops, and max loss
5. **Isolates bots** completely via file system and MT5 accounts
6. **Tracks analytics** with MFE/MAE and persistent history
7. **Persists state** atomically to recover from crashes
8. **Deduplicates** signals via 4-layer protection

**Architecture Principles:**
- **Simplicity:** Counter diff logic is elegant and foolproof
- **Safety:** Atomic operations prevent corruption
- **Isolation:** No shared state between bots
- **Reliability:** Graceful failure handling everywhere
- **Auditability:** Every decision logged and traceable

**Guarantee:** The system maintains bot state = website state, using only state that can be recovered from disk, with deterministic behavior across restarts and concurrent execution.

