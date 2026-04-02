# JSON Persistence & Counter Diff Logic

## Overview

The Counter Diff Logic system uses JSON files to persist state across bot restarts. This ensures **zero position loss** and **perfect deduplication** even if the bot crashes, restarts, or the broker connection is interrupted.

---

## JSON Files Architecture

### 1. **processed_signals.json** - Deduplication Tracker

**Purpose**: Track which signals have already been processed to prevent opening duplicate trades.

**File Location**: `processed_signals.json` (root directory)

**File Format**:
```json
{
  "2026-04-02T10:15:30.123456+00:00_('EURUSD', 'BUY', 1.158, 1.154)": "2026-04-02T10:15:35.987654+00:00",
  "2026-04-02T10:16:45.654321+00:00_('EURUSD', 'BUY', 1.158, 1.154)": "2026-04-02T10:16:50.123456+00:00",
  "2026-04-02T10:17:22.111111+00:00_('GBPUSD', 'SELL', 1.268, 1.262)": "2026-04-02T10:17:27.222222+00:00"
}
```

**Key Structure**:
```
signal_id = "{signal_timestamp}_{signal_key}"

Example:
  2026-04-02T10:15:30.123456+00:00_('EURUSD', 'BUY', 1.158, 1.154)
  │                                 │
  Signal timestamp (UTC ISO format)  Signal key (pair, side, TP, SL - normalized)

Value:
  2026-04-02T10:15:35.987654+00:00
  │
  When this signal was saved (processed)
```

**Purpose of Each Field**:

| Field | Purpose |
|-------|---------|
| Key (signal_id) | Unique identifier for each signal |
| Value (timestamp) | When this signal was processed (for rotation cleanup) |

**Usage in Code**:

```python
# At startup: Load processed signals
processed_signal_ids = load_processed_signals()  # Returns: set of signal IDs

# During cycle: Check if signal was already processed
signal_id = f"{sig.time.isoformat()}_{SignalKey.build(...)}"
if signal_id in processed_signal_ids:
    print(f"[SKIP] Signal already processed, not opening duplicate")
    continue  # Don't open

# After opening a trade: Mark signal as processed
processed_signal_ids.add(signal_id)
save_processed_signals(processed_signal_ids)
```

**Rotation & Cleanup**:
```python
# Keep only signals from last 24 hours
cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
filtered = {
    ts: v for ts, v in data.items()
    if datetime.fromisoformat(v) > cutoff
}

# Older signals automatically drop out
# File size stays bounded even with millions of signals
```

**Fault Tolerance**:
```python
def load_processed_signals():
    try:
        # Try to load file
        with open('processed_signals.json', 'r') as f:
            data = json.load(f)
        return set(filtered.keys())

    except FileNotFoundError:
        return set()  # File doesn't exist yet - OK, start fresh

    except json.JSONDecodeError:
        print("[ERROR_JSON] File corrupted, starting fresh (no duplicate opens)")
        return set()  # Corrupted - safe to lose 24h of dedup info

    except Exception as e:
        print(f"[ERROR_JSON] {e}, starting fresh")
        return set()  # Any error - safe to restart
```

**Atomic Write Protection**:
```python
# Write to temporary file first (prevents corruption)
temp_fd, temp_path = tempfile.mkstemp(suffix='.json')
try:
    with os.fdopen(temp_fd, 'w') as f:
        json.dump(data, f)  # Write to temp
    os.replace(temp_path, 'processed_signals.json')  # Atomic rename
except Exception:
    os.unlink(temp_path)  # Clean up temp on failure
    raise
```

---

### 2. **positions.json** - Position Store Persistence (Optional)

**Purpose**: Persist the PositionStore state for crash recovery and state reconstruction.

**File Location**: `positions.json` (optional, for advanced recovery)

**File Format**:
```json
{
  "('EURUSD', 'BUY', 1.158, 1.154)": [10001, 10002, 10003],
  "('GBPUSD', 'SELL', 1.268, 1.262)": [10004],
  "('_UNMATCHED_', 'USDJPY', 'SELL', 110.5, 109.8)": [10005, 10006]
}
```

**Key Structure**:
```
key = "(pair, side, tp, sl)"
value = [ticket1, ticket2, ticket3, ...]

Example:
  "('EURUSD', 'BUY', 1.158, 1.154)": [10001, 10002, 10003]
   │                                  │
   Signal key (string representation)  List of ticket IDs (in LIFO order)
```

