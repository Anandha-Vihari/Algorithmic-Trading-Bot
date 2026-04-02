"""
STATE CONSISTENCY SIGNAL MANAGER

Core principles:
1. Website is SNAPSHOT-BASED: shows current state, not events
2. Objective: Maintain bot's trade state = website's trade state
3. Safety: NEVER close trades we didn't open
4. Simplicity: Counter-based diff, no guessing about exact trades

Signal Key = (pair, side, round(tp, precision), round(sl, precision))
Positions = {key: [ticket1, ticket2, ticket3, ...]}

The system maintains counts separately:
  prev_counter = Counter(previous_keys)
  curr_counter = Counter(current_keys)

Diff gives us:
  closed = prev_counter - curr_counter
  opened = curr_counter - prev_counter
"""

from collections import Counter
from dataclasses import dataclass
from typing import Dict, List, Tuple, Optional
from datetime import datetime, timezone, timedelta


@dataclass
class Signal:
    """Structured trading signal from website."""
    pair: str
    side: str  # "BUY" or "SELL"
    open_price: float
    tp: float
    sl: float
    time: datetime  # MUST be absolute UTC time (no relative "24 mins ago")
    frame: str  # "short" or "long"
    status: str  # "ACTIVE" or "CLOSE"
    close_price: Optional[float] = None
    close_reason: Optional[str] = None  # "Achieved", "Trailing Stop", "Manual"

    def __post_init__(self):
        """Validate signal has valid timestamp (UTC)."""
        if not isinstance(self.time, datetime):
            raise ValueError(f"Signal time must be datetime, got {type(self.time)}")
        if self.time.tzinfo is None:
            raise ValueError("Signal time must have timezone info (must be UTC)")

    def get_age_seconds(self) -> float:
        """Get signal age in seconds from now."""
        now = datetime.now(timezone.utc)
        return (now - self.time).total_seconds()

    def is_stale(self, max_age_seconds: int) -> bool:
        """Check if signal is older than max_age."""
        return self.get_age_seconds() > max_age_seconds


class SignalKey:
    """Normalized signal key for deduplication and matching."""

    PRECISION = 3  # Round to 3 decimal places (configurable per symbol)

    @staticmethod
    def build(pair: str, side: str, tp: float, sl: float) -> Tuple[str, str, float, float]:
        """Build normalized key from signal.

        Returns:
            tuple: (pair, side, rounded_tp, rounded_sl)

        Example:
            SignalKey.build("EURUSD", "BUY", 1.15823, 1.15493)
            → ("EURUSD", "BUY", 1.158, 1.155)
        """
        rounded_tp = round(tp, SignalKey.PRECISION)
        rounded_sl = round(sl, SignalKey.PRECISION)
        return (pair, side, rounded_tp, rounded_sl)

    @staticmethod
    def set_precision(precision: int):
        """Configure rounding precision (e.g., 3 for most pairs, 5 for cryptos)."""
        SignalKey.PRECISION = precision


