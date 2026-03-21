# State Consistency Architecture - Complete Implementation

## Problem Statement

**The Website is Snapshot-Based, Not Event-Based**

The website provides STATES (counts of open trades), not EVENTS (which exact trade closed).

```
Event-based (what we don't have):
  T1: Trade #456 closed at 1.158

State-based (what we have):
  T1: 3 EURUSD trades open
  T2: 2 EURUSD trades open (unknown which one closed!)
```

## Core Insight

**We cannot determine which exact trade closed without a unique identifier from the website.**

Since the website only gives us counts and TP/SL values, we must:
1. Track our OWN opened positions
2. Detect differences between previous and current state
3. Close ANY matching trade (all are equivalent from risk perspective)

## Architecture Overview

### 1. Signal Normalization

Convert website signals → normalized keys that abstract away temporary variations:

```python
key = (pair, side, round(tp, precision), round(sl, precision))

Examples:
  ("EURUSD", "BUY", 1.158, 1.154)
  ("GBPUSD", "SELL", 1.275, 1.269)
```

**Why this works:**
- TP and SL are rounded to trading precision
- Small broker adjustments (1.15802 → 1.158) are normalized
- Same pair+side+TP/SL = same position type

### 2. Position Storage

```python
positions = {
    key: [ticket1, ticket2, ticket3, ...]
}
```

**Why lists, not counts:**
- Multiple identical positions are possible
- We need actual ticket numbers to close
- LIFO popping gives deterministic behavior

Example:
```python
{
    ("EURUSD", "BUY", 1.158, 1.154): [10001, 10002, 10003],
    ("GBPUSD", "SELL", 1.275, 1.269): [10004],
}
```

### 3. State Diffing with Counter

Compare previous snapshot to current snapshot:

```python
prev_keys = [
    ("EURUSD", "BUY", 1.158, 1.154),
    ("EURUSD", "BUY", 1.158, 1.154),
    ("EURUSD", "BUY", 1.158, 1.154),
    ("GBPUSD", "SELL", 1.275, 1.269),
]

curr_keys = [
    ("EURUSD", "BUY", 1.158, 1.154),
    ("EURUSD", "BUY", 1.158, 1.154),
    ("GBPUSD", "SELL", 1.278, 1.272),  # Different TP/SL = different key
]

prev_counter = Counter(prev_keys)
curr_counter = Counter(curr_keys)

closed = prev_counter - curr_counter
# {("EURUSD", "BUY", 1.158, 1.154): 1, ("GBPUSD", "SELL", 1.275, 1.269): 1}

opened = curr_counter - prev_counter
# {("GBPUSD", "SELL", 1.278, 1.272): 1}
```

### 4. Safe Execution

**CRITICAL SAFETY RULES:**

```python
# For each closed key:
1. Check if key exists in positions
   IF NOT: Skip (don't close what we didn't open)

2. Calculate safe count
   safe_count = min(count_to_close, available_tickets)

3. Close tickets
   for _ in range(safe_count):
       ticket = positions[key].pop()  # LIFO
       close_ticket(ticket)
```

**This prevents:**
- Closing positions we never opened
- Closing more than we have
- Guessing about which exact trade

### 5. Signal Age Filtering

**CRITICAL DISTINCTION:**

```python
# ACTIVE signals: Skip if older than 24 hours
# Rationale: We want fresh open signals, not stale history

# CLOSE signals: Keep regardless of age
# Rationale: We MUST close positions when website shows them as closed,
#           even if the signal is old
```

## Implementation Flow

```
CYCLE:
  1. Fetch website HTML

  2. Parse signals (MUST use absolute UTC time, not "24 mins ago")
     -> List[Signal]

  3. Build current keys
     curr_keys = [
         SignalKey.build(s.pair, s.side, s.tp, s.sl)
         for s in signals if s.status == "ACTIVE"
     ]

  4. Get previous keys from our position tracker
     prev_keys = list(positions.keys())

  5. Compute diff
     closed, opened = StateDifferencer.compute_diff(prev_keys, curr_keys)

  6. Close trades SAFELY
     for key, count in closed.items():
         is_valid, reason = SafeExecutor.validate_close(key, count, positions)
         if is_valid:
             for _ in range(count):
                 ticket = positions[key].pop()
                 close_ticket(ticket)

  7. Open trades
     for key, count in opened.items():
         for _ in range(count):
             signal = find_signal_for_key(key)
             ticket = open_trade(signal)
             positions[key].append(ticket)

  8. Sleep and repeat
```

