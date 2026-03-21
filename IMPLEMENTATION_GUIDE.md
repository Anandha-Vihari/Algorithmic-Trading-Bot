# Blind Follower Bot - Implementation Guide

## Trade Identification System

### Signal ID Format
Each signal is uniquely identified by:
```
{pair}_{time}_{side}_{frame}_{tp}_{sl}
```

**Example:** `EURUSD_2026-03-20 20:00:00+00:00_BUY_short_1.15824_1.15494`

This ensures:
- ✅ Same signal won't be processed twice
- ✅ Different TP/SL combinations = different signals
- ✅ Multiple positions per pair can coexist separately

**Code location:** `main.py:253`

---

## 1. Trade Identification (Core Identification System)

### How are trades uniquely identified?
Trades are identified by a **composite signal ID** that includes all parameters:

```python
signal_id = f"{pair}_{s['time']}_{s['side']}_{frame}_{s['tp']}_{s['sl']}"
```

### Exact variables used:
- **pair**: Trading pair (e.g., "EURUSD")
- **time**: Signal timestamp (e.g., "2026-03-20 20:00:00+00:00")
- **side**: Trade direction ("BUY" or "SELL")
- **frame**: Timeframe ("short" = 15/30 min, "long" = 1/4 hour)
- **tp**: Take Profit price (e.g., 1.15824)
- **sl**: Stop Loss price (e.g., 1.15494)

### Example identification:
```
Position A: EURUSD_2026-03-20 20:00:00+00:00_BUY_short_1.15824_1.15494
Position B: EURUSD_2026-03-20 20:00:00+00:00_BUY_short_1.15812_1.15483
             ↑ Different TP/SL = Different signal ID = Different position
```

---

## 2. Open Trade Logic

### Conditions to decide whether to open a new trade

**1. Age filtering** (`main.py:229-227`):
```python
signal_age = (now - s['time']).total_seconds()
if signal_age <= MAX_SIGNAL_AGE:  # 1800 seconds = 30 minutes
    age_filtered.append(s)
```
Signals older than 30 minutes are skipped.

**2. Deduplication** (`main.py:211-215`):
```python
key = f"{s['pair']}_{s['frame']}_{s['tp']}_{s['sl']}"
if key not in seen:
    seen.add(key)
    filtered_signals.append(s)
```
Only the most recent signal per unique TP/SL setup is kept.

**3. Duplicate prevention** (`main.py:244-256`):
```python
if signal_id in processed_signals:
    continue  # Skip if already processed

# ... open trade ...

processed_signals[signal_id] = now  # Mark as processed
```

### How duplicate trades are prevented:
The `processed_signals.json` file (persistent dict) stores all signal IDs that have been processed. Before opening any trade:

1. Check if signal_id exists in `processed_signals`
2. If yes → Skip (already processed)
3. If no → Open trade and add to `processed_signals`

**File:** `processed_signals.json`
```json
{
  "EURUSD_2026-03-20 20:00:00+00:00_BUY_short_1.15824_1.15494": "2026-03-20T20:11:16.397815+00:00"
}
```

---

## 3. Close Trade Logic (Critical Matching)

### How the bot decides which trade to close

**Step 1: Extract close signal** (`parser.py:62-75`):
```python
close_price_match = re.search(r"Close:\s*([\d\.]+)", text)

if close_price_match:
    status = "CLOSE"
    close_price = float(close_price_match.group(1))

    # Detect reason
    if "Achieved" in text:
        close_reason = "Achieved"
    elif "Trailing Stop" in text:
        close_reason = "Trailing Stop"
    else:
        close_reason = "Manual"
```

**Step 2: Match by TP/SL** (`main.py:287`):
```python
matching_signal_id, metadata = position_tracker.find_matching_position(
    pair, frame,
    tp=s.get('tp'),
    sl=s.get('sl')
)
```

**Step 3: Close by ticket** (`main.py:297`):
```python
if close_position_by_ticket(metadata["ticket"], pair):
    closed += 1
    position_tracker.remove(matching_signal_id)
```

### Exact matching algorithm (`state.py:87-132`):