class FuzzyMatcher:
    """Match MT5 positions to website signals using distance-based scoring."""

    THRESHOLD_STANDARD = 0.01      # Default threshold (most pairs)
    THRESHOLD_JPY = 1.0            # JPY pairs (4+ decimals)

    @staticmethod
    def calculate_score(signal_tp, signal_sl, mt5_tp, mt5_sl) -> float:
        """Calculate distance score: abs(tp_diff) + abs(sl_diff)"""
        return abs(signal_tp - mt5_tp) + abs(signal_sl - mt5_sl)

    @staticmethod
    def get_threshold(pair: str) -> float:
        """JPY pairs use larger threshold (4+ decimals)."""
        return FuzzyMatcher.THRESHOLD_JPY if "JPY" in pair else FuzzyMatcher.THRESHOLD_STANDARD

    @staticmethod
    def is_time_compatible(signal_time, mt5_time_opened, max_hours: int = 24) -> bool:
        """Check if signal and MT5 trade opened within reasonable time window.

        Args:
            signal_time: datetime object (UTC) when signal was created
            mt5_time_opened: datetime object (UTC) when MT5 position opened
            max_hours: Maximum time difference in hours (default 24 = same day)

        Returns:
            bool: True if within time window, False if too old/future
        """
        if signal_time is None or mt5_time_opened is None:
            return True  # Can't verify, assume compatible

        try:
            time_diff_hours = abs((signal_time - mt5_time_opened).total_seconds() / 3600)
            return time_diff_hours <= max_hours
        except Exception:
            return True  # Safe fallback: assume compatible if comparison fails

    @staticmethod
    def find_best_match_with_confidence(mt5_tp, mt5_sl, mt5_time, signals_by_key):
        """Find best match with time validation and confidence check.

        SAFETY RULES:
        1. Time compatibility: Signal and MT5 position within 24 hours
        2. Confidence threshold: Best match must be 50% better than 2nd best
        3. Ambiguous matches: Rejected and sent to UNMATCHED bucket

        Args:
            mt5_tp: MT5 position take profit
            mt5_sl: MT5 position stop loss
            mt5_time: datetime when MT5 position opened
            signals_by_key: Dict of {key: [Signal]}

        Returns:
            (best_key, best_signal, best_score, is_confident) - Tuple with confidence flag
        """
        best_key = None
        best_signal = None
        best_score = float('inf')
        second_best_score = float('inf')

        for key, sigs in signals_by_key.items():
            if not sigs:
                continue

            sig = sigs[0]

            # SAFETY: Check time compatibility (prevent old trade mis-mapping)
            if not FuzzyMatcher.is_time_compatible(sig.time, mt5_time):
                continue

            score = FuzzyMatcher.calculate_score(sig.tp, sig.sl, mt5_tp, mt5_sl)

            if score < best_score:
                # Previous best becomes second best
                second_best_score = best_score
                best_score = score
                best_key = key
                best_signal = sig
            elif score < second_best_score:
                second_best_score = score

        # SAFETY: Confidence check - best significantly better than second best (0.5 = 50%)
        # Only accept if best is clearly the winner, not ambiguous
        is_confident = (
            best_key is not None
            and best_score < float('inf')
            and second_best_score < float('inf')
            and best_score < (second_best_score * 0.5)
        )

        return best_key, best_signal, best_score, is_confident

    @staticmethod
    def find_best_match(mt5_tp, mt5_sl, signals_by_key):
        """Find closest signal match.

        Args:
            mt5_tp: MT5 position take profit level
            mt5_sl: MT5 position stop loss level
            signals_by_key: Dict of {key: [Signal, ...]} (already deduplicated)

        Returns:
            (best_key, best_signal, best_score) - (Key tuple, Signal object, score) or (None, None, inf)
        """
        best_key = None
        best_signal = None
        best_score = float('inf')

        for key, sigs in signals_by_key.items():
            if not sigs:
                continue
            # Use first signal for this key (already deduplicated)
            sig = sigs[0]
            score = FuzzyMatcher.calculate_score(sig.tp, sig.sl, mt5_tp, mt5_sl)

            if score < best_score:
                best_score = score
                best_key = key
                best_signal = sig

        return best_key, best_signal, best_score


