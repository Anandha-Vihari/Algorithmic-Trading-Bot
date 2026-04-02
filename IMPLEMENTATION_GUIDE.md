# Counter Diff Logic - Complete Implementation Guide

## Files & JSON Structures

### 1. Core Files Involved

```
main.py
  ├─ processed_signals.json      (Deduplication tracker)
  ├─ Calls signal_manager.py     (State logic)
  ├─ Calls trader.py             (MT5 operations)
  └─ Maintains PositionStore (in-memory)

signal_manager.py
  ├─ SignalKey class             (Key normalization)
  ├─ PositionStore class         (Position storage)
  ├─ StateDifferencer class      (Counter logic)
  ├─ SignalFilter class          (Deduplication)
  └─ SafeExecutor class          (Validation)
```

---

## JSON File: `processed_signals.json`

### Purpose
**Prevent duplicate signal processing** by tracking which signals have already been acted on.

### Structure

```json
{
  "2025-04-02T10:00:01.123456+00:00_('EURUSD', 'BUY', 1.158, 1.154)": "2025-04-02T10:00:01.200000+00:00",
  "2025-04-02T10:00:05.654321+00:00_('GBPUSD', 'SELL', 1.268, 1.262)": "2025-04-02T10:00:05.300000+00:00",
  "2025-04-02T10:00:15.987654+00:00_('EURUSD', 'BUY', 1.158, 1.154)": "2025-04-02T10:00:15.400000+00:00"
}
```

### Key Format
```python
signal_id = f"{signal.time.isoformat()}_{signal_key}"

# Example:
# signal.time = 2025-04-02T10:00:01.123456+00:00
# signal_key = ("EURUSD", "BUY", 1.158, 1.154)
# signal_id = "2025-04-02T10:00:01.123456+00:00_('EURUSD', 'BUY', 1.158, 1.154)"
```

### Value (always timestamp when saved)
```python
# Value = when we processed it
json_value = datetime.now(timezone.utc).isoformat()
# "2025-04-02T10:00:01.200000+00:00"
```

### Lifecycle

#### Loading
```python
def load_processed_signals():
    """Load set of already-processed signal timestamps (fault-tolerant)."""
    try:
        with open('processed_signals.json', 'r') as f:
            data = json.load(f)

        # Keep signals from last 24 hours (older ones garbage-collected)
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        filtered = {
            ts: v for ts, v in data.items()
            if datetime.fromisoformat(v) > cutoff
        }

        return set(filtered.keys())  # Return signal IDs as set

    except FileNotFoundError:
        return set()  # Fresh start
    except json.JSONDecodeError as e:
        print(f"[ERROR_JSON] Corrupted: {e}, starting fresh")
        return set()  # Recover gracefully
    except Exception as e:
        print(f"[ERROR_JSON] Failed to load: {e}, starting fresh")
        return set()
```

**Key points:**
- Returns a **set** of signal IDs (not dict)
- Keeps only signals from last 24 hours
- Handles file-not-found, corrupted JSON, and other errors
- Always returns a valid set (empty if error)

#### Processing
```python
# During signal cycle
processed_signals = load_processed_signals()

for sig in website_signals:
    signal_id = get_signal_id(sig)  # Build ID

    if signal_id in processed_signals:
        print(f"[SKIP] Already processed: {signal_id}")
        continue  # Skip duplicate

    # Process signal (open/close trade)
    # ...

    # Mark as processed
    processed_signals.add(signal_id)
```

#### Saving
```python
def save_processed_signals(signal_set):
    """Save processed signal IDs (fault-tolerant)."""
    try:
        # Convert set to dict for JSON
        data = {
            sig_id: datetime.now(timezone.utc).isoformat()
            for sig_id in signal_set
        }

        # ATOMIC WRITE: temp file → replace
        temp_fd, temp_path = tempfile.mkstemp(suffix='.json', prefix='processed_signals_')
        try:
            with os.fdopen(temp_fd, 'w') as f:
                json.dump(data, f)
            os.replace(temp_path, 'processed_signals.json')  # Atomic rename
        except Exception:
            try:
                os.unlink(temp_path)  # Clean up temp file
            except:
                pass
            raise

    except Exception as e:
        print(f"[ERROR_JSON] Failed to save: {e}, changes may be lost")
```

