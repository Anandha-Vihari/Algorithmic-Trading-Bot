"""
RUNTIME AUDIT INTEGRATION for main.py

Adds comprehensive validation logging to the signal processing pipeline
WITHOUT modifying execution logic.

Place calls at strategic points in main.py:
  1. After signal inversion: log_inversion_result()
  2. After strategy transform: log_strategy_transform()
  3. Before opening trades: log_pre_execution_state()
  4. After opening trades: log_post_execution_state()
"""

from datetime import datetime, timezone, timedelta


class RuntimeAudit:
    """Runtime validation and logging for BOT 1."""

    IST_OFFSET = timedelta(hours=5, minutes=30)

    @staticmethod
    def get_ist_time():
        """Get current IST time."""
        now_utc = datetime.now(timezone.utc)
        return now_utc + RuntimeAudit.IST_OFFSET

    @staticmethod
    def log_inversion_result(signals_before: list, signals_after: list, is_inverted: bool):
        """
        Log signal inversion results.

        Call AFTER: signals_json = SignalInverter.apply_inversion_filter(signals_json)

        Args:
            signals_before: Original signals before inversion
            signals_after: Signals after inversion filter
            is_inverted: Whether inversion was applied
        """
        ist_time = RuntimeAudit.get_ist_time()
        hour = ist_time.hour

        status = "INVERTED" if is_inverted else "NO_INVERT"
        print(f"\n[AUDIT_INVERSION] IST {ist_time.strftime('%H:%M:%S')} Hour={hour} → {status}")

        for i, (before, after) in enumerate(zip(signals_before, signals_after)):
            if before.side != after.side or before.tp != after.tp or before.sl != after.sl:
                print(f"  Signal {i}: {before.pair}")
                print(f"    Before: {before.side:4} TP={before.tp} SL={before.sl}")
                print(f"    After:  {after.side:4} TP={after.tp} SL={after.sl}")
                # Verify correctness
                if is_inverted:
                    assert before.side != after.side, f"Side not inverted: {before.side}"
                    assert before.tp == after.sl, f"TP/SL not swapped: {before.tp} != {after.sl}"
                    print(f"    ✅ Inverted correctly")
            else:
                print(f"  Signal {i}: {before.pair} - NO CHANGE (expected outside window)")
                assert not is_inverted, "Signal changed outside window"

    @staticmethod
    def log_strategy_transform(signals_before: list, signals_after: list, strategy_name: str):
        """
        Log strategy transformation results.

        Call AFTER: signals_json = [strategy.transform_signal(sig) for sig in signals_json]

        Args:
            signals_before: Original signals before strategy transform
            signals_after: Signals after strategy transform
            strategy_name: Name of strategy applied
        """
        ist_time = RuntimeAudit.get_ist_time()
        print(f"\n[AUDIT_STRATEGY] {strategy_name.upper()} transformation")
        print(f"  IST: {ist_time.strftime('%H:%M:%S')}")

        for i, (before, after) in enumerate(zip(signals_before, signals_after)):
            if before.side != after.side:
                print(f"  Signal {i}: {before.pair}")
                print(f"    Before: {before.side:4} TP={before.tp} SL={before.sl}")
                print(f"    After:  {after.side:4} TP={after.tp} SL={after.sl}")
                print(f"    ⚠️  Side changed by strategy")
            else:
                # Verify consistency
                assert before.pair == after.pair, "Pair changed"
                assert before.side == after.side, "Side changed unexpectedly"
                assert before.tp == after.tp, "TP changed"
                assert before.sl == after.sl, "SL changed"

    @staticmethod
    def log_pre_execution_state(signals: list, active_positions: dict):
        """
        Log state before executing trades.

        Call BEFORE opening new positions.

        Args:
            signals: List of signals about to be executed
            active_positions: Dict of currently open positions
        """
        is_within_window = 13 <= RuntimeAudit.get_ist_time().hour < 17

        print(f"\n[AUDIT_PRE_EXECUTION]")
        print(f"  Time Window: {'Inversion Active' if is_within_window else 'Normal Mode'}")
        print(f"  New Signals: {len(signals)}")
        print(f"  Open Positions: {len(active_positions)}")

        signal_keys = {f"{s.pair}/{s.side}" for s in signals}
        print(f"  Signal Keys: {signal_keys}")

        # Check for duplicates
        if len(signal_keys) < len(signals):
            print(f"  ⚠️  WARNING: Duplicate signals detected")
            seen = set()
            for sig in signals:
                key = f"{sig.pair}/{sig.side}"
                if key in seen:
                    print(f"    Duplicate: {key}")
                seen.add(key)

    @staticmethod
    def log_post_execution_state(
        opened_trades: dict,
        expected_side_by_pair: dict,
        strategy_name: str
    ):
        """
        Log execution results after opening trades.

        Call AFTER trades are opened.

        Args:
            opened_trades: Dict mapping ticket -> trade details
            expected_side_by_pair: Dict mapping pair -> expected side from transformed signal
            strategy_name: Name of strategy used
        """
        print(f"\n[AUDIT_POST_EXECUTION]")
        print(f"  Strategy: {strategy_name.upper()}")
        print(f"  Trades Opened: {len(opened_trades)}")

        for ticket, trade_info in opened_trades.items():
            pair = trade_info.get("pair")
            executed_side = trade_info.get("side")
            expected_side = expected_side_by_pair.get(pair)

            if expected_side:
                match = "✅" if executed_side == expected_side else "❌"
                print(f"  {match} {pair}: Executed={executed_side}, Expected={expected_side}")
                assert executed_side == expected_side, \
                    f"Execution mismatch for {pair}: {executed_side} != {expected_side}"

    @staticmethod
    def log_mid_trade_check(positions_mt5: dict, positions_store: dict):
        """
        Log position state to detect mid-trade flipping.

        Call BEFORE/AFTER time boundary crossing.

        Args:
            positions_mt5: Current positions from MT5
            positions_store: Local position store
        """
        ist_time = RuntimeAudit.get_ist_time()
        hour = ist_time.hour

        print(f"\n[AUDIT_MID_TRADE_CHECK] IST {ist_time.strftime('%H:%M:%S')} Hour={hour}")

        for ticket, pos_mt5 in positions_mt5.items():
            pos_store = positions_store.get(ticket, {})
            side_mt5 = pos_mt5.get("type")
            side_store = pos_store.get("side")

            print(f"  Ticket {ticket}: {pos_mt5.get('symbol')}")
            print(f"    MT5 Side: {side_mt5}")
            print(f"    Store Side: {side_store}")

            # Critical assertion: sides must match
            if side_store and side_mt5:
                assert side_mt5 == side_store, \
                    f"Mid-trade flip detected: {side_mt5} (MT5) != {side_store} (store)"
                print(f"    ✅ Sides match (no mid-trade flip)")

    @staticmethod
    def log_counter_diff_state(prev_keys: set, curr_keys: set, opened: dict, closed: set):
        """
        Log counter diff state for integrity verification.

        Call AFTER counter diff computation.

        Args:
            prev_keys: Previous cycle signal keys
            curr_keys: Current cycle signal keys
            opened: Dict of opened signal keys
            closed: Set of closed signal keys
        """
        print(f"\n[AUDIT_COUNTER_DIFF]")
        print(f"  Previous Keys: {prev_keys}")
        print(f"  Current Keys:  {curr_keys}")
        print(f"  Opened:  {set(opened.keys()) if isinstance(opened, dict) else opened}")
        print(f"  Closed:  {closed}")

        # Verify counter diff logic
        newly_opened = curr_keys - prev_keys
        newly_closed = prev_keys - curr_keys

        print(f"\n  Computed:")
        print(f"    Should Open:  {newly_opened}")
        print(f"    Should Close: {newly_closed}")

        # Assert logical consistency
        if opened:
            opened_keys = set(opened.keys()) if isinstance(opened, dict) else opened
            assert newly_opened == opened_keys, \
                f"Opened mismatch: {newly_opened} != {opened_keys}"

        if closed:
            assert newly_closed == closed, \
                f"Closed mismatch: {newly_closed} != {closed}"

        print(f"  ✅ Counter diff logic consistent")

    @staticmethod
    def log_cycle_summary(
        bot_id: int,
        cycle_num: int,
        signals_fetched: int,
        signals_transformed: int,
        trades_opened: int,
        trades_closed: int,
        time_window_active: bool
    ):
        """
        Log cycle summary for audit trail.

        Call AT END of main execution loop.

        Args:
            bot_id: Bot ID
            cycle_num: Cycle number
            signals_fetched: Number of signals fetched
            signals_transformed: Number after transformation
            trades_opened: Number of trades opened this cycle
            trades_closed: Number of trades closed this cycle
            time_window_active: Whether inversion window is active
        """
        ist_time = RuntimeAudit.get_ist_time()
        mode = "INVERTED" if time_window_active else "NORMAL"

        print(f"\n[AUDIT_CYCLE_SUMMARY] BOT{bot_id} Cycle {cycle_num}")
        print(f"  Time: {ist_time.strftime('%Y-%m-%d %H:%M:%S %Z')}")
        print(f"  Mode: {mode}")
        print(f"  Signals: Fetched={signals_fetched}, Transformed={signals_transformed}")
        print(f"  Trades: Opened={trades_opened}, Closed={trades_closed}")