class PositionStore:
    """Thread-safe position storage: {key: [ticket1, ticket2, ...]}

    Updated for new 2-tuple key format: (pair, executed_side)
    Includes persistence to disk for crash recovery.
    """

    PERSISTENCE_FILE = "positions_store.json"

    def __init__(self):
        """Initialize position store and load persisted state from disk."""
        self.positions: Dict[Tuple[str, str], List[int]] = {}
        # Load from disk on startup
        self.load_from_disk()

    def add_ticket(self, key: Tuple, ticket: int):
        """Add ticket to position list for key."""
        if key not in self.positions:
            self.positions[key] = []
        self.positions[key].append(ticket)

    def pop_ticket(self, key: Tuple) -> Optional[int]:
        """Remove and return one ticket from key (LIFO order)."""
        if key not in self.positions or not self.positions[key]:
            return None
        return self.positions[key].pop()

    def count_for_key(self, key: Tuple) -> int:
        """Get number of open tickets for key."""
        return len(self.positions.get(key, []))

    def get_all_keys(self) -> set:
        """Get all keys with at least one ticket."""
        return {key for key, tickets in self.positions.items() if tickets}

    def has_key(self, key: Tuple) -> bool:
        """Check if key exists and has tickets."""
        return key in self.positions and len(self.positions[key]) > 0

    def get_n_tickets_for_close(self, key: Tuple, count: int) -> List[int]:
        """Get last N tickets for this key WITHOUT removing (LIFO order).

        Used to prepare close operations without modifying state.
        Always returns requested tickets in LIFO order (newest last).

        Args:
            key: Signal key
            count: Number of tickets to get

        Returns:
            List of ticket IDs (up to count, LIFO order)
        """
        tickets = self.positions.get(key, [])
        return list(tickets[-count:]) if count > 0 and tickets else []

    def remove_ticket(self, ticket: int) -> bool:
        """Remove specific ticket by ID from any key.

        Called AFTER successful close to update state.
        Searches all keys to find and remove ticket.

        Args:
            ticket: Ticket ID to remove

        Returns:
            bool: True if found and removed, False if not found
        """
        for key, tickets in self.positions.items():
            if ticket in tickets:
                tickets.remove(ticket)
                return True
        return False

    def clear(self):
        """Clear all positions (for testing)."""
        self.positions.clear()

    def to_dict(self):
        """Serialize to JSON-safe format (tuples → strings)."""
        return {
            str(key): tickets for key, tickets in self.positions.items()
        }

    def from_dict(self, data: dict):
        """Deserialize from JSON-safe format (2-tuple keys: pair, side)."""
        self.positions.clear()
        for key_str, tickets in data.items():
            try:
                # Parse 2-tuple: (pair, side)
                pair, side = eval(key_str)
                key = (pair, side)
                self.positions[key] = list(tickets)
            except Exception as e:
                print(f"  [WARN] Skipping corrupted key {key_str}: {e}")
                continue

    def save_to_disk(self):
        """Persist positions to disk (call after opening/closing trades)."""
        import json
        import os
        import tempfile
        try:
            data = self.to_dict()
            # Atomic write: temp file first, then atomic rename
            temp_fd, temp_path = tempfile.mkstemp(suffix='.json', prefix='positions_')
            try:
                with os.fdopen(temp_fd, 'w') as f:
                    json.dump(data, f)
                os.replace(temp_path, self.PERSISTENCE_FILE)
                # Uncomment for debug: print(f"  [SAVED] Positions persisted: {len(data)} keys")
            except Exception:
                os.close(temp_fd)
                if os.path.exists(temp_path):
                    os.remove(temp_path)
                raise
        except Exception as e:
            print(f"  [SAVE_ERROR] Failed to save positions: {e}")

    def load_from_disk(self):
        """Load positions from disk on startup or recovery."""
        import json
        import os
        try:
            if not os.path.exists(self.PERSISTENCE_FILE):
                # No saved state yet - this is normal on first run
                return

            with open(self.PERSISTENCE_FILE, 'r') as f:
                data = json.load(f)

            self.from_dict(data)
            print(f"  [LOADED] Restored {len(self.positions)} position keys from disk")
        except json.JSONDecodeError as e:
            print(f"  [LOAD_ERROR] Corrupted positions_store.json: {e}, starting fresh")
            self.positions.clear()
        except Exception as e:
            print(f"  [LOAD_ERROR] Failed to load positions: {e}, starting fresh")
            self.positions.clear()


class StateDifferencer:
    """Compute diff between previous and current state using Counters."""

    @staticmethod
    def compute_diff(
        prev_keys: List[Tuple],
        curr_keys: List[Tuple]
    ) -> Tuple[Counter, Counter]:
        """
        Compute which positions were CLOSED and OPENED.

        Args:
            prev_keys: List of keys from previous snapshot
            curr_keys: List of keys from current snapshot

        Returns:
            (closed_counter, opened_counter)

        Example:
            prev = [("EURUSD", "BUY", 1.158, 1.154), ("EURUSD", "BUY", 1.158, 1.154)]
            curr = [("EURUSD", "BUY", 1.158, 1.154)]

            diff = StateDifferencer.compute_diff(prev, curr)
            closed = {("EURUSD", "BUY", 1.158, 1.154): 1}  # 1 closed
            opened = {}
        """
        prev_counter = Counter(prev_keys)
        curr_counter = Counter(curr_keys)

        # What was closed: (prev - curr)
        closed = prev_counter - curr_counter

        # What was opened: (curr - prev)
        opened = curr_counter - prev_counter

        return closed, opened


class SignalFilter:
    """Filter signals for age, validity, duplicates."""

    @staticmethod
    def filter_by_age(signals: List[Signal], max_age_seconds: int) -> List[Signal]:
        """
        Filter signals by age.

        For ACTIVE signals: Skip if older than max_age
        For CLOSE signals: Keep all (we need to close old positions)

        Args:
            signals: List of Signal objects
            max_age_seconds: Maximum age in seconds (e.g., 24*3600 for 24 hours)

        Returns:
            Filtered list of signals
        """
        filtered = []
        for sig in signals:
            if sig.status == "CLOSE":
                # Always keep CLOSE signals (no age filter)
                # These are critical for state consistency
                filtered.append(sig)
            else:  # ACTIVE signals
                if not sig.is_stale(max_age_seconds):
                    filtered.append(sig)
        return filtered

    @staticmethod
    def deduplicate_by_key(signals: List[Signal]) -> List[Signal]:
        """
        Keep only most recent signal per unique key.

        Deduplication key = (pair, side, rounded_tp, rounded_sl)

        Args:
            signals: List of Signal objects (assumed sorted by time DESC)

        Returns:
            Deduplicated list (most recent per key only)
        """
        seen_keys = set()
        deduplicated = []

        for sig in signals:
            key = SignalKey.build(sig.pair, sig.side, sig.tp, sig.sl)
            if key not in seen_keys:
                seen_keys.add(key)
                deduplicated.append(sig)

        return deduplicated