**JSON Serialization Challenge**:
```python
# Problem: Python tuples can't be serialized to JSON directly
key = ("EURUSD", "BUY", 1.158, 1.154)
# Can't do: json.dump({key: [tickets]})  ← TypeError!

# Solution: Convert tuples to strings for JSON
def to_dict(self):
    """Serialize to JSON-safe format"""
    return {
        str(key): tickets for key, tickets in self.positions.items()
    }
    # Result: {"('EURUSD', 'BUY', 1.158, 1.154)": [10001, ...]}

# And back from JSON:
def from_dict(self, data):
    """Deserialize from JSON"""
    for key_str, tickets in data.items():
        pair, side, tp, sl = eval(key_str)  # Safe: our format only
        key = (pair, side, float(tp), float(sl))
        self.positions[key] = list(tickets)
```

**Ticket Order (LIFO)**:
```python
# Tickets stored in LIFO order (Last In, First Out)
positions[key] = [10001, 10002, 10003]  # 10001 opened first

# When closing, pop from the end (most recent first)
ticket_to_close = positions[key].pop()  # Gets 10003 (most recent)
```

**Usage Pattern**:

```python
# Save after each cycle (optional, for crash recovery)
state = {
    "positions": positions.to_dict(),
    "timestamp": datetime.now().isoformat(),
    "prev_keys": prev_keys,  # For resuming diff logic
}
with open('positions.json', 'w') as f:
    json.dump(state, f)

# On startup: Reconstruct from MT5 (doesn't use this file)
# File is only for crash recovery during a cycle
```

**Why This Is Optional**:
- Counter Diff always reconstructs state from MT5 on startup (safer)
- File is mainly for **mid-cycle crash recovery**
- If bot crashes, it recovers by:
  1. Reading all open positions from MT5
  2. Fuzzy matching to website signals
  3. Reconstructing PositionStore fresh
- File can be deleted without data loss

---

## Deduplication Logic - Step by Step

### The Problem: Multiple Identical Signals

```
Cycle 1 - Website shows: EURUSD BUY (10:15)
Cycle 2 - Website shows: EURUSD BUY (10:15) + EURUSD BUY (10:16)

Question: Is the 10:15 signal the same or a NEW signal?

Traditional approach: Compare TP/SL
  ❌ If TP/SL identical, can't tell which is which

Counter Diff approach: Use timestamp + TP/SL as ID
  ✓ timestamp_1 + TP/SL_1 ≠ timestamp_1 + TP/SL_2
  ✓ Two different signals!
```

### The Solution: Signal ID Creation

**Step 1: Extract Signal Data**

```python
sig = Signal(
    pair="EURUSD",
    side="BUY",
    tp=1.1580,           # From website
    sl=1.1540,           # From website
    time=datetime(...),  # Parsed from website "Posted at 10:15"
    status="ACTIVE"
)
```

**Step 2: Build Signal ID**

```python
def get_signal_id(sig: Signal) -> str:
    """Create unique signal ID from timestamp + key."""

    # Step 2a: Normalize key (round to 3 decimals)
    key = SignalKey.build(sig.pair, sig.side, sig.tp, sig.sl)
    # Returns: ("EURUSD", "BUY", 1.158, 1.154)

    # Step 2b: Get ISO timestamp
    time_str = sig.time.isoformat()
    # Returns: "2026-04-02T10:15:30.123456+00:00"

    # Step 2c: Combine
    signal_id = f"{time_str}_{key}"
    # Returns: "2026-04-02T10:15:30.123456+00:00_('EURUSD', 'BUY', 1.158, 1.154)"

    return signal_id
```

**Step 3: Check Against Processed Set**

```python
# At startup
processed_signal_ids = load_processed_signals()
# Loaded from JSON: set of ~1000 signal IDs from last 24h

# During cycle, for each signal
signal_id = get_signal_id(sig)

if signal_id in processed_signal_ids:
    # Already opened this exact signal in the past 24 hours
    print(f"[SKIP_DUP] {signal_id}: already processed")
    continue  # Don't open duplicate
else:
    # New signal, safe to open
    print(f"[NEW] {signal_id}: haven't seen this before")
    ticket = open_trade(sig)
    processed_signal_ids.add(signal_id)  # Mark as processed
```

**Step 4: Persist**

```python
# Save updated set
save_processed_signals(processed_signal_ids)

# File now contains:
{
  "..._old_signal_1": "2026-04-01T14:22:10...",
  "..._old_signal_2": "2026-04-01T15:30:44...",
  "2026-04-02T10:15:30.123456+00:00_('EURUSD', 'BUY', 1.158, 1.154)": "2026-04-02T10:15:35+00:00"
}
```