**Why atomic write?**
- Prevents corruption if bot crashes mid-write
- Temp file is written first, then renamed
- If power fails, only temp is corrupted, main file stays intact

---

## In-Memory Structure: `PositionStore`

### Purpose
Hold ticket associations with signal keys **in memory** (NOT in JSON).

### Data Structure
```python
class PositionStore:
    def __init__(self):
        # Dict: key → list of ticket IDs
        self.positions: Dict[Tuple, List[int]] = {}

        # Example:
        # {
        #   ("EURUSD", "BUY", 1.158, 1.154): [10001, 10002, 10003],
        #   ("GBPUSD", "SELL", 1.268, 1.262): [10004],
        # }
```

### Key Format
```python
key = (pair, side, rounded_tp, rounded_sl)

# Example:
key = ("EURUSD", "BUY", 1.158, 1.154)
#       ^^^^^^    ^^^    ^^^^^^  ^^^^^^
#       pair    side    tp      sl
```

### Operations

#### Add Ticket (after successful open)
```python
def add_ticket(self, key: Tuple, ticket: int):
    if key not in self.positions:
        self.positions[key] = []
    self.positions[key].append(ticket)

# Example:
store.add_ticket(("EURUSD", "BUY", 1.158, 1.154), 10001)
# positions[("EURUSD", "BUY", 1.158, 1.154)] = [10001]
```

#### Pop Ticket (for closing - LIFO order)
```python
def pop_ticket(self, key: Tuple) -> Optional[int]:
    if key not in self.positions or not self.positions[key]:
        return None
    return self.positions[key].pop()  # Remove from end

# Example:
ticket = store.pop_ticket(("EURUSD", "BUY", 1.158, 1.154))
# Returns 10001, removes it from list
# positions[("EURUSD", "BUY", 1.158, 1.154)] = []
```

#### Get N Tickets (for close validation - WITHOUT removal)
```python
def get_n_tickets_for_close(self, key: Tuple, count: int) -> List[int]:
    """Get tickets WITHOUT modifying store (safety first!)"""
    tickets = self.positions.get(key, [])
    return list(tickets[-count:]) if count > 0 and tickets else []

# Example:
tickets = store.get_n_tickets_for_close(("EURUSD", "BUY", 1.158, 1.154), 2)
# Returns [10002, 10003] (last 2, LIFO)
# positions UNCHANGED - safe to validate before actually closing
```

#### Remove Ticket (ONLY after successful close)
```python
def remove_ticket(self, ticket: int) -> bool:
    for key, tickets in self.positions.items():
        if ticket in tickets:
            tickets.remove(ticket)
            return True
    return False

# Example:
store.remove_ticket(10001)
# Searches all keys, finds and removes 10001
# Returns True if found, False otherwise
```

#### Count for Key
```python
def count_for_key(self, key: Tuple) -> int:
    return len(self.positions.get(key, []))

# Example:
count = store.count_for_key(("EURUSD", "BUY", 1.158, 1.154))
# Returns 3 (three tickets for this key)
```

#### Serialization (for crash recovery - optional)
```python
def to_dict(self):
    """Convert to JSON-safe format (tuples become strings)"""
    return {
        str(key): tickets for key, tickets in self.positions.items()
    }
    # {
    #   "('EURUSD', 'BUY', 1.158, 1.154)": [10001, 10002, 10003],
    #   "('GBPUSD', 'SELL', 1.268, 1.262)": [10004],
    # }

def from_dict(self, data: dict):
    """Restore from JSON format"""
    self.positions.clear()
    for key_str, tickets in data.items():
        pair, side, tp, sl = eval(key_str)
        key = (pair, side, float(tp), float(sl))
        self.positions[key] = list(tickets)
```

---

## Signal Key Normalization

### Problem
Website might send float precision variations:
```
Signal 1: TP=1.15823, SL=1.15493
Signal 2: TP=1.15825, SL=1.15491
```

These are nearly identical (differ by 2-4 pips), should be same trade.