class SafeExecutor:
    """Execute trades safely with validation checks."""

    @staticmethod
    def validate_close(
        key: Tuple,
        close_count: int,
        position_store: PositionStore
    ) -> Tuple[bool, str]:
        """
        Validate that we CAN close this many trades safely.

        Safety rules:
        1. Key must exist in our positions
        2. Don't close more than we have

        Args:
            key: Signal key
            close_count: How many to close
            position_store: Our position tracker

        Returns:
            (is_valid, reason)
        """
        if not position_store.has_key(key):
            return False, f"Key {key} not in positions (not opened by us)"

        available = position_store.count_for_key(key)
        if close_count > available:
            return False, f"Want to close {close_count} but only have {available}"

        return True, "OK"

    @staticmethod
    def prepare_close_operations(
        closed_counter: Counter,
        position_store: PositionStore
    ) -> List[Tuple[Tuple, int]]:
        """
        Prepare safe close operations WITHOUT removing tickets yet.

        CRITICAL CHANGE: Tickets are NOT removed here. They are only removed
        AFTER successful close confirmation. This prevents ticket loss if
        close attempts fail.

        SAFETY RULES:
        1. UNMATCHED positions are skipped entirely (never processed)
        2. Tickets are collected WITHOUT modification
        3. Caller is responsible for removing after successful close

        Args:
            closed_counter: Dict of {key: count_to_close}
            position_store: Our position tracker

        Returns:
            List of (key, ticket) tuples to attempt closing
            Tickets NOT yet removed from positions

        Example:
            [
                (("EURUSD", "BUY", 1.158, 1.154), 12345),
                (("GBPUSD", "SELL", 1.278, 1.272), 12346),
            ]
        """
        operations = []

        for key, count_to_close in closed_counter.items():
            # CRITICAL SAFETY: Skip UNMATCHED positions entirely
            # They should never be closed (guard prevents it anyway)
            if key[0] == "_UNMATCHED_":
                print(f"  [SKIP_UNMATCHED] Won't process {key}: unmatched positions remain unchanged")
                continue

            is_valid, reason = SafeExecutor.validate_close(
                key, count_to_close, position_store
            )

            if not is_valid:
                print(f"  [SKIP CLOSE] {key}: {reason}")
                continue

            # Safe close: use min() to never close more than available
            safe_close_count = min(count_to_close, position_store.count_for_key(key))

            # Get tickets to close (LIFO) WITHOUT removing them yet
            # Tickets stay in positions until close succeeds
            tickets_to_close = position_store.get_n_tickets_for_close(key, safe_close_count)

            for ticket in tickets_to_close:
                if ticket:
                    operations.append((key, ticket))

        return operations


# ══════════════════════════════════════════════════════════════════════════════
# EXAMPLE SIMULATION
# ══════════════════════════════════════════════════════════════════════════════