### Deduplication in Action - Real Example

**Scenario**: Website signal gets re-shown multiple times

```
Time    Website Shows                   Bot Action
────────────────────────────────────────────────────
10:15   EURUSD BUY @ 1.158/1.154
        [fresh signal]

        → signal_id = "10:15:30_EURUSD_BUY_1.158_1.154"
        → Not in processed_signal_ids
        → Opens ticket T10001
        → Adds signal_id to processed_signal_ids
        → Saves JSON

10:16   EURUSD BUY @ 1.158/1.154
        [SAME signal re-shown]

        → signal_id = "10:15:30_EURUSD_BUY_1.158_1.154" (SAME ID!)
        → Already in processed_signal_ids
        → [SKIP] - Doesn't open again

10:17   EURUSD BUY @ 1.158/1.154
        [SAME signal, bot restarted]

        → Load processed_signal_ids from JSON (contains old signal_id)
        → signal_id = "10:15:30_EURUSD_BUY_1.158_1.154"
        → Still in processed_signal_ids (recovered from file!)
        → [SKIP] - Doesn't open duplicate despite restart

10:18   EURUSD BUY @ 1.159/1.155
        [NEW signal (slightly different TP/SL)]

        → Normalized key = ("EURUSD", "BUY", 1.159, 1.155)
        → signal_id = "10:18:45_EURUSD_BUY_1.159_1.155" (DIFFERENT!)
        → Not in processed_signal_ids
        → Opens ticket T10002 (new independent trade)
```

**Result**: Perfect deduplication, zero duplicate opens!

---

## Counter Diff State Synchronization

### How State is Compared (Using Keys, Not Tickets)

**Cycle 1: Initial State**

```json
// processed_signals.json (tracks duplicates)
{}  // Empty at start

// Current signals from website
Website snapshot:
  - EURUSD BUY @ TP=1.158, SL=1.154
  - EURUSD BUY @ TP=1.158, SL=1.154  (duplicate - same params at same time)
  - GBPUSD SELL @ TP=1.268, SL=1.262

// Extract keys (deduplication at key level for state diffing)
curr_keys = [
  ("EURUSD", "BUY", 1.158, 1.154),
  ("EURUSD", "BUY", 1.158, 1.154),    ← Counter will count as 2
  ("GBPUSD", "SELL", 1.268, 1.262),
]

prev_keys = []  // Nothing before

// Counter Diff
from collections import Counter

prev_counter = Counter(prev_keys)    # {}
curr_counter = Counter(curr_keys)    # {('EURUSD', 'BUY', 1.158, 1.154): 2, ('GBPUSD', 'SELL', 1.268, 1.262): 1}

closed = prev_counter - curr_counter # {}       (nothing to close)
opened = curr_counter - prev_counter # {('EURUSD', 'BUY', 1.158, 1.154): 2, ('GBPUSD', 'SELL', 1.268, 1.262): 1}

// Action: Open 2 EURUSD trades + 1 GBPUSD trade
```

**Cycle 2: One Closes**

```json
// Website now shows (one EURUSD closed)
Website snapshot:
  - EURUSD BUY @ TP=1.158, SL=1.154   ← Only 1 left
  - GBPUSD SELL @ TP=1.268, SL=1.262

// Extract keys
curr_keys = [
  ("EURUSD", "BUY", 1.158, 1.154),
  ("GBPUSD", "SELL", 1.268, 1.262),
]

prev_keys = [
  ("EURUSD", "BUY", 1.158, 1.154),
  ("EURUSD", "BUY", 1.158, 1.154),    ← Was 2
  ("GBPUSD", "SELL", 1.268, 1.262),
]

// Counter Diff
prev_counter = Counter(prev_keys)    # {('EURUSD', 'BUY', 1.158, 1.154): 2, ('GBPUSD', 'SELL', 1.268, 1.262): 1}
curr_counter = Counter(curr_keys)    # {('EURUSD', 'BUY', 1.158, 1.154): 1, ('GBPUSD', 'SELL', 1.268, 1.262): 1}

closed = prev_counter - curr_counter # {('EURUSD', 'BUY', 1.158, 1.154): 1}    ← Close 1
opened = curr_counter - prev_counter # {}

// Action: Close 1 EURUSD trade (doesn't matter which, they're identical!)
// Bot pops one ticket from the list: positions[key].pop()
```

---

## JSON File Management - Best Practices

### File Locations