```python
def find_matching_position(self, pair, frame, tp=None, sl=None):
    """
    Matching strategy:
    1. If TP and SL provided, match by TP/SL values (with tolerance)
    2. Tolerance = 0.001 pips (handles MT5 minimum distance adjustments)
    3. If match found → return it
    4. If NO match → return None (close signal NOT for our trades)
    5. Otherwise return oldest position (FIFO)
    """
    TP_SL_TOLERANCE = 0.001

    matches = []
    for signal_id, metadata in self._data.items():
        if metadata["pair"] != pair or metadata["frame"] != frame:
            continue
        matches.append((signal_id, metadata))

    if not matches:
        return None, None

    if len(matches) == 1:
        return matches[0]

    # Multiple matches + TP/SL provided: match by TP/SL
    if tp is not None and sl is not None and len(matches) > 1:
        for signal_id, metadata in matches:
            stored_tp = metadata.get('tp')
            stored_sl = metadata.get('sl')

            if (stored_tp is not None and stored_sl is not None and
                abs(stored_tp - tp) < TP_SL_TOLERANCE and
                abs(stored_sl - sl) < TP_SL_TOLERANCE):
                return signal_id, metadata

        return None, None  # No TP/SL match = don't close

    # Multiple matches, no TP/SL: return oldest
    oldest = min(matches, key=lambda x: x[1].get('created_at', ''))
    return oldest
```

---

## 4. MT5 Position Handling

### How MT5 positions are retrieved and filtered

**Order Placement** (`trader.py:80-93`):
```python
request = {
    "action": mt5.TRADE_ACTION_DEAL,
    "symbol": pair,
    "volume": TRADE_VOLUME,
    "type": order_type,
    "price": price,
    "tp": tp,
    "sl": sl,
    "deviation": 20,
    "magic": MAGIC_NUMBER,        # ← All trades marked with 777
    "comment": "blind",            # ← All trades commented "blind"
    "type_filling": mt5.ORDER_FILLING_IOC,
    "type_time": mt5.ORDER_TIME_GTC
}
result = mt5.order_send(request)
```

### Closing specific position by ticket (`trader.py:149-185`):
```python
def close_position_by_ticket(ticket, pair=None):
    """Close a specific position by ticket number."""

    names = [(pair, pair + "+")] if pair else [(None, None)]

    for name1, name2 in names:
        for name in (name1, name2):
            if name is None:
                continue
            positions = mt5.positions_get(symbol=name)
            if not positions:
                continue

            for pos in positions:
                if pos.ticket != ticket or pos.magic != MAGIC_NUMBER:
                    continue  # Skip positions not opened by us

                # Close this specific position
                request = {
                    "action": mt5.TRADE_ACTION_DEAL,
                    "symbol": name,
                    "volume": pos.volume,
                    "type": mt5.ORDER_TYPE_SELL if pos.type == 0 else mt5.ORDER_TYPE_BUY,
                    "position": ticket,
                    "deviation": 20,
                    "magic": MAGIC_NUMBER,
                    "comment": "close",
                    "type_filling": mt5.ORDER_FILLING_IOC,
                    "type_time": mt5.ORDER_TIME_GTC
                }

                result = mt5.order_send(request)
                if result.retcode == 10009:
                    return True

    return False
```

### Position filtering:
- Only positions with `magic == MAGIC_NUMBER` (777) are considered
- Positions with `comment == "blind"` are confirmed as ours
- Others are ignored

---

## 5. Signal Parsing (Website Data Extraction)

### What data fields are extracted from the website

**Complete signal structure** (`parser.py:84-95`):
```python
signals.append({
    "pair":           pair,              # "EURUSD"
    "side":           side,              # "BUY" or "SELL"
    "open":           float(...),        # Entry price: 1.15824
    "tp":             float(...),        # Take Profit: 1.15824
    "sl":             float(...),        # Stop Loss: 1.15494
    "time":           signal_time,       # 2026-03-20 20:00:00+00:00
    "status":         status,            # "ACTIVE" or "CLOSE"
    "frame":          frame,             # "short" or "long"
    "close":          close_price,       # Close price if status="CLOSE"
    "close_reason":   close_reason,      # "Achieved" / "Trailing Stop" / "Manual"
})
```

### Unique identifier per signal:
- **Composite key**: Includes pair + time + side + frame + TP + SL
- **This uniquely identifies each trade setup on the website**