### Solution: Round to 3 decimals
```python
class SignalKey:
    PRECISION = 3  # Configurable

    @staticmethod
    def build(pair: str, side: str, tp: float, sl: float) -> Tuple:
        rounded_tp = round(tp, SignalKey.PRECISION)
        rounded_sl = round(sl, SignalKey.PRECISION)
        return (pair, side, rounded_tp, rounded_sl)

# Both signals normalize to same key:
key1 = SignalKey.build("EURUSD", "BUY", 1.15823, 1.15493)
key2 = SignalKey.build("EURUSD", "BUY", 1.15825, 1.15491)

print(key1 == key2)  # True! Same key
# ("EURUSD", "BUY", 1.158, 1.155)
```

### Why 3 decimals?
- Most forex pairs: 5 decimal places (EURUSD, GBPUSD)
- 3 decimal precision = 0.001 pip = ~$0.10 on standard lot (sufficient for TP/SL)
- JPY pairs: Use 2 decimals (different rounding)

---

## Deduplication Logic

### Problem: Multiple Identical Website Signals

Website fetches might return:
```
[
  Signal(EURUSD, BUY, TP=1.158, SL=1.154, time=10:00:01),
  Signal(EURUSD, BUY, TP=1.158, SL=1.154, time=10:00:02),  ← Same trade (float drift)
  Signal(GBPUSD, SELL, TP=1.268, SL=1.262, time=10:00:03),
]
```

### Solution: Keep Only Most Recent Per Key

```python
class SignalFilter:
    @staticmethod
    def deduplicate_by_key(signals: List[Signal]) -> List[Signal]:
        seen_keys = set()
        deduplicated = []

        for sig in signals:  # Assuming signals already sorted by time DESC
            key = SignalKey.build(sig.pair, sig.side, sig.tp, sig.sl)

            if key not in seen_keys:
                seen_keys.add(key)
                deduplicated.append(sig)
                # Skip any further signals with same key

        return deduplicated

# Example:
signals = [
    Signal(EURUSD, BUY, 1.15823, 1.15493, time=10:00:02),  ← KEPT (most recent)
    Signal(EURUSD, BUY, 1.15825, 1.15491, time=10:00:01),  ← SKIPPED
    Signal(GBPUSD, SELL, 1.26823, 1.26293, time=10:00:03), ← KEPT
]

deduplicated = SignalFilter.deduplicate_by_key(signals)
# Result: [Signal(EURUSD, time=10:00:02), Signal(GBPUSD, ...)]
```

### Flow: Raw → Deduplicated → Processed

```
Website HTML
    ↓
[parse_signals] → Raw signals list (may have duplicates/noise)
    ↓
[deduplicate_by_key] → One signal per unique key
    ↓
[filter_by_age] → Only signals < 24 hours old
    ↓
[processed_signals check] → Skip if already acted on
    ↓
Clean signals ready for Counter diff
```

---

## Counter Diff Logic

### The Core Algorithm

```python
class StateDifferencer:
    @staticmethod
    def compute_diff(
        prev_keys: List[Tuple],
        curr_keys: List[Tuple]
    ) -> Tuple[Counter, Counter]:
        """
        Compare two snapshots to determine what changed.
        """
        prev_counter = Counter(prev_keys)
        curr_counter = Counter(curr_keys)

        # CLOSED: existed before but not now
        closed = prev_counter - curr_counter

        # OPENED: not before but exists now
        opened = curr_counter - prev_counter

        return closed, opened
```

### Example: Step-by-Step

#### Cycle 1: Bob opens 3 identical EURUSD trades

```
prev_keys = []  # Start empty
curr_keys = [
    ("EURUSD", "BUY", 1.158, 1.154),
    ("EURUSD", "BUY", 1.158, 1.154),
    ("EURUSD", "BUY", 1.158, 1.154),
]

prev_counter = {}
curr_counter = {("EURUSD", "BUY", 1.158, 1.154): 3}

closed = prev_counter - curr_counter = {}
opened = curr_counter - prev_counter = {("EURUSD", "BUY", 1.158, 1.154): 3}

# ACTION: Open 3 trades
# Result in PositionStore:
#   {("EURUSD", "BUY", 1.158, 1.154): [10001, 10002, 10003]}
```