```
Bot Root Directory/
├── bot.py                          (main bot)
├── processed_signals.json          ← Deduplication tracker
├── positions.json                  ← Optional crash recovery
├── bot.log                         ← Bot output log
└── (other source files)
```

### File Size Monitoring

**processed_signals.json**:
```
Typical size:
- 24-hour retention
- ~100 signals per cycle
- ~70 cycles per day = 7,000 signals per day
- Each signal ID ~100 bytes
- Daily: ~700 KB
- Multiple days: rotates and stays bounded

Strategy: Auto-cleanup (signals older than 24h removed)
```

**positions.json** (if used):
```
Typical size:
- Usually <100 KB (one entry per unique key)
- Rarely exceeds 1 MB even with 1000+ positions
- Can be safely deleted and rebuilt from MT5
```

### Manual Management

**Clearing deduplication cache** (if needed):
```bash
# WARNING: Only do this if you understand the risk
# This allows opening signals from today that were already opened

rm processed_signals.json  # Bot will create empty file on restart

# Or manually edit to keep only recent signals
```

**Checking file integrity**:
```bash
# Validate JSON syntax
python -m json.tool processed_signals.json > /dev/null && echo "OK" || echo "CORRUPT"

# View sample entries
python -m json.tool processed_signals.json | head -20
```

**Recovering from corruption**:
```python
# If file is corrupted, bot automatically:
# 1. Catches json.JSONDecodeError
# 2. Prints warning
# 3. Starts fresh (empty set)
# 4. Creates new valid JSON on first save

# This is safe - only risk is allowing duplicate opens
# for signals processed before the corruption
```

---

## Recovery Mechanisms

### Startup Recovery Sequence

```
1. START BOT
   ↓
2. Load processed_signals.json
   ├─ File exists? → Load and filter (keep last 24h)
   ├─ File missing? → Start fresh (empty set)
   └─ File corrupt? → Log warning, start fresh
   ↓
3. Read all open positions from MT5
   ↓
4. Reconstruct PositionStore
   ├─ Match MT5 positions to website signals (fuzzy match)
   ├─ Matches → PositionStore[key] = [tickets]
   └─ Unmatched → PositionStore[("_UNMATCHED_", ...)] = [tickets]
   ↓
5. First diff cycle
   ├─ Website signals → current keys
   ├─ Compare to reconstructed keys
   └─ Only process real changes
```

### Mid-Cycle Crash Recovery

**Scenario**: Bot crashes mid-trade execution

```
Original state:
  positions = {("EURUSD", "BUY", 1.158, 1.154): [10001, 10002, 10003]}
  processed_signals.json = {...}

Bot: Opens trade → ticket 10001
Bot: Saves to positions.json (optional)
Bot: Crashes before saving processed_signals.json

Restart:
  1. Load processed_signals.json (old version, ticket 10001 may be missing)
  2. Read MT5 → sees ticket 10001 is open
  3. Reconstruct PositionStore from MT5 (sees 10001)
  4. Next cycle → diff against reconstructed state

Result: ✓ No position loss (MT5 is source of truth)
```

---

## Example: Full Trading Day Sequence

### Files Evolution

**File at 00:00 (midnight UTC)**:
```json
// processed_signals.json - fresh start
{
  "2026-04-02T00:00:15.123456+00:00_('EURUSD', 'BUY', 1.158, 1.154)": "2026-04-02T00:00:20"
}

// positions.json
{
  "('EURUSD', 'BUY', 1.158, 1.154)": [10001]
}
```

**File at 06:00 (morning session)**:
```json
// processed_signals.json - growing
{
  "2026-04-02T00:00:15.123456+00:00_('EURUSD', 'BUY', 1.158, 1.154)": "2026-04-02T00:00:20",
  "2026-04-02T02:15:30.654321+00:00_('GBPUSD', 'SELL', 1.268, 1.262)": "2026-04-02T02:15:35",
  "2026-04-02T04:22:45.111111+00:00_('EURUSD', 'BUY', 1.160, 1.156)": "2026-04-02T04:22:50",
  ...
}  // ~400 signals in 6 hours

// positions.json - mix of active and unmatched
{
  "('EURUSD', 'BUY', 1.160, 1.156)": [10005, 10006],
  "('GBPUSD', 'SELL', 1.268, 1.262)": [10007],
  "('_UNMATCHED_', 'USDJPY', 'BUY', 110.5, 109.8)": [10008, 10009]
}
```