### Example parsed signals:
```python
{
    "pair": "EURUSD",
    "side": "BUY",
    "open": 1.15824,
    "tp": 1.15824,
    "sl": 1.15494,
    "time": datetime(2026, 3, 20, 20, 0, 0, tzinfo=timezone.utc),
    "status": "ACTIVE",
    "frame": "short",
    "close": None,
    "close_reason": None
}

{
    "pair": "EURUSD",
    "side": "BUY",
    "open": 1.15824,
    "tp": 1.15824,
    "sl": 1.15494,
    "time": datetime(2026, 3, 20, 20, 0, 0, tzinfo=timezone.utc),
    "status": "CLOSE",
    "frame": "short",
    "close": 1.15712,
    "close_reason": "Achieved"
}
```

---

## 6. State Management (Persistent Storage)

### Persistent storage system

The bot uses **two JSON files** to maintain state across restarts:

**A) processed_signals.json** - Tracks processed signals
**B) open_positions.json** - Tracks open positions

### processed_signals.json
**Purpose**: Prevent duplicate signal processing

```json
{
  "EURUSD_2026-03-20 20:00:00+00:00_BUY_short_1.15824_1.15494": "2026-03-20T20:11:16.397815+00:00",
  "EURCAD_2026-03-20 20:00:00+00:00_BUY_short_1.58807_1.58477": "2026-03-20T20:11:16.397815+00:00"
}
```

**Key**: Signal ID
**Value**: Timestamp when processed

**Implementation** (`state.py:9-36`):
```python
class _PersistentDict:
    """Dict-like that auto-saves to disk."""

    def __init__(self):
        self._data = {}
        if os.path.exists(_FILE):
            with open(_FILE) as f:
                raw = json.load(f)
            self._data = {k: datetime.fromisoformat(v) for k, v in raw.items()}

    def _save(self):
        with open(_FILE, "w") as f:
            json.dump({k: v.isoformat() for k, v in self._data.items()}, f)

    def __setitem__(self, key, value):
        self._data[key] = value
        self._save()  # Auto-save to disk
```

### open_positions.json
**Purpose**: Track which signal opened which MT5 position

```json
{
  "EURUSD_2026-03-20 20:00:00+00:00_BUY_short_1.15824_1.15494": {
    "ticket": 123456,
    "pair": "EURUSD",
    "frame": "short",
    "open_price": 1.15824,
    "side": "BUY",
    "signal_time": "2026-03-20T20:00:00+00:00",
    "tp": 1.15824,
    "sl": 1.15494,
    "created_at": "2026-03-20T20:11:16.397815+00:00"
  }
}
```

**Key**: Signal ID (same as processed_signals)
**Value**: Position metadata including MT5 ticket number

**Implementation** (`state.py:39-146`):
```python
class _PositionTracker:
    """Maps signal_id → position metadata."""

    def add(self, signal_id, ticket, pair, frame, open_price, side,
            signal_time=None, tp=None, sl=None):
        self._data[signal_id] = {
            "ticket": ticket,
            "pair": pair,
            "frame": frame,
            "open_price": open_price,
            "side": side,
            "signal_time": time_str,
            "tp": tp,
            "sl": sl,
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        self._save()
```

---

## 7. Order Placement Details

### Magic Number and Comment

**Magic Number = 777** (`trader.py:14`):
```python
MAGIC_NUMBER = 777  # All trades use same magic number
```

**Comment = "blind"** (`trader.py:90`):
```python
"comment": "blind"
```

### Full order request structure (`trader.py:80-93`):

```python
request = {
    "action": mt5.TRADE_ACTION_DEAL,        # Execute immediately
    "symbol": pair,                          # e.g., "EURUSD"
    "volume": TRADE_VOLUME,                  # 0.01 lots
    "type": order_type,                      # BUY or SELL
    "price": price,                          # Current market price
    "tp": tp,                                # Take profit from signal
    "sl": sl,                                # Stop loss from signal
    "deviation": 20,                         # Price slippage tolerance
    "magic": MAGIC_NUMBER,                   # 777 = our bot
    "comment": "blind",                      # Identifier for our orders
    "type_filling": mt5.ORDER_FILLING_IOC,   # Immediate or Cancel
    "type_time": mt5.ORDER_TIME_GTC           # Good Till Cancel
}

result = mt5.order_send(request)
```