## Edge Cases Handled

### Case 1: Identical Multiple Positions

```
Scenario:
  Website: EURUSD BUY @ 1.158 TP/SL = 3 trades
  Bot has: 3 tickets open for this key

If website closes 1:
  Diff: {key: 1 closed}
  Action: pop() one ticket (LIFO)
  Result: Bot now has 2 tickets ✓

Note: We don't KNOW which one closed, but it doesn't matter
      (all identical trades have same risk exposure)
```

### Case 2: TP/SL Changes (Trailing Stop)

```
Scenario:
  Old key: ("EURUSD", "BUY", 1.158, 1.154)
  New key: ("EURUSD", "BUY", 1.160, 1.156)  (TP/SL moved)

Effect on state:
  prev = [("EURUSD", "BUY", 1.158, 1.154)] x 1
  curr = [("EURUSD", "BUY", 1.160, 1.156)] x 1

Diff:
  closed: {("EURUSD", "BUY", 1.158, 1.154): 1}
  opened: {("EURUSD", "BUY", 1.160, 1.156): 1}

Action:
  1. Close the old ticket
  2. Open a new one (but with same underlying position!)

This is SAFE because:
  - Bot was told to close old position (website removed it)
  - Bot was told to open new position (website added it)
  - Net effect: Existing trade continues (no gap)
```

### Case 3: Bot Missed Signals (Desync)

```
Scenario:
  Website: Had 3 EURUSD, now 0
  Bot tracker: Still has 3 from cycle N-1

Edge case: Nothing in website = all positions appear closed

State:
  prev = [("EURUSD", "BUY", 1.158, 1.154)] x 3
  curr = []

Diff:
  closed: {("EURUSD", "BUY", 1.158, 1.154): 3}

Action:
  pop() and close all 3 tickets

Result: Bot is synced ✓
```

### Case 4: Partial Close (Stale Signal)

```
Scenario:
  Website: EURUSD 3 → 2 (one closed)
  Signal age: 36 hours old (but it's a CLOSE signal)

Filter rule:
  CLOSE signals bypass age filter (always processed)

Result:
  Bot correctly closes 1 trade ✓
```

## Comparison: Old vs New

| Aspect | Old (TP/SL Matching) | New (Counter-based) |
|--------|---|---|
| **Models website as** | Transaction stream | State machine |
| **Tries to solve** | Which exact trade closed | What state should I be in |
| **Feasibility** | Impossible (no ID) | Possible (state is given) |
| **Tolerance logic** | Complex (handles 0.001 pp) | None needed (rounding) |
| **Collision handling** | Complex (guesses) | None (counter logic) |
| **Determinism** | Probabilistic | Deterministic (Counter+LIFO) |
| **Failure mode** | Wrong but consistent count | Wrong but consistent count |
| **Code complexity** | ~300 lines | ~150 lines |

## Guarantees

This system guarantees:

1. **No wrong trade closures**
   - Only close what we opened (validated)
   - Only close up to what we have (min() applied)

2. **No crashes on desync**
   - Missing signals → detects count diff
   - Stale signals → handled with age filter
   - Network issues → just wait for next cycle

3. **Deterministic behavior**
   - Counter logic is deterministic
   - LIFO popping is predictable
   - Same snapshot → same action always

## Configuration

```python
# signal_manager.py
SignalKey.PRECISION = 3  # Rounding precision for TP/SL

# config.py
MAX_SIGNAL_AGE = 24 * 3600  # 24 hours, only for ACTIVE signals
SIGNAL_INTERVAL = 8  # seconds between cycles
TRADE_VOLUME = 0.01  # lot size
```

## Migration Steps

1. Replace signal parsing to use `signal_manager.Signal`
2. Update parser to use only absolute UTC times (no relative parsing)
3. Replace main.py logic with Counter-based diff
4. Update position tracker to use new storage format
5. Test with simulation scenarios
6. Deploy and monitor

---

**Key Insight:**

The website doesn't tell you which trade to close.

It tells you what state you should be in.

Sync the state, don't guess the trades.