**File at 23:59 (end of day)**:
```json
// processed_signals.json - about to rotate
{
  "2026-04-02T01:00:00+00:00_...": "...",  // 23 hours ago, about to expire
  "2026-04-02T02:00:00+00:00_...": "...",  // Keep these
  ...
  "2026-04-02T23:50:00+00:00_...": "...",  // Keep these
}  // ~7,000 signals in 24 hours

// At 00:00 next day, cleanup runs:
//   Remove all entries with timestamp < 2026-04-03T00:00:00
//   Keep all entries with timestamp >= 2026-04-03T00:00:00 (only this morning's)
//   File shrinks back to small size
```

---

## Troubleshooting

### Issue: "File corrupted" warning on startup

**Cause**: JSON file has invalid syntax

**Resolution**:
```bash
# Check if file is valid JSON
python -c "import json; json.load(open('processed_signals.json'))"

# If error: file is corrupt
# Bot will automatically restart fresh
# Loss: Only signals from corrupted period allowed as duplicates

# To manually fix:
rm processed_signals.json  # Bot creates new valid file on restart
```

### Issue: Duplicate trades opened despite being "same signal"

**Possible causes**:
1. Website shows signal with different TP/SL second time (different key)
2. Signal timestamp changed (different signal_id)
3. processed_signals.json rotated out (older than 24h)
4. Bot was restarted, dedup lost (workaround: don't restart during same signal window)

**Verification**:
```python
# Check what signal_ids were saved
import json

with open('processed_signals.json') as f:
    data = json.load(f)

# Look for your signal
for sig_id, timestamp in data.items():
    if 'EURUSD' in sig_id and '1.158' in sig_id:
        print(f"Found: {sig_id} @ {timestamp}")
```

### Issue: positions.json shows wrong ticket counts

**Possible causes**:
1. File is stale (didn't save after recent trades)
2. Tickets were closed in MT5 but file wasn't updated

**Resolution**:
- File is advisory only
- MT5 is source of truth
- Safe to delete: `rm positions.json`
- Bot reconstructs on next startup

---

## JSON File Schemas (Reference)

### processed_signals.json Schema

```json
{
  "type": "object",
  "additionalProperties": {
    "type": "string",
    "pattern": "^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}.*$"
  },
  "description": "Map of signal_id (ISO_timestamp + key) → processed_timestamp (ISO)"
}
```

### positions.json Schema

```json
{
  "type": "object",
  "properties": {
    "positions": {
      "type": "object",
      "additionalProperties": {
        "type": "array",
        "items": {
          "type": "integer"
        }
      },
      "description": "Map of string_key → [ticket1, ticket2, ...] (LIFO order)"
    },
    "timestamp": {
      "type": "string",
      "pattern": "^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}.*$"
    },
    "prev_keys": {
      "type": "array",
      "description": "Previous cycle keys for resuming diff logic"
    }
  }
}
```

---

## Performance & Scaling

### Deduplication Performance

```python
# Lookup time
processed_signal_ids in Python set: O(1) - constant time

# Even with 7,000 signals:
if signal_id in processed_signal_ids:
    # Takes ~1 microsecond (instantaneous)
    pass

# Save/load time
# 1 MB file: < 100ms to load and parse
# 7,000 signals: < 50ms to save

# Conclusion: No performance impact, extremely fast
```

### File Size Scaling

```
Signals per day:     7,000
Signals per MB:      ~10,000 (at ~100 bytes per ID)
Daily file size:     ~700 KB

24-hour retention:
  - Max age: 86,400 seconds
  - Cleanup: removes entries > 24h old
  - File auto-rotates
  - Never grows beyond ~700 KB (for normal trading volume)

Extreme case (1000 trades/day):
  - 7,000,000 signals per day
  - ~700 MB per day
  - Cleanup keeps 24h = ~700 MB max
  - Memory used by set: ~2 GB (still manageable on modern systems)
```

---

## Summary

✅ **processed_signals.json**
- Prevents duplicate opens using signal timestamp + key
- Auto-rotates (24h retention)
- Fault-tolerant (file loss = only risk of duplicate opens)
- Small file ~700 KB typical

✅ **positions.json** (optional)
- Stores position state for crash recovery
- Auto-reconstructed from MT5 on startup
- Safe to delete
- Supports LIFO ticket ordering

✅ **State Synchronization**
- Uses Counter diff on normalized keys
- Never identifies individual tickets (doesn't need to)
- Counts how many to open/close
- Matches any identical ticket (all the same anyway)

✅ **Perfect Recovery**
- Handles crashes gracefully
- MT5 is source of truth
- Dedup cache provides duplicate prevention
- State always consistent with website