#### Cycle 2: One EURUSD trade closed by broker (now 2 left)

```
prev_keys = [
    ("EURUSD", "BUY", 1.158, 1.154),
    ("EURUSD", "BUY", 1.158, 1.154),
    ("EURUSD", "BUY", 1.158, 1.154),
]
curr_keys = [
    ("EURUSD", "BUY", 1.158, 1.154),
    ("EURUSD", "BUY", 1.158, 1.154),
]

prev_counter = {("EURUSD", "BUY", 1.158, 1.154): 3}
curr_counter = {("EURUSD", "BUY", 1.158, 1.154): 2}

closed = {("EURUSD", "BUY", 1.158, 1.154): 1}  # 3 - 2 = 1
opened = {}

# ACTION: Close 1 trade
# Pick LIFO (pop from end): 10003
# Result in PositionStore:
#   {("EURUSD", "BUY", 1.158, 1.154): [10001, 10002]}
# State SYNCED: bot=2, website=2 ✓
```

#### Cycle 3: EURUSD closed, new GBPUSD SELL trade appears

```
prev_keys = [
    ("EURUSD", "BUY", 1.158, 1.154),
    ("EURUSD", "BUY", 1.158, 1.154),
]
curr_keys = [
    ("EURUSD", "BUY", 1.158, 1.154),
    ("EURUSD", "BUY", 1.158, 1.154),
    ("GBPUSD", "SELL", 1.268, 1.262),
]

prev_counter = {("EURUSD", "BUY", 1.158, 1.154): 2}
curr_counter = {
    ("EURUSD", "BUY", 1.158, 1.154): 2,
    ("GBPUSD", "SELL", 1.268, 1.262): 1,
}

closed = {}  # EURUSD count didn't decrease
opened = {("GBPUSD", "SELL", 1.268, 1.262): 1}

# ACTION: Open 1 GBPUSD SELL
# Get new ticket: 10004
# Result in PositionStore:
#   {
#     ("EURUSD", "BUY", 1.158, 1.154): [10001, 10002],
#     ("GBPUSD", "SELL", 1.268, 1.262): [10004],
#   }
```

---

## Safe Execution with Validation

### Problem
Website shows "close 5 trades" but bot only has 3. Don't blindly close!

### Solution: SafeExecutor Validates Before Closing

```python
class SafeExecutor:
    @staticmethod
    def validate_close(
        key: Tuple,
        close_count: int,
        position_store: PositionStore
    ) -> Tuple[bool, str]:
        """Validate we can safely close this many."""

        # Rule 1: Key must exist
        if not position_store.has_key(key):
            return False, f"Key {key} not in positions (not opened by us)"

        # Rule 2: Don't close more than we have
        available = position_store.count_for_key(key)
        if close_count > available:
            return False, f"Want to close {close_count} but only have {available}"

        return True, "OK"
```

### Example Execution Flow

```python
# Diff says: Close 5 EURUSD trades
closed_counter = {("EURUSD", "BUY", 1.158, 1.154): 5}

# Validate
is_valid, reason = SafeExecutor.validate_close(
    key=("EURUSD", "BUY", 1.158, 1.154),
    close_count=5,
    position_store=store
)

if store.count_for_key(key) == 3:
    # is_valid = False
    # reason = "Want to close 5 but only have 3"
    print(f"[SKIP] {reason}")
    # Don't execute - state would diverge if we tried
```

### Prepare Close Operations (WITHOUT removing)

```python
@staticmethod
def prepare_close_operations(
    closed_counter: Counter,
    position_store: PositionStore
) -> List[Tuple[Tuple, int]]:
    """Collect tickets to close WITHOUT removing them yet."""

    operations = []

    for key, count_to_close in closed_counter.items():
        # Skip UNMATCHED (never close positions we don't understand)
        if key[0] == "_UNMATCHED_":
            print(f"  [SKIP_UNMATCHED] Won't touch {key}")
            continue

        # Validate
        is_valid, reason = SafeExecutor.validate_close(
            key, count_to_close, position_store
        )

        if not is_valid:
            print(f"  [SKIP CLOSE] {key}: {reason}")
            continue

        # Safe close: never more than available
        safe_count = min(count_to_close, position_store.count_for_key(key))

        # Get tickets WITHOUT removing
        tickets = position_store.get_n_tickets_for_close(key, safe_count)

        # Return operations
        for ticket in tickets:
            if ticket:
                operations.append((key, ticket))

    return operations

# Example:
# Input: {("EURUSD", "BUY", 1.158, 1.154): 2}
# Output: [
#   (("EURUSD", "BUY", 1.158, 1.154), 10002),
#   (("EURUSD", "BUY", 1.158, 1.154), 10001),
# ]
# PositionStore UNCHANGED - ready to validate
```