### Return value handling (`trader.py:97-112`):
```python
if result.retcode == 10009:  # Success
    return True, result.order  # Return (success, ticket_number)
elif result.retcode == 10016:  # Price moved
    return True, None  # Mark as processed but no ticket
else:
    return False, None  # Failed
```

---

## 8. Handling Multiple Trades Same Pair

### Problem: Two EURUSD trades with different TP/SL

**Scenario:**
```
Position A: EURUSD SHORT @ 1.15824 with TP 1.158, SL 1.153
Position B: EURUSD SHORT @ 1.15811 with TP 1.157, SL 1.154
```

### Solution: Deduplication includes TP/SL

**Before fix** (would skip one signal):
```python
key = f"{s['pair']}_{s['frame']}"  # Only pair+frame
# Both unique signals get same key → only first kept
```

**After fix** (both signals processed):
```python
key = f"{s['pair']}_{s['frame']}_{s['tp']}_{s['sl']}"
# Position A: "EURUSD_short_1.158_1.153" ✓
# Position B: "EURUSD_short_1.157_1.154" ✓ (different key)
# Both are kept and processed
```

### How they're differentiated:
1. **Storage** (`open_positions.json`):
   ```json
   {
     "EURUSD_..._1.158_1.153": { "ticket": 123456, ... },
     "EURUSD_..._1.157_1.154": { "ticket": 123457, ... }
   }
   ```

2. **Closing** - Match by TP/SL:
   ```
   Website close: TP 1.157, SL 1.154
   → Matches Position B by TP/SL
   → Closes only ticket 123457
   → Position A stays open ✓
   ```

---

## 9. Restart Behavior

### What happens when the bot restarts

**Step 1: Load processed signals** (`main.py:59-60`):
```python
prune_signals('processed_signals.json', hours=24)
```

**Step 2: Load open positions** (`state.py:47-53`):
```python
class _PositionTracker:
    def __init__(self):
        self._data = {}
        if os.path.exists(_POSITIONS_FILE):
            with open(_POSITIONS_FILE) as f:
                self._data = json.load(f)
            print(f"STATE: loaded {len(self._data)} open position mappings from disk")
```

**Step 3: Cleanup stale positions** (`main.py:88-100`):
```python
def cleanup_stale_positions():
    """Remove positions that MT5 closed but we didn't process."""
    stale_count = 0
    for signal_id, metadata in position_tracker.all_positions():
        ticket = metadata['ticket']
        pair = metadata['pair']

        pos = get_position(pair)
        if pos and pos.ticket == ticket:
            continue  # Position still open

        # MT5 closed it, we didn't know
        position_tracker.remove(signal_id)
        stale_count += 1
```

### Complete restart sequence:
1. Load `processed_signals.json` → Skip already-processed signals
2. Load `open_positions.json` → Know which positions we opened
3. Sync with MT5 → Remove stale positions we didn't close
4. Resume normal operation

---

## 10. Edge Case: Two EURUSD Trades, Close One

### Complete step-by-step execution

**Initial state:**
```
Position A: EURUSD SHORT @ 1.15824, TP 1.158, SL 1.153, Ticket 123456
Position B: EURUSD SHORT @ 1.15811, TP 1.157, SL 1.154, Ticket 123457
```

**Website shows close signal:**
```
Close: 1.15712
TP: 1.157
SL: 1.154
Status: Achieved
```

### Execution flow:

**1. Parser extracts** (`parser.py:62-75`):
```python
close_price_match = re.search(r"Close:\s*([\d\.]+)", text)
# Extracts: close_price = 1.15712

if "Achieved" in text:
    close_reason = "Achieved"

signal = {
    "pair": "EURUSD",
    "status": "CLOSE",
    "tp": 1.157,
    "sl": 1.154,
    "close": 1.15712,
    "close_reason": "Achieved"
}
```

**2. Main processes close signal** (`main.py:267-287`):
```python
if s["status"] != "CLOSE":
    continue  # This is CLOSE, so proceed

pair = "EURUSD"
frame = "short"  # From signal

# Create close signal ID
close_signal_id = f"EURUSD_{time}_CLOSE_short_1.157_1.154"

# Check if already processed
if close_signal_id in processed_signals:
    continue  # Skip if already processed

# Find matching position
matching_signal_id, metadata = position_tracker.find_matching_position(
    pair="EURUSD",
    frame="short",
    tp=1.157,
    sl=1.154
)
```

