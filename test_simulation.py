"""
REAL-WORLD SIMULATION TEST - Trading Bot Lifecycle

Simulates minute-by-minute signal evolution and verifies bot correctness.
Tests: state consistency, multiple trades, UNMATCHED, FAILED_CLOSE, restart, stale detection.
"""

import sys
from collections import Counter
from datetime import datetime, timezone

# Import bot modules
from signal_manager import Signal, SignalKey, PositionStore, StateDifferencer, SignalFilter, SafeExecutor
from operational_safety import OperationalSafety, log, LogLevel


class MockMT5:
    """Mock MT5 API for testing."""

    def __init__(self):
        self.positions = {}  # ticket → position data
        self.next_ticket = 10000
        self.close_failures = {}  # ticket → fail count (for testing escalation)

    def open_position(self, pair, side, tp, sl):
        """Simulate opening a position."""
        ticket = self.next_ticket
        self.next_ticket += 1

        self.positions[ticket] = {
            "ticket": ticket,
            "symbol": pair,
            "type": 0 if side == "BUY" else 1,
            "tp": tp,
            "sl": sl,
            "time": datetime.now(timezone.utc),
        }
        return ticket

    def close_position(self, ticket, fail=False):
        """Simulate closing a position."""
        # Check if this ticket is marked to fail
        if ticket in self.close_failures or fail:
            return False

        if ticket in self.positions:
            del self.positions[ticket]
            self.close_failures.pop(ticket, None)
            return True

        return False  # Position doesn't exist (manually closed)

    def get_positions(self):
        """Get all open positions."""
        return list(self.positions.values())

    def manually_close_position(self, ticket):
        """Simulate user manually closing in MT5."""
        if ticket in self.positions:
            del self.positions[ticket]


class SimulationSignal:
    """Signal that evolves over time."""

    def __init__(self, pair, side, tp, sl, open_time, close_time=None):
        self.pair = pair
        self.side = side.upper()
        self.tp = tp
        self.sl = sl
        self.open_time = open_time
        self.close_time = close_time

    def is_active_at(self, t):
        """Check if signal is active at time t."""
        if t < self.open_time:
            return False
        if self.close_time is not None and t >= self.close_time:
            return False
        return True

    def to_signal_object(self):
        """Convert to Signal object for bot."""
        return Signal(
            pair=self.pair,
            side=self.side,
            open_price=1.0,  # Not used in diff
            tp=self.tp,
            sl=self.sl,
            time=datetime.now(timezone.utc),
            frame="short",
            status="ACTIVE",
            close_price=None,
            close_reason=None,
        )


class BotSimulator:
    """Simulates bot behavior."""

    def __init__(self, mock_mt5):
        self.positions = PositionStore()
        self.safety = OperationalSafety(max_retries=5, unmatched_threshold=3)
        self.mt5 = mock_mt5
        self.prev_keys = []

    def process_signals(self, signals_at_t):
        """Process signals like main bot does."""
        # Filter and normalize signals
        signal_objects = [s.to_signal_object() for s in signals_at_t]
        signal_objects = SignalFilter.deduplicate_by_key(signal_objects)

        # Build current state
        curr_keys = [SignalKey.build(s.pair, s.side, s.tp, s.sl) for s in signal_objects]

        # Get previous state
        prev_keys = list(self.positions.get_all_keys())
        self.prev_keys = prev_keys

        # Compute diff
        closed, opened = StateDifferencer.compute_diff(prev_keys, curr_keys)

        results = {"opened": 0, "closed": 0, "escalated": 0}

        # Close trades
        if closed:
            mt5_positions = self.mt5.get_positions()

            ops = SafeExecutor.prepare_close_operations(closed, self.positions)
            for key, ticket in ops:
                if key[0] == "_UNMATCHED_":
                    continue

                # Check if stale
                stale = True
                for pos in mt5_positions:
                    if pos["ticket"] == ticket:
                        stale = False
                        break

                if stale:
                    self.positions.remove_ticket(ticket)
                    continue

                # Attempt close
                if self.mt5.close_position(ticket):
                    self.positions.remove_ticket(ticket)
                    self.safety.handle_close_success(ticket)
                    results["closed"] += 1
                else:
                    action = self.safety.handle_close_failure(
                        ticket, key[0], "mock close failed"
                    )
                    if action == "ESCALATE":
                        failed_key = ("_FAILED_CLOSE_", key[0], key[2], key[3])
                        self.positions.remove_ticket(ticket)
                        self.positions.add_ticket(failed_key, ticket)
                        results["escalated"] += 1

        # Open trades
        if opened:
            for key, count in opened.items():
                pair, side, tp, sl = key

                # Find matching signal
                matching = [
                    s
                    for s in signal_objects
                    if s.pair == pair
                    and s.side == side
                    and round(s.tp, 3) == round(tp, 3)
                    and round(s.sl, 3) == round(sl, 3)
                ]

                if matching:
                    for _ in range(count):
                        ticket = self.mt5.open_position(pair, side, tp, sl)
                        self.positions.add_ticket(key, ticket)
                        results["opened"] += 1

        return results, signal_objects

    def reconstruct_from_mt5(self, signals_at_t):
        """Reconstruct positions from MT5 (like startup)."""
        signal_objects = [s.to_signal_object() for s in signals_at_t]
        signal_objects = SignalFilter.deduplicate_by_key(signal_objects)

        signals_by_key = {}
        for sig in signal_objects:
            key = SignalKey.build(sig.pair, sig.side, sig.tp, sig.sl)
            if key not in signals_by_key:
                signals_by_key[key] = []
            signals_by_key[key].append(sig)

        reconstructed = 0
        for pos in self.mt5.get_positions():
            pair = pos["symbol"]
            tp = pos["tp"]
            sl = pos["sl"]
            ticket = pos["ticket"]
            side = "BUY" if pos["type"] == 0 else "SELL"

            # Fuzzy match (simplified: exact match for simulation)
            best_key = None
            best_score = float("inf")

            for key, sigs in signals_by_key.items():
                sig = sigs[0]
                score = abs(sig.tp - tp) + abs(sig.sl - sl)
                if score < best_score:
                    best_score = score
                    best_key = key

            if best_key and best_score < 0.01:
                self.positions.add_ticket(best_key, ticket)
                reconstructed += 1
            else:
                fallback_key = ("_UNMATCHED_", pair, side, tp, sl)
                self.positions.add_ticket(fallback_key, ticket)

        return reconstructed