# ─────────────────────────────────────────────────────────────────────────────
# INTEGRATION EXAMPLE (to be added to main.py)
# ─────────────────────────────────────────────────────────────────────────────

INTEGRATION_EXAMPLE = """
# In main.py, after line 387 (signal inversion):

    if config.USE_SIGNAL_INVERTER:
        signals_before_invert = signals_json.copy()
        signals_json = SignalInverter.apply_inversion_filter(signals_json)
        RuntimeAudit.log_inversion_result(
            signals_before_invert,
            signals_json,
            SignalInverter.is_inversion_time()
        )
        invert_status = "INVERTED" if SignalInverter.is_inversion_time() else "NO_INVERT"
        print(f"  [{invert_status}] {len(signals_json)} signals after filter")

# After line 394 (strategy transformation):

    try:
        signals_before_strategy = signals_json.copy()
        signals_json = [strategy.transform_signal(sig) for sig in signals_json]
        RuntimeAudit.log_strategy_transform(
            signals_before_strategy,
            signals_json,
            strategy.name
        )
        print(f"  [STRATEGY] Applied {strategy.name} transformation")
    except Exception as e:
        print(f"  [ERROR] Strategy transformation failed: {e}")

# Before opening new trades (around line 700):

    RuntimeAudit.log_pre_execution_state(signals_to_open, positions_store.get_all())

# After opening new trades:

    opened_trades_info = {...}  # ticket -> {"pair", "side", ...}
    expected_by_pair = {s.pair: s.side for s in signals_to_open}
    RuntimeAudit.log_post_execution_state(
        opened_trades_info,
        expected_by_pair,
        strategy.name
    )

# At cycle end (around line 800+):

    RuntimeAudit.log_cycle_summary(
        BOT_ID,
        cycle_count,
        len(signals_json),
        len(signals_to_open),
        len(trades_opened),
        len(trades_closed),
        SignalInverter.is_inversion_time()
    )
"""

if __name__ == "__main__":
    print("Runtime Audit Integration Module")
    print(f"\nIntegration points in main.py:\n{INTEGRATION_EXAMPLE}")