def example_simulation():
    """Simulate state synchronization with Counter-based logic."""

    print("\n" + "="*80)
    print("STATE CONSISTENCY BOT - SIMULATION")
    print("="*80 + "\n")

    # Initialize
    store = PositionStore()
    print("[INIT] Position store ready\n")

    # --- CYCLE 1: Website shows 3 EURUSD trades ---

    print("--- CYCLE 1: Website snapshot shows EURUSD trades ---")
    prev_keys = []
    print(f"  Previous state: {len(prev_keys)} trades")

    curr_keys = [
        ("EURUSD", "BUY", 1.158, 1.154),
        ("EURUSD", "BUY", 1.158, 1.154),
        ("EURUSD", "BUY", 1.158, 1.154),
    ]
    print(f"  Current state: {len(curr_keys)} trades")
    print(f"    Keys: {curr_keys}\n")

    # Compute diff
    closed, opened = StateDifferencer.compute_diff(prev_keys, curr_keys)
    print(f"  Diff: {dict(closed)} closed, {dict(opened)} opened")

    # Open trades
    for key, count in opened.items():
        print(f"\n  [OPEN] {key}: {count} trade(s)")
        for i in range(count):
            ticket = 10000 + i
            store.add_ticket(key, ticket)
            print(f"    [OK] Opened ticket {ticket}")

    print(f"\n  Store state: {store.to_dict()}\n")

    # --- CYCLE 2: Website closes 1 trade (now shows 2) ---

    print("--- CYCLE 2: Website closes 1 EURUSD trade (may be at new TP) ---")
    prev_keys = [
        ("EURUSD", "BUY", 1.158, 1.154),
        ("EURUSD", "BUY", 1.158, 1.154),
        ("EURUSD", "BUY", 1.158, 1.154),
    ]
    print(f"  Previous state: {len(prev_keys)} trades")

    curr_keys = [
        ("EURUSD", "BUY", 1.158, 1.154),
        ("EURUSD", "BUY", 1.158, 1.154),
    ]
    print(f"  Current state: {len(curr_keys)} trades")
    print(f"    Keys: {curr_keys}\n")

    # Compute diff
    closed, opened = StateDifferencer.compute_diff(prev_keys, curr_keys)
    print(f"  Diff: {dict(closed)} closed, {dict(opened)} opened")

    # Close trades (SAFELY)
    for key, count in closed.items():
        print(f"\n  [CLOSE] {key}: {count} trade(s)")
        ops = SafeExecutor.prepare_close_operations({key: count}, store)
        for op_key, op_count, ticket in ops:
            print(f"    [OK] Closing ticket {ticket}")
            # In real code, actually close the ticket in MT5

    print(f"\n  Store state after close: {store.to_dict()}\n")

    # --- CYCLE 3: Different pair opens ---

    print("--- CYCLE 3: New GBPUSD trade appears (at different TP/SL) ---")
    prev_keys = [
        ("EURUSD", "BUY", 1.158, 1.154),
        ("EURUSD", "BUY", 1.158, 1.154),
    ]
    print(f"  Previous state: {len(prev_keys)} trades")

    curr_keys = [
        ("EURUSD", "BUY", 1.158, 1.154),
        ("EURUSD", "BUY", 1.158, 1.154),
        ("GBPUSD", "SELL", 1.278, 1.272),
    ]
    print(f"  Current state: {len(curr_keys)} trades")
    print(f"    Keys: {curr_keys}\n")

    # Compute diff
    closed, opened = StateDifferencer.compute_diff(prev_keys, curr_keys)
    print(f"  Diff: {dict(closed)} closed, {dict(opened)} opened")

    # Open trades
    for key, count in opened.items():
        print(f"\n  [OPEN] {key}: {count} trade(s)")
        for i in range(count):
            ticket = 10002 + i
            store.add_ticket(key, ticket)
            print(f"    [OK] Opened ticket {ticket}")

    print(f"\n  Store state: {store.to_dict()}\n")

    # --- CYCLE 4: Mixed close and open ---

    print("--- CYCLE 4: EURUSD fully closed, GBPUSD moved (TP/SL different) ---")
    prev_keys = [
        ("EURUSD", "BUY", 1.158, 1.154),
        ("EURUSD", "BUY", 1.158, 1.154),
        ("GBPUSD", "SELL", 1.278, 1.272),
    ]
    print(f"  Previous state: {len(prev_keys)} trades")

    curr_keys = [
        ("GBPUSD", "SELL", 1.275, 1.269),  # Same pair but different TP/SL
    ]
    print(f"  Current state: {len(curr_keys)} trades")
    print(f"    Keys: {curr_keys}\n")

    # Compute diff
    closed, opened = StateDifferencer.compute_diff(prev_keys, curr_keys)
    print(f"  Diff: {dict(closed)} closed, {dict(opened)} opened")

    # Close trades (SAFELY)
    for key, count in closed.items():
        print(f"\n  [CLOSE] {key}: {count} trade(s)")
        ops = SafeExecutor.prepare_close_operations({key: count}, store)
        for op_key, op_count, ticket in ops:
            print(f"    [OK] Closing ticket {ticket}")

    # Open new trades
    for key, count in opened.items():
        print(f"\n  [OPEN] {key}: {count} trade(s)")
        for i in range(count):
            ticket = 10003 + i
            store.add_ticket(key, ticket)
            print(f"    [OK] Opened ticket {ticket}")

    print(f"\n  Store state: {store.to_dict()}\n")

    print("="*80)
    print("SIMULATION COMPLETE")
    print("="*80 + "\n")


if __name__ == "__main__":
    example_simulation()