---

## Complete Signal Cycle Flow

### Full Sequence

```
1. FETCH SIGNALS
   └─ fetch_page() → HTML
   └─ parse_signals() → Signal objects (raw, may have dupes)

2. FILTER & DEDUPLICATE
   └─ filter_by_age() → Remove signals > 24h old
   └─ deduplicate_by_key() → Keep only most recent per key

3. LOAD PROCESSED SIGNALS
   └─ load_processed_signals() → Set of already-acted-on signal IDs
   └─ Skip duplicates from previous cycles

4. COMPUTE DIFF
   └─ Extract curr_keys from signals
   └─ Compare to prev_keys using Counter
   └─ Get: closed = prev_counter - curr_counter
   └─ Get: opened = curr_counter - prev_counter

5. EXECUTE CLOSES
   └─ For each (key, count) in closed:
      └─ validate_close() → Safety check
      └─ prepare_close_operations() → Get tickets (no removal)
      └─ close_position_by_ticket() → Actually close in MT5
      └─ remove_ticket() → ONLY after success

6. EXECUTE OPENS
   └─ For each (key, count) in opened:
      └─ For i in range(count):
         └─ open_trade() → Open in MT5, get ticket
         └─ add_ticket(key, ticket) → Store ticket

7. UPDATE STATE
   └─ prev_keys = curr_keys (for next cycle)
   └─ processed_signals.add(signal_id for each signal)
   └─ save_processed_signals()

8. SLEEP
   └─ sleep(SIGNAL_INTERVAL)  # Check again in ~7 seconds
```

---

## JSON + In-Memory Coordination

### Question: Why not persist PositionStore to JSON?

**Answer:** Design choice for speed and simplicity.

| Aspect | In-Memory | JSON Persist |
|--------|-----------|-------------|
| Speed | O(1) dict lookup | O(n) JSON parse |
| Complexity | Simple list ops | Serialize/deserialize |
| Crash recovery | Lost on restart | Can reload from disk |
| Current design | ✓ Used | ✗ Not needed |

### How recovery works on restart

When bot restarts:

```python
# 1. Load processed_signals.json
processed = load_processed_signals()

# 2. Reconstruct PositionStore from MT5 live state
positions = PositionStore()

# 3. Fetch current MT5 positions
mt5_positions = show_open_positions()

# 4. Match each MT5 position to latest signals
for mt5_pos in mt5_positions:
    # Get fresh signals from website
    curr_signals = fetch_and_parse_signals()

    # Fuzzy match: MT5 position ↔ signal (by TP/SL similarity)
    best_key = FuzzyMatcher.find_best_match(
        mt5_pos.tp, mt5_pos.sl, signals_by_key
    )

    if best_key:
        positions.add_ticket(best_key, mt5_pos.ticket)

# Result: PositionStore reconstructed from MT5 ✓
```

**Key insight:** Website is source of truth. Reconstruct state from live MT5 + signals.

---

## Example JSON State Progression

### Cycle 1: Start

```json
processed_signals.json:
{}

PositionStore (in-memory):
{}
```

### Cycle 2: Open 2 EURUSD trades

```json
processed_signals.json:
{
  "2025-04-02T10:00:01.111111+00:00_('EURUSD', 'BUY', 1.158, 1.154)": "2025-04-02T10:00:01.200000+00:00",
  "2025-04-02T10:00:02.222222+00:00_('EURUSD', 'BUY', 1.158, 1.154)": "2025-04-02T10:00:02.300000+00:00"
}

PositionStore (in-memory):
{
  ("EURUSD", "BUY", 1.158, 1.154): [10001, 10002]
}
```