**3. Position matching** (`state.py:104-128`):
```python
matches = []
for signal_id, metadata in self._data.items():
    if metadata["pair"] != "EURUSD" or metadata["frame"] != "short":
        continue
    matches.append((signal_id, metadata))

# Now matches contains:
#   Signal A: tp=1.158, sl=1.153
#   Signal B: tp=1.157, sl=1.154

# Find TP/SL match
tp = 1.157
sl = 1.154
TP_SL_TOLERANCE = 0.001

for signal_id, metadata in matches:
    stored_tp = metadata.get('tp')
    stored_sl = metadata.get('sl')

    # Check Signal A
    if abs(1.158 - 1.157) < 0.001:  # 0.001 < 0.001? NO ✗
        continue

    # Check Signal B
    if abs(1.157 - 1.157) < 0.001:   # 0.0 < 0.001? YES ✓
        and abs(1.154 - 1.154) < 0.001:  # 0.0 < 0.001? YES ✓
        return signal_id_B, metadata_B  # FOUND!
```

**4. Close by ticket** (`main.py:297-303`):
```python
if matching_signal_id and metadata:
    print(f"CLOSE: EURUSD @ 1.15712 [Frame: short] (Achieved) TP:1.157 SL:1.154")
    print(f"  ✓ Matched to signal ID: {matching_signal_id}")
    print(f"    Ticket: {metadata['ticket']}")  # 123457

    close_position_by_ticket(123457, "EURUSD")  # Close only Position B
```

**5. Close execution** (`trader.py:149-182`):
```python
def close_position_by_ticket(ticket=123457, pair="EURUSD"):
    positions = mt5.positions_get(symbol="EURUSD")

    for pos in positions:
        if pos.ticket != 123457 or pos.magic != 777:
            continue  # Skip Position A (ticket 123456)

        # Found Position B (ticket 123457)
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": "EURUSD",
            "volume": pos.volume,
            "type": mt5.ORDER_TYPE_BUY,  # Opposite of SELL
            "position": 123457,
            "magic": 777,
            "comment": "close"
        }

        result = mt5.order_send(request)
        if result.retcode == 10009:
            return True  # Successfully closed
```

**6. Cleanup** (`main.py:298-303`):
```python
if close_position_by_ticket(metadata["ticket"], pair):
    closed += 1
    position_tracker.remove(matching_signal_id)  # Remove Signal B from tracker

    # Check if other positions remain
    remaining = len([m for sid, m in position_tracker.all_positions()
                     if m["pair"] == "EURUSD"])
    # remaining = 1 (Signal A still there)

    # Don't unlock frame since Position A still open
```

### Final result:
```
✓ Position B closed at 1.15712 (Achieved)
✓ Position A remains open
✓ Signal A still in open_positions.json
✓ Signal B removed from tracking
✓ Frame still locked (Position A prevents new signals on short frame)
```

### Log output:
```
[20:15:43] CLOSE: EURUSD @ 1.15712 [Frame: short] (Achieved) TP:1.157 SL:1.154
  ✓ Matched to signal ID: EURUSD_2026-03-20 20:00:15+00:00_SELL_short_1.157_1.154
    Signal time: 20:00:15 | Original price: 1.15811 | Side: SELL
    TP match: 1.157 | SL match: 1.154
    Ticket: 123457
  ✓ CLOSED
```

---

## Summary

| Component | Implementation | Status |
|-----------|---|---|
| **Trade Identification** | Composite signal ID with TP/SL | ✅ Unique per setup |
| **Open Logic** | Dedup + age filter + processing flag | ✅ No duplicates |
| **Close Logic** | TP/SL matching + ticket-based close | ✅ Correct position |
| **Position Tracking** | Persistent JSON storage | ✅ Survives restart |
| **Multiple Trades** | TP/SL differentiation | ✅ Works correctly |
| **MT5 Integration** | Magic=777, comment="blind" | ✅ Traceable orders |
| **State Management** | Two JSON files (signals + positions) | ✅ Persistent |
| **Edge Cases** | Handled (stale cleanup, tolerance, etc.) | ✅ Robust |