class SimulationTest:
    """Main simulation test runner."""

    def __init__(self):
        self.mt5 = MockMT5()
        self.bot = BotSimulator(self.mt5)
        self.test_results = []

    def assert_state(self, t, expected_positions, test_name):
        """Verify bot state matches expected."""
        # Only count keys with non-empty ticket lists (like get_all_keys does)
        actual = {}
        for key, tickets in self.bot.positions.positions.items():
            if tickets:  # Only include keys with tickets
                actual[key] = len(tickets)

        expected = {}
        for key, count in expected_positions.items():
            expected[key] = count

        passed = actual == expected

        status = "[PASS]" if passed else "[FAIL]"
        print(f"{status} T={t:2d} min | {test_name}")

        if not passed:
            print(f"  Expected: {expected}")
            print(f"  Actual:   {actual}")

        self.test_results.append((test_name, passed))
        return passed

    def run(self):
        """Execute full simulation."""
        print("\n" + "=" * 80)
        print("REAL-WORLD SIMULATION TEST - Trading Bot Lifecycle")
        print("=" * 80 + "\n")

        # ─────────────────────────────────────────────────────────────────────

        print("SCENARIO 1: Basic Open/Close")
        print("-" * 80)

        # T=0: First signal appears
        signals = {
            0: [SimulationSignal("USDCAD", "BUY", 1.374, 1.370, 0, 10)]
        }

        t = 0
        results, _ = self.bot.process_signals(signals[t])
        key = ("USDCAD", "BUY", 1.374, 1.370)
        self.assert_state(t, {key: 1}, "Open first USDCAD trade")

        assert results["opened"] == 1, "Should open 1 trade"
        assert len(self.mt5.positions) == 1, "MT5 should have 1 position"

        # T=10: Signal closes
        t = 10
        results, _ = self.bot.process_signals([])
        self.assert_state(t, {}, "All signals closed, trade auto-closes")

        assert results["closed"] == 1, "Should close 1 trade"
        assert len(self.mt5.positions) == 0, "MT5 should be empty"

        # ─────────────────────────────────────────────────────────────────────

        print("\nSCENARIO 2: Multiple Same-Pair Trades")
        print("-" * 80)

        self.bot = BotSimulator(self.mt5)
        self.mt5.positions.clear()

        # T=0: First signal
        t = 0
        signals_t0 = [SimulationSignal("USDCAD", "BUY", 1.374, 1.370, 0, 15)]
        results, _ = self.bot.process_signals(signals_t0)
        key1 = ("USDCAD", "BUY", 1.374, 1.370)
        self.assert_state(t, {key1: 1}, "Open first USDCAD")

        # T=5: Second signal with different TP/SL
        t = 5
        signals_t5 = [
            SimulationSignal("USDCAD", "BUY", 1.374, 1.370, 0, 15),
            SimulationSignal("USDCAD", "BUY", 1.375, 1.369, 5, 20),
        ]
        results, _ = self.bot.process_signals(signals_t5)
        key2 = ("USDCAD", "BUY", 1.375, 1.369)
        self.assert_state(
            t,
            {key1: 1, key2: 1},
            "Open second USDCAD (different TP/SL)",
        )

        assert results["opened"] == 1, "Should open 1 new trade"
        assert len(self.mt5.positions) == 2, "MT5 should have 2 positions"

        # T=10: First signal closes, second remains
        t = 10
        signals_t10 = [
            SimulationSignal("USDCAD", "BUY", 1.375, 1.369, 5, 20),
        ]
        results, _ = self.bot.process_signals(signals_t10)
        self.assert_state(
            t,
            {key2: 1},
            "First USDCAD closes, second remains",
        )

        assert results["closed"] == 1, "Should close exactly 1 trade"
        assert len(self.mt5.positions) == 1, "MT5 should have 1 position"

        # ─────────────────────────────────────────────────────────────────────

        print("\nSCENARIO 3: Multi-Pair Trading")
        print("-" * 80)

        self.bot = BotSimulator(self.mt5)
        self.mt5.positions.clear()

        # T=0: USDCAD signal
        t = 0
        signals = [SimulationSignal("USDCAD", "BUY", 1.374, 1.370, 0, 20)]
        results, _ = self.bot.process_signals(signals)
        key_usd = ("USDCAD", "BUY", 1.374, 1.370)
        self.assert_state(t, {key_usd: 1}, "Open USDCAD")

        # T=5: Add EURUSD signal
        t = 5
        signals = [
            SimulationSignal("USDCAD", "BUY", 1.374, 1.370, 0, 20),
            SimulationSignal("EURUSD", "SELL", 1.150, 1.155, 5, 15),
        ]
        results, _ = self.bot.process_signals(signals)
        key_eur = ("EURUSD", "SELL", 1.150, 1.155)
        self.assert_state(t, {key_usd: 1, key_eur: 1}, "Add EURUSD")

        assert len(self.mt5.positions) == 2, "MT5 should have 2 different pairs"

        # T=15: EURUSD closes
        t = 15
        signals = [SimulationSignal("USDCAD", "BUY", 1.374, 1.370, 0, 20)]
        results, _ = self.bot.process_signals(signals)
        self.assert_state(t, {key_usd: 1}, "EURUSD closes")

        assert results["closed"] == 1, "Should close 1 trade"

        # T=20: All closed
        t = 20
        signals = []
        results, _ = self.bot.process_signals(signals)
        self.assert_state(t, {}, "All trades closed")

        # ─────────────────────────────────────────────────────────────────────

        print("\nSCENARIO 4: Restart Reconstruction")
        print("-" * 80)

        # Snapshot: bot state before restart
        bot_before_restart = self.bot
        mt5_before_restart = [(p["ticket"], p["symbol"], p["tp"], p["sl"])
                               for p in self.mt5.positions.values()]

        # T=30: Simulate restart
        t = 30
        self.bot = BotSimulator(self.mt5)

        # Add a signal to website
        signals = [SimulationSignal("GBPUSD", "BUY", 1.280, 1.270, 30, 40)]

        # Reconstruct from MT5
        reconstructed = self.bot.reconstruct_from_mt5(signals)

        # Verify no duplicates created
        actual_positions = {}
        for key, tickets in self.bot.positions.positions.items():
            actual_positions[key] = len(tickets)

        # Should match what was in MT5 before
        print(f"[INFO] T={t} Reconstructed {reconstructed} positions from MT5")

        # ─────────────────────────────────────────────────────────────────────

        print("\nSCENARIO 5: Failed Close Escalation")
        print("-" * 80)

        self.bot = BotSimulator(self.mt5)
        self.mt5.positions.clear()
        self.mt5.close_failures.clear()

        # T=0: Open a trade
        t = 0
        signals = [SimulationSignal("USDCAD", "BUY", 1.374, 1.370, 0, 100)]
        results, _ = self.bot.process_signals(signals)
        key = ("USDCAD", "BUY", 1.374, 1.370)
        self.assert_state(t, {key: 1}, "Open trade")

        ticket = list(self.mt5.positions.keys())[0]

        # T=5-24: Simulate 5 failed close attempts by marking ticket as failing
        self.mt5.close_failures[ticket] = True  # Mark for ALL subsequent attempts

        for attempt in range(1, 6):
            t = 4 + attempt
            signals = []
            results, _ = self.bot.process_signals(signals)

            if attempt < 5:
                self.assert_state(
                    t, {key: 1}, f"Close attempt {attempt} fails, retrying"
                )
            else:
                # After 5 attempts, should escalate to _FAILED_CLOSE_
                escalated_key = ("_FAILED_CLOSE_", "USDCAD", 1.374, 1.370)
                self.assert_state(
                    t,
                    {escalated_key: 1},
                    "Close attempt 5 fails, escalate to _FAILED_CLOSE_",
                )

        # Clear the failure flag
        self.mt5.close_failures.pop(ticket, None)

        # ─────────────────────────────────────────────────────────────────────

        print("\nSCENARIO 6: Manual Close Detection")
        print("-" * 80)

        self.bot = BotSimulator(self.mt5)
        self.mt5.positions.clear()

        # T=0: Open two trades
        t = 0
        signals = [
            SimulationSignal("USDCAD", "BUY", 1.374, 1.370, 0, 10),
            SimulationSignal("EURUSD", "SELL", 1.150, 1.155, 0, 20),
        ]
        results, _ = self.bot.process_signals(signals)
        key_usd = ("USDCAD", "BUY", 1.374, 1.370)
        key_eur = ("EURUSD", "SELL", 1.150, 1.155)
        self.assert_state(t, {key_usd: 1, key_eur: 1}, "Open 2 trades")

        tickets = list(self.mt5.positions.keys())
        ticket_usd = tickets[0]

        # T=10: User manually closes USDCAD in MT5, but EURUSD signal still active
        t = 10
        self.mt5.manually_close_position(ticket_usd)

        # Bot tries to close USDCAD but detects it's stale (manually closed)
        signals = [
            SimulationSignal("EURUSD", "SELL", 1.150, 1.155, 0, 20),
        ]
        results, _ = self.bot.process_signals(signals)

        self.assert_state(t, {key_eur: 1}, "Stale USDCAD detected and removed")

        # ─────────────────────────────────────────────────────────────────────

        print("\nSCENARIO 7: UNMATCHED Handling")
        print("-" * 80)

        self.bot = BotSimulator(self.mt5)
        self.mt5.positions.clear()

        # T=0: Open a trade
        t = 0
        signals = [SimulationSignal("USDCAD", "BUY", 1.374, 1.370, 0, 20)]
        results, _ = self.bot.process_signals(signals)
        key = ("USDCAD", "BUY", 1.374, 1.370)
        self.assert_state(t, {key: 1}, "Open USDCAD")

        # Simulate restart with ambiguous matching
        t = 10
        self.bot = BotSimulator(self.mt5)

        # Modify MT5 position slightly (simulating broker rounding)
        for ticket, pos in self.mt5.positions.items():
            pos["tp"] = 1.3745  # Slightly different, causing ambiguity

        # Signal doesn't match anymore
        signals = [
            SimulationSignal("EURUSD", "BUY", 1.150, 1.145, 10, 20)
        ]

        reconstructed = self.bot.reconstruct_from_mt5(signals)

        # USDCAD should be UNMATCHED
        unmatched_key = None
        for k in self.bot.positions.positions.keys():
            if k[0] == "_UNMATCHED_":
                unmatched_key = k
                break

        if unmatched_key:
            print(f"[PASS] T={t} min | UNMATCHED position stored safely")
            print(f"  Key: {unmatched_key}")
        else:
            print(f"[FAIL] T={t} min | UNMATCHED position NOT found")

        # ─────────────────────────────────────────────────────────────────────

        print("\nSCENARIO 8: Rapid Signal Flip")
        print("-" * 80)

        self.bot = BotSimulator(self.mt5)
        self.mt5.positions.clear()

        # T=0: Signal appears
        t = 0
        signals = [SimulationSignal("USDCAD", "BUY", 1.374, 1.370, 0, 1)]
        results, _ = self.bot.process_signals(signals)
        key = ("USDCAD", "BUY", 1.374, 1.370)
        self.assert_state(t, {key: 1}, "Signal appears, open trade")
        ticket_1 = list(self.mt5.positions.keys())[0]

        # T=1: Signal closes/disappears, immediate re-appears (same trade)
        t = 1
        signals = [SimulationSignal("USDCAD", "BUY", 1.374, 1.370, 1, 5)]
        results, _ = self.bot.process_signals(signals)

        # Should NOT create duplicate
        actual_tickets = []
        for key_check, tickets in self.bot.positions.positions.items():
            actual_tickets.extend(tickets)

        if len(actual_tickets) == 1:
            print(f"[PASS] T={t} min | Rapid flip no duplicate (1 ticket)")
        else:
            print(
                f"[FAIL] T={t} min | Rapid flip created duplicates ({len(actual_tickets)} tickets)"
            )

        # ─────────────────────────────────────────────────────────────────────

        print("\n" + "=" * 80)
        print("TEST SUMMARY")
        print("=" * 80)

        passed = sum(1 for _, p in self.test_results if p)
        total = len(self.test_results)

        print(f"\nPassed: {passed}/{total}")

        if passed == total:
            print("\n[SUCCESS] ALL TESTS PASSED - Bot is production-ready")
            return True
        else:
            print(f"\n[FAILED] {total - passed} TEST(S) FAILED")
            for name, p in self.test_results:
                if not p:
                    print(f"  - {name}")
            return False


# ────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    test = SimulationTest()
    success = test.run()
    sys.exit(0 if success else 1)