Note: Website sent 2 signals → both processed and stored → tickets created

### Cycle 3: Added GBPUSD SELL

```json
processed_signals.json:
{
  "2025-04-02T10:00:01.111111+00:00_('EURUSD', 'BUY', 1.158, 1.154)": "2025-04-02T10:00:01.200000+00:00",
  "2025-04-02T10:00:02.222222+00:00_('EURUSD', 'BUY', 1.158, 1.154)": "2025-04-02T10:00:02.300000+00:00",
  "2025-04-02T10:00:15.333333+00:00_('GBPUSD', 'SELL', 1.268, 1.262)": "2025-04-02T10:00:15.400000+00:00"
}

PositionStore (in-memory):
{
  ("EURUSD", "BUY", 1.158, 1.154): [10001, 10002],
  ("GBPUSD", "SELL", 1.268, 1.262): [10003]
}
```

### Cycle 4: Close 1 EURUSD (Broker closed it)

```json
processed_signals.json:
{
  "2025-04-02T10:00:01.111111+00:00_('EURUSD', 'BUY', 1.158, 1.154)": "2025-04-02T10:00:01.200000+00:00",
  "2025-04-02T10:00:02.222222+00:00_('EURUSD', 'BUY', 1.158, 1.154)": "2025-04-02T10:00:02.300000+00:00",
  "2025-04-02T10:00:15.333333+00:00_('GBPUSD', 'SELL', 1.268, 1.262)": "2025-04-02T10:00:15.400000+00:00"
}

PositionStore (in-memory):
{
  ("EURUSD", "BUY", 1.158, 1.154): [10001],        ← One removed
  ("GBPUSD", "SELL", 1.268, 1.262): [10003]
}
```

Mechanics:
- Website shows: 1 EURUSD (was 2)
- Diff: close {EURUSD: 1}
- Action: close_position_by_ticket(10002) → success
- Update: remove_ticket(10002) → position_store

---

## Multi-Pair Scenario With Duplicates

### Website sends (messy snapshot):

```
[
  Signal(EURUSD, BUY, 1.15823, 1.15493, time=10:00:01),
  Signal(EURUSD, BUY, 1.15825, 1.15491, time=10:00:01.5),  ← Similar (noise)
  Signal(EURUSD, BUY, 1.15820, 1.15490, time=10:00:02),    ← Identical key
  Signal(GBPUSD, SELL, 1.26823, 1.26293, time=10:00:03),
  Signal(GBPUSD, SELL, 1.26825, 1.26295, time=10:00:03.5), ← Duplicate
]
```

### Step 1: Normalize Keys

```python
keys = [
    ("EURUSD", "BUY", 1.158, 1.155),  # Signal 1
    ("EURUSD", "BUY", 1.158, 1.155),  # Signal 2 → SAME KEY
    ("EURUSD", "BUY", 1.158, 1.155),  # Signal 3 → SAME KEY
    ("GBPUSD", "SELL", 1.268, 1.263), # Signal 4
    ("GBPUSD", "SELL", 1.268, 1.263), # Signal 5 → SAME KEY
]
```

### Step 2: Deduplicate

```python
deduplicated = [
    Signal(EURUSD, BUY, 1.15820, 1.15490, time=10:00:02),  ← Most recent
    Signal(GBPUSD, SELL, 1.26825, 1.26295, time=10:00:03.5),  ← Most recent
]

deduplicated_keys = [
    ("EURUSD", "BUY", 1.158, 1.155),
    ("GBPUSD", "SELL", 1.268, 1.263),
]
```

### Step 3: Check Processed (prevents re-opening)

```python
processed = {
    "2025-04-02T10:00:01.111111+00:00_('EURUSD', 'BUY', 1.158, 1.155)",
    # ... other old signals
}

for sig in deduplicated:
    signal_id = get_signal_id(sig)
    if signal_id not in processed:
        # Process it first time
        # ...
        processed.add(signal_id)
```

### Step 4: Counter Diff

```
prev_counter = {
    ("EURUSD", "BUY", 1.158, 1.155): 1,
    ("GBPUSD", "SELL", 1.268, 1.263): 1,
}

curr_counter = {
    ("EURUSD", "BUY", 1.158, 1.155): 1,
    ("GBPUSD", "SELL", 1.268, 1.263): 1,
}

closed = {}  # No change
opened = {}

# No action needed, state already synced
```

---

## FAQ: How It Prevents Bugs

### Q: What if website sends SAME signal 3 times?

```
Website: [sig1, sig1, sig1]  (identical)

Dedup: [sig1]  ← Only one kept
Diff: prev_counter[sig1] = X → curr_counter[sig1] = 1
      If X == 1: no change
      If X == 0: open 1 (correct!)
      If X == 5: close 4 (correct!)
```

**Result:** Deduplication prevents duplicate opens.

### Q: What if MT5 crashes and loses positions?

```
Before crash:
  PositionStore: {key: [10001, 10002, 10003]}
  MT5: Positions 10001, 10002, 10003 open

Crash

On restart:
  PositionStore: {} (lost, in-memory)
  MT5: Positions 10001, 10002, 10003 still open

Reconstruction:
  1. Reconstruct PositionStore from MT5 + signals
  2. Fetch MT5 positions → [10001, 10002, 10003]
  3. Fetch signals → find matching keys
  4. Add each ticket back

Result: PositionStore rebuilt ✓
```

### Q: What if website sends close signal but bot has 5 positions?

```
Website: "Close EURUSD"
Diff: closed = {EURUSD: 5}

Before close:
  PositionStore: {EURUSD: [10001, 10002, 10003, 10004, 10005]}

Safety check:
  Want to close: 5
  Have: 5
  Validation: PASS

Execute:
  close_position_by_ticket(10005)
  close_position_by_ticket(10004)
  close_position_by_ticket(10003)
  close_position_by_ticket(10002)
  close_position_by_ticket(10001)

All succeed
PositionStore: {EURUSD: []}

Result: Cleanly closed all ✓
```

### Q: What if one close fails mid-sequence?

```
Cycle 1: Website shows 0 trades
         Bot has 3 EURUSD
         Diff: close 3

Execute:
  CLOSE 10003 → SUCCESS → remove_ticket(10003)
  CLOSE 10002 → FAIL (insufficient margin)
  CLOSE 10001 → (not attempted)

PositionStore state:
  BEFORE: [10001, 10002, 10003]
  AFTER: [10001, 10002]  ← 10003 removed, others stay

Next cycle:
  Website: shows 0 (broker closed the rest)
  Bot has: [10001, 10002]
  Diff: close 2

Execute:
  CLOSE 10002 → SUCCESS
  CLOSE 10001 → SUCCESS

Result: Retry handles failures gracefully ✓
```

---

## Performance Characteristics

```
Operation                      | Time Complexity | Notes
-------------------------------|-----------------|----------------------------------
Load processed_signals         | O(n)            | n = signals in last 24h (~1000)
Deduplicate by key             | O(n)            | Single pass, set lookup O(1)
Counter diff                   | O(k)            | k = unique keys (~50)
Validate close                 | O(1)            | Direct dict lookup
Prepare operations             | O(m)            | m = operations to execute (~10)
Add/remove ticket              | O(1)            | List append/remove
-------------------------------|-----------------|----------------------------------
Total per cycle                | ~50-100ms       | Dominated by MT5 API calls
```

---

## Summary

**Counter Diff Logic** with **JSON + In-Memory** approach achieves:

✓ **State consistency**: bot state = website state always
✓ **Duplicate prevention**: Deduplication + processed_signals tracking
✓ **Safe execution**: Validation before every close
✓ **Fault tolerance**: Atomic JSON writes, recovery on restart
✓ **Simplicity**: Clear data flow, easy to debug
✓ **Performance**: O(k) where k = unique signals

**Key files:**
- `processed_signals.json` - Dedup tracker (persistent)
- `PositionStore` (in-memory) - Ticket associations
- `StateDifferencer` - Counter-based diffing
- `SafeExecutor` - Validation before execution

**The formula:**
```
prev_counter - curr_counter = positions to close
curr_counter - prev_counter = positions to open
No guessing, pure math ✓
```
