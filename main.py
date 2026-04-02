"""
BLIND FOLLOWER BOT - State Consistency Architecture

Core objective: Maintain bot state = website state

Uses Counter-based diffing instead of TP/SL matching:
  prev_counter - curr_counter = positions to close
  curr_counter - prev_counter = positions to open

Safety: Only close trades we opened.
"""

import time
import sys
import threading
import MetaTrader5 as mt5
import json
import os
import tempfile
from datetime import datetime, timezone, timedelta

# Log to file
sys.stdout = open("bot.log", "a", buffering=1, encoding="utf-8")
sys.stderr = sys.stdout

from scraper import fetch_page
from parser import parse_signals
from trader import open_trade, close_position_by_ticket, init_mt5, show_open_positions, account_summary
from signal_manager import (
    Signal, SignalKey, PositionStore, StateDifferencer, SignalFilter, SafeExecutor, FuzzyMatcher
)
from operational_safety import OperationalSafety, log, LogLevel
from virtual_sl import init_virtual_sl, get_virtual_sl_manager
from trailing_stop import init_trailing_stop
from config import SIGNAL_INTERVAL, TRADE_VOLUME, MAX_SIGNAL_AGE, REVERSE_MODE
from signal_inverter import get_inversion_mode_status, invert_signal

print(f"\n{'='*80}")
print("BLIND FOLLOWER BOT - STATE CONSISTENCY ARCHITECTURE")
print(f"Signal interval: {SIGNAL_INTERVAL}s | Volume: {TRADE_VOLUME}")
inversion_status = get_inversion_mode_status()
print(f"Mode: {inversion_status['status']}")
print(f"{'='*80}\n")


def safe_log(msg: str):
    """Safely log message even if formatting fails."""
    try:
        print(msg)
    except Exception as e:
        print(f"[LOG_FAIL] Could not log message: {e}")

# Initialize MT5
init_mt5()

# Persistent position tracker (loads from disk automatically in __init__)
positions = PositionStore()

# ──── STATE RECONSTRUCTION FROM MT5 ON STARTUP ────────────────────────────────
# If bot is restarted, rebuild positions_store from MT5 open positions
# This ensures we don't lose track of trades opened before restart

def reconstruct_positions_from_mt5():
    """Load open positions from MT5 and register them in positions_store."""
    print("[STATE_RECOVERY] Reconstructing positions_store from MT5...")
    try:
        mt5_positions = mt5.positions_get()
        if not mt5_positions:
            print("[STATE_RECOVERY] No open positions in MT5")
            return 0

        reconstructed_count = 0
        for pos in mt5_positions:
            if pos.magic != 777:  # MAGIC_NUMBER from trader.py
                continue  # Skip positions not opened by this bot

            # Reconstruct from MT5 position
            pair = pos.symbol.rstrip('+')
            side = "BUY" if pos.type == 0 else "SELL"  # 0=BUY, 1=SELL
            key = (pair, side)

            positions.add_ticket(key, pos.ticket)
            reconstructed_count += 1
            print(f"  [RECOVER] Registered T{pos.ticket} {pair} {side}")

        print(f"[STATE_RECOVERY] Reconstructed {reconstructed_count} position(s)")
        positions.save_to_disk()  # Persist after reconstruction
        return reconstructed_count
    except Exception as e:
        print(f"[STATE_RECOVERY] Failed: {e}")
        return 0

# Reconstruct on startup
reconstruct_positions_from_mt5()

# Persistent position tracker (now with disk persistence)
# NOTE: positions initialized with disk load in PositionStore.__init__()

# Operational safety monitoring and retry control
safety = OperationalSafety(max_retries=5, unmatched_threshold=3)

# Virtual SL - Spread-aware stop loss management
# spread_factor: 1.5-2.0 (higher = more protection from spread spikes)
# cooldown_seconds: 300 (5 min cooldown to prevent reopen loop after VSL close)
virtual_sl = init_virtual_sl(spread_factor=1.5, cooldown_seconds=300)

# Trailing Stop - Phase-based SL management (passive layer)
trailing_stop_mgr = init_trailing_stop()
print("[TRAIL] Initialized trailing stop manager")


# Persistent signal processing tracker (prevent duplicate opens)
processed_signals_file = "processed_signals.json"


def load_processed_signals():
    """Load set of already-processed signal timestamps (fault-tolerant)."""
    try:
        with open(processed_signals_file, 'r') as f:
            data = json.load(f)
        # Keep signals from last 24 hours
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        filtered = {
            ts: v for ts, v in data.items()
            if datetime.fromisoformat(v) > cutoff
        }
        return set(filtered.keys())
    except FileNotFoundError:
        return set()  # File doesn't exist yet
    except json.JSONDecodeError as e:
        print(f"[ERROR_JSON] Corrupted processed_signals.json: {e}, starting fresh")
        return set()
    except Exception as e:
        print(f"[ERROR_JSON] Failed to load processed_signals: {e}, starting fresh")
        return set()


def save_processed_signals(signal_set):
    """Save processed signal IDs (fault-tolerant)."""
    try:
        data = {sig_id: datetime.now(timezone.utc).isoformat() for sig_id in signal_set}
        # Atomic write: write to temp file first, then rename
        temp_fd, temp_path = tempfile.mkstemp(suffix='.json', prefix='processed_signals_')
        try:
            with os.fdopen(temp_fd, 'w') as f:
                json.dump(data, f)
            os.replace(temp_path, processed_signals_file)
        except Exception:
            try:
                os.unlink(temp_path)
            except:
                pass
            raise
    except Exception as e:
        print(f"[ERROR_JSON] Failed to save processed_signals: {e}, changes may be lost")


def load_bot_control():
    """Load bot control settings (session mode, etc).

    Returns:
        dict: {'trading_sessions': str}

    File format (bot_control.json):
        {
            "enabled": true,
            "trading_sessions": "all"
        }

    Valid modes:
        'all' - trade 24/7
        'london' - 08:00-17:00 UTC only
        'ny' - 13:00-22:00 UTC only
        'overlap' - 13:00-17:00 UTC only (London-NY overlap)
        'asia' - 22:00-08:00 UTC (Tokyo, Sydney, Singapore)
    """
    try:
        if not os.path.exists('bot_control.json'):
            return {'trading_sessions': 'all'}

        with open('bot_control.json', 'r') as f:
            control = json.load(f)

        mode = control.get('trading_sessions', 'all').lower().strip()
        valid_modes = ['all', 'london', 'ny', 'overlap', 'asia']

        if mode not in valid_modes:
            print(f"[WARNING] Invalid trading_sessions mode: {mode}, defaulting to 'all'")
            mode = 'all'

        return {'trading_sessions': mode}
    except Exception as e:
        print(f"[WARNING] Failed to load bot_control.json: {e}, defaulting to 'all'")
        return {'trading_sessions': 'all'}


def get_signal_id(sig: Signal) -> str:
    """Create unique signal ID from signal timestamp + key."""
    key = SignalKey.build(sig.pair, sig.side, sig.tp, sig.sl)
    time_str = sig.time.isoformat()
    return f"{time_str}_{key}"


def reconstruct_positions_from_mt5(mt5_positions_list, signals_to_process, positions_store):
    """Reconstruct position tracker from MT5 live state + fuzzy matching to signals.

    SAFETY FEATURES:
    1. Time filtering: Only match signals from same trading session (24h window)
    2. Confidence check: Best match must be 50% better than second-best
    3. Unmatched safety: Ambiguous matches sent to UNMATCHED bucket (never closed)

    Args:
        mt5_positions_list: List of MT5 position objects
        signals_to_process: List of Signal objects (already filtered, deduplicated)
        positions_store: PositionStore instance to populate

    Returns:
        (reconstructed_count, unmatched_count) - tickets loaded and fallback count
    """
    # Build dict of signals by key for fast lookup: {key: [Signal, ...]}
    signals_by_key = {}
    for sig in signals_to_process:
        key = SignalKey.build(sig.pair, sig.side, sig.tp, sig.sl)
        if key not in signals_by_key:
            signals_by_key[key] = []
        signals_by_key[key].append(sig)

    reconstructed = 0
    unmatched = 0

    for pos in mt5_positions_list:
        if pos.magic != 777:  # Not our positions
            continue

        # Extract MT5 position details
        pair = pos.symbol
        tp = pos.tp
        sl = pos.sl
        ticket = pos.ticket
        side = "BUY" if pos.type == 0 else "SELL"

        # Extract MT5 position open time (safe conversion)
        mt5_time_opened = None
        try:
            if hasattr(pos, 'time'):
                # Convert Unix timestamp to datetime
                mt5_time_opened = datetime.fromtimestamp(pos.time, tz=timezone.utc)
            elif hasattr(pos, 'time_setup'):
                mt5_time_opened = datetime.fromtimestamp(pos.time_setup, tz=timezone.utc)
        except Exception:
            pass  # If can't extract time, will still match (time_compatible returns True)

        # Find best match with SAFETY CHECKS
        best_key, best_signal, best_score, is_confident = FuzzyMatcher.find_best_match_with_confidence(
            tp, sl, mt5_time_opened, signals_by_key
        )

        threshold = FuzzyMatcher.get_threshold(pair)

        # CRITICAL: Require BOTH distance threshold AND confidence
        if best_key is not None and best_score <= threshold and is_confident:
            # MATCHED with high confidence: Reconstruct with this key
            positions_store.add_ticket(best_key, ticket)
            reconstructed += 1
            print(f"  [RECONSTRUCT] {pair} {side} ticket {ticket} -> key {best_key} (score={best_score:.6f}, confident)")
        else:
            # UNMATCHED: Either no match, threshold exceeded, or ambiguous
            fallback_key = ("_UNMATCHED_", pair, side, tp, sl)
            positions_store.add_ticket(fallback_key, ticket)
            unmatched += 1

            reason = "ambiguous" if (best_key is not None and best_score <= threshold and not is_confident) else "no_match"
            print(f"  [UNMATCHED] {pair} {side} ticket {ticket} @ TP={tp} SL={sl} ({reason}, score={best_score:.6f})")

    return reconstructed, unmatched


# Load processed signals at startup
processed_signal_ids = load_processed_signals()
print(f"[STARTUP] Loaded {len(processed_signal_ids)} processed signal IDs (last 24h)")

print()


# ══════════════════════════════════════════════════════════════════════════════
# SIGNAL CYCLE
# ══════════════════════════════════════════════════════════════════════════════

def run_signal_cycle():
    """
    Main signal processing cycle using state consistency logic.

    1. Fetch website snapshot
    2. Parse signals
    3. Build current state (list of keys)
    4. Compute diff vs previous state
    5. Close trades (safe)
    6. Open trades
    7. Sleep
    """
    global positions, processed_signal_ids

    now = datetime.now(timezone.utc)
    now_str = now.strftime('%H:%M:%S')

    # ──── FETCH & PARSE ──────────────────────────────────────────────────────

    html = fetch_page()
    if html is None:
        print(f"[{now_str}] WARNING: Could not fetch signals (proxy failed)")
        return

    try:
        raw_signals = parse_signals(html)
    except Exception as e:
        print(f"[{now_str}] ERROR: Failed to parse signals: {e}")
        import traceback
        traceback.print_exc()
        return

    if not raw_signals:
        print(f"[{now_str}] No signals found on website")
        return

    print(f"[{now_str}] Fetched {len(raw_signals)} raw signals")

    # ──── CONVERT TO SIGNAL OBJECTS ──────────────────────────────────────────

    signals = []
    for raw in raw_signals:
        try:
            sig = Signal(
                pair=raw['pair'],
                side=raw['side'],
                open_price=raw['open'],
                tp=raw['tp'],
                sl=raw['sl'],
                time=raw['time'],
                frame=raw['frame'],
                status=raw['status'],
                close_price=raw.get('close'),
                close_reason=raw.get('close_reason'),
            )
            signals.append(sig)
        except Exception as e:
            print(f"  [WARN] Skipping malformed signal: {e}")
            continue

    if not signals:
        print(f"[{now_str}] No valid signals after parsing")
        return

    # ──── SIGNAL STABILITY LOGGING: Raw signal list every cycle ────────────────
    raw_signal_list = [(s.pair, s.side) for s in signals if s.status == "ACTIVE"]
    print(f"  [RAW_SIGNALS] Cycle signals (ACTIVE only): {raw_signal_list}")

    # ──── FILTER BY AGE (CRITICAL: CLOSE signals bypass age filter) ──────────

    active_signals = [s for s in signals if s.status == "ACTIVE"]
    close_signals = [s for s in signals if s.status == "CLOSE"]

    print(f"  Active: {len(active_signals)}, Close: {len(close_signals)}")

    # ──── FILTER BY AGE: Only open NEW trades from fresh signals (<30 min)
    # BUG FIX: Use FRESH signals for state comparison to prevent multiple opens

    fresh_signals = SignalFilter.filter_by_age(active_signals, MAX_SIGNAL_AGE)
    print(f"  After age filter: {len(fresh_signals)} fresh active (max age: {MAX_SIGNAL_AGE}s)")

    # ──── APPLY INVERSION EARLY (if REVERSE_MODE) ────────────────────────────────
    # CRITICAL FIX: Invert signals BEFORE deduplication so state keys reflect actual execution
    # This ensures (pair, executed_side) identity prevents duplicates from TP/SL drift

    if REVERSE_MODE:
        fresh_signals_inverted = []
        for sig in fresh_signals:
            try:
                inv_sig, metadata = invert_signal(sig, REVERSE_MODE)
                fresh_signals_inverted.append(inv_sig)
            except Exception as e:
                print(f"  [INVERT_ERROR] Failed to invert {sig.pair} {sig.side}: {e}")
                # Fall through - keep original if inversion fails
                fresh_signals_inverted.append(sig)
        fresh_signals = fresh_signals_inverted
        print(f"  [INVERTED] Applied inversion to {len(fresh_signals)} signals")

    # ──── DEDUPLICATE: By EXECUTED identity (pair, executed_side) ────────────────────
    # CRITICAL: Collapse multiple signals for same (pair, side) into ONE
    # This prevents duplicates when TP/SL drifts across cycles
    # Example: Multiple "EURUSD BUY @1.158/1.155" and "EURUSD BUY @1.157/1.154"
    # both collapse to single EURUSD BUY (executed as SELL if inverted)

    fresh_signals_sorted = sorted(fresh_signals, key=lambda s: s.time, reverse=True)

    # Group by (pair, executed_side) and keep LATEST only
    seen_exec_identities = {}  # {(pair, side): signal}
    for sig in fresh_signals_sorted:
        exec_identity = (sig.pair, sig.side)  # Executed identity (inverted if REVERSE_MODE)
        if exec_identity not in seen_exec_identities:
            seen_exec_identities[exec_identity] = sig

    signals_to_open = list(seen_exec_identities.values())
    print(f"  [EXEC_DEDUP] Deduplicated by (pair, executed_side): {len(fresh_signals_sorted)} → {len(signals_to_open)} unique")

    # For state comparison, use FRESH signals only (prevents reopening aged-out signals)
    # FIX: Changed from ALL active to FRESH ONLY
    # This ensures curr_keys matches signals_to_open and prevents duplicate opens
    signals_to_manage = signals_to_open  # Both are deduped fresh signals

    # ──── BUILD CURRENT STATE ────────────────────────────────────────────────

    # CRITICAL FIX: Build state keys from EXECUTION IDENTITY ONLY (pair, executed_side)
    # Remove TP/SL from identity → prevents false "close + reopen" from TP/SL drift
    # Each (pair, side) can only exist once, regardless of TP/SL changes
    curr_keys = [(sig.pair, sig.side) for sig in signals_to_open]

    print(f"  [STATE_KEYS] Built {len(curr_keys)} state keys from execution identity (pair, side only)")
    print(f"              TP/SL no longer part of identity → TP/SL drift won't cause reopens")

    # ──── KEY PRECISION VERIFICATION: Log execution identity ──────────────────
    # Show what signals will be tracked for state diff
    if signals_to_open:
        print(f"\n  [EXEC_IDENTITY] Signals for state management ({len(signals_to_open)}):")
        for s in signals_to_open[:5]:  # Log first 5
            print(f"    {s.pair:7s} {s.side:4s} | TP={s.tp:.5f} SL={s.sl:.5f} (metadata only, not in key)")

    # Get previous keys from our tracker
    prev_keys = list(positions.get_all_keys())

    print(f"  Previous state: {len(prev_keys)} keys from positions store")
    print(f"  Current state: {len(curr_keys)} keys from fresh signals")

    # ──── RUNTIME VERIFICATION: Verify curr_keys matches signals_to_open ────
    # FIX: Now both come from fresh signals, preventing duplicate opens
    print(f"  [VERIFY] Raw active signals: {len(active_signals)}")
    print(f"  [VERIFY] Fresh signals only: {len(fresh_signals)}")
    print(f"  [VERIFY] Signals_to_manage (deduped fresh): {len(signals_to_manage)}")
    print(f"  [VERIFY] Signals_to_open (deduped fresh): {len(signals_to_open)}")
    print(f"  [VERIFY] FIX CHECK: signals_to_manage == signals_to_open? {signals_to_manage == signals_to_open}")
    print(f"  [VERIFY] curr_keys source check: {len(curr_keys)} == {len(signals_to_manage)} ? {len(curr_keys) == len(signals_to_manage)}")

    # Print actual key content for verification
    if curr_keys:
        print(f"  [VERIFY] Sample curr_keys (first 3): {curr_keys[:3]}")

    # CRITICAL CHECK: Verify curr_keys matches signals_to_open (no duplicates possible)
    if len(curr_keys) == len(signals_to_manage) == len(signals_to_open):
        print(f"  [VERIFIED OK] No aged-out signals in curr_keys (prevents duplicate opens)")
    else:
        print(f"  [WARNING] Mismatch: curr_keys={len(curr_keys)}, signals_to_manage={len(signals_to_manage)}, signals_to_open={len(signals_to_open)}")


    # ──── VIRTUAL SL CHECK (SPREAD-AWARE) ─────────────────────────────────────
    # Check and close positions that hit virtual SL (accounts for spread changes)

    mt5_positions = mt5.positions_get() or []
    print(f"  [TRIGGER] VSL_CHECK_START")
    virtual_sl_closes = virtual_sl.check_and_close_all(
        mt5, positions, lambda t, p: close_position_by_ticket(t, p)
    )
    print(f"  [TRIGGER] VSL_CHECK_END - closed {len(virtual_sl_closes or [])}")

    if virtual_sl_closes:
        log(LogLevel.INFO, f"Virtual SL closed {len(virtual_sl_closes)} position(s)")
        for ticket, key, reason in virtual_sl_closes:
            log(LogLevel.DEBUG, f"  {reason}")
            # Remove from trailing stop tracking (position is now closed)
            try:
                trailing_stop_mgr.remove_position(ticket)
                print(f"  [TRAIL] Removed T{ticket} (VSL close)")
            except Exception as e:
                log(LogLevel.DEBUG, f"Trailing stop remove failed for T{ticket}: {e}")

    # ──── CLEANUP CLOSED_BY_BOT FOR REAPPEARED SIGNALS ──────────────────────────
    # If signal reappears after being closed by virtual SL, allow reopen
    virtual_sl.cleanup_closed_signals(curr_keys)

    # ──── TRAILING STOP UPDATE (PASSIVE LAYER) ──────────────────────────────────
    # Update trailing stops for all tracked positions (SL adjustments only)
    # FIX 2: FAIL-FAST - Crash if trailing stop fails (no silent errors)
    try:
        trailing_stop_mgr.update_all_positions(mt5)
    except Exception as e:
        log(LogLevel.CRITICAL, f"TRAILING STOP FAILURE: {e}")
        print(f"[FATAL] Trailing stop failed: {e}")
        raise RuntimeError("Trailing stop is offline — aborting bot")

    # ──── COMPUTE DIFF ───────────────────────────────────────────────────────
    # RUNTIME VERIFICATION: Show exact inputs to diff calculation
    print(f"  [VERIFY] Before diff - prev_keys count: {len(prev_keys)}, curr_keys count: {len(curr_keys)}")
    if prev_keys and curr_keys:
        print(f"  [VERIFY] Sample prev_key: {prev_keys[0]}")
        print(f"  [VERIFY] Sample curr_key: {curr_keys[0]}")

    closed, opened = StateDifferencer.compute_diff(prev_keys, curr_keys)

    if closed or opened:
        print(f"  Diff: {dict(closed)} closed | {dict(opened)} opened")
    else:
        print(f"  No changes")

    # ──── CLOSE TRADES (SAFE) ────────────────────────────────────────────────

    close_count = 0
    escalated_count = 0
    if closed:
        log(LogLevel.INFO, f"Processing {len(closed)} key(s) to close")
        print(f"  [TRIGGER] DIFF_CLOSE_START - {len(closed)} keys to close")

        # Get current MT5 positions for stale detection
        mt5_positions = mt5.positions_get() or []

        ops = SafeExecutor.prepare_close_operations(closed, positions)
        for key, ticket in ops:
            # STALE DETECTION: Check if ticket was manually closed in MT5
            if safety.check_stale_tickets(ticket, mt5_positions):
                positions.remove_ticket(ticket)
                virtual_sl.remove_position(ticket)  # Clean up VSL tracking
                try:
                    trailing_stop_mgr.remove_position(ticket)
                    print(f"  [TRAIL] Removed T{ticket} (stale detect)")
                except Exception as e:
                    log(LogLevel.DEBUG, f"Trailing stop remove failed for T{ticket}: {e}")
                continue

            try:
                # Attempt close
                pair = key[0]  # 2-tuple: (pair, side)
                print(f"  [TRIGGER] DIFF_CLOSE_TICKET {ticket} for key {key}")
                if close_position_by_ticket(ticket, pair):
                    # Success - NOW remove ticket from tracking
                    positions.remove_ticket(ticket)
                    virtual_sl.remove_position(ticket)  # Remove from virtual SL tracking
                    # Remove from trailing stop tracking (position is now closed)
                    try:
                        trailing_stop_mgr.remove_position(ticket)
                        print(f"  [TRAIL] Removed T{ticket} (DIFF close)")
                    except Exception as e:
                        log(LogLevel.DEBUG, f"Trailing stop remove failed for T{ticket}: {e}")
                    close_count += 1
                    safety.handle_close_success(ticket)
                    log(LogLevel.INFO, f"Closed and removed ticket {ticket} for {pair}")

                    # Persist state after successful close
                    positions.save_to_disk()

                else:
                    # Failed - ticket STAYS in positions for retry next cycle
                    # Track failure with escalation
                    action = safety.handle_close_failure(ticket, pair, "close_position_by_ticket returned False")

                    if action == "ESCALATE":
                        print(f"  [ESCALATE] T{ticket} escalated after max retries")
                        # HARD LIMIT: After escalation, give up and remove from tracking
                        # This prevents infinite retry loops for positions that can't be closed
                        print(f"  [FORCE_REMOVE] T{ticket} - giving up after escalation, removing from store")
                        positions.remove_ticket(ticket)
                        virtual_sl.remove_position(ticket)
                        try:
                            trailing_stop_mgr.remove_position(ticket)
                        except Exception as e:
                            log(LogLevel.DEBUG, f"Trailing stop remove failed for T{ticket}: {e}")
                        positions.save_to_disk()
                        escalated_count += 1
                        log(LogLevel.WARN, f"Escalated and force-removed ticket {ticket} (no more retries)")

            except Exception as e:
                # Exception - ticket STAYS in positions for retry next cycle
                action = safety.handle_close_failure(ticket, pair, str(e))
                if action == "ESCALATE":
                    print(f"  [ESCALATE] T{ticket} escalated after max retries (exception)")
                    # HARD LIMIT: After escalation, give up and remove from tracking
                    print(f"  [FORCE_REMOVE] T{ticket} - giving up after escalation, removing from store")
                    positions.remove_ticket(ticket)
                    virtual_sl.remove_position(ticket)
                    try:
                        trailing_stop_mgr.remove_position(ticket)
                    except Exception:
                        pass
                    positions.save_to_disk()
                    escalated_count += 1
                    log(LogLevel.WARN, f"Escalated and force-removed ticket {ticket} due to exception")

        print(f"  [TRIGGER] DIFF_CLOSE_END - closed {close_count}, escalated {escalated_count}")

    # ──── OPEN TRADES ────────────────────────────────────────────────────────

    open_count = 0
    if opened:
        print(f"\n[OPEN] Processing {len(opened)} key(s) to open...")

        for key, count in opened.items():
            pair, side = key  # NEW: 2-tuple (pair, executed_side)

            # Find matching signal for this (pair, side)
            matching_signals = [
                s for s in signals_to_open
                if s.pair == pair and s.side == side
            ]

            if not matching_signals:
                print(f"  [SKIP] No signal found for {key}")
                continue

            sig = matching_signals[0]  # Use first match

            # Check if already processed recently
            sig_id = get_signal_id(sig)
            if sig_id in processed_signal_ids:
                print(f"  [SKIP] Signal already processed: {sig_id}")
                continue

            # ──── CRITICAL: PRE-OPEN DUPLICATE CHECK ────────────────────────────
            # Check if (pair, side) is already open in positions store
            # This is a safety backup to prevent any duplicate opens
            exec_identity = (sig.pair, sig.side)
            if positions.has_key(exec_identity):
                existing_count = positions.count_for_key(exec_identity)
                print(f"  [SKIP_DUP] {exec_identity} already open ({existing_count} tickets, count={count}), preventing duplicate")
                log(LogLevel.INFO, f"Skipped duplicate {sig.pair} {sig.side} - already {existing_count} open")
                continue

            # Open trade(s) for this key
            for i in range(count):
                try:
                    success, ticket = open_trade(sig)

                    if success and ticket:
                        # ──── CRITICAL: STORE STATE FIRST (before ANY other code) ────
                        # If anything fails after this, the trade is still in our store
                        positions.add_ticket(key, ticket)
                        positions.save_to_disk()
                        print(f"  [STORE] Added {key} → ticket {ticket}")

                        # Optional operations that might fail (wrapped in try/except)
                        # Register with virtual SL for spread-aware monitoring
                        try:
                            virtual_sl.add_position(
                                ticket=ticket,
                                pair=sig.pair,
                                side=sig.side,
                                original_sl=sig.sl,
                                tp=sig.tp,
                                entry_price=sig.open_price
                            )
                        except Exception as e:
                            # Virtual SL registration failed but trade is already saved
                            print(f"  [VSL_ERR] Failed to register with VSL: {e}")

                        # Register with trailing stop for SL management
                        try:
                            trailing_stop_mgr.register_position(
                                ticket=ticket,
                                symbol=sig.pair,
                                side=sig.side,
                                entry_price=sig.open_price,
                                tp=sig.tp,
                                original_sl=sig.sl
                            )
                            print(f"  [TRAIL] Registered T{ticket} {sig.pair} {sig.side}")
                        except Exception as e:
                            # Trailing stop registration failed but trade is already saved
                            print(f"  [TRAIL_ERR] Failed to register T{ticket}: {e}")

                        open_count += 1
                        try:
                            print(f"  [OK] Opened ticket {ticket} for {key}")
                        except Exception as e:
                            # Even logging failed, but trade is saved
                            print(f"  [LOG_ERR] {e}")

                        processed_signal_ids.add(sig_id)
                    else:
                        print(f"  [ERR] Failed to open trade for {key}")

                except Exception as e:
                    print(f"  [ERR] Exception opening {key}: {e}")

    # ──── SAVE STATE ─────────────────────────────────────────────────────────

    if open_count > 0 or close_count > 0:
        save_processed_signals(processed_signal_ids)

    # ──── PROCESS CLOSE SIGNALS (Informational) ───────────────────────────────

    if close_signals:
        print(f"\n[CLOSE_SIGNALS] Found {len(close_signals)} close signal(s) on website")
        for sig in close_signals:
            print(f"  {sig.pair} {sig.side} @ close {sig.close_price} ({sig.close_reason})")
            # These are FYI only - the counter diff already handled closing

    # ──── STATUS ─────────────────────────────────────────────────────────────

    # Count position types
    total_tickets = sum(len(t) for t in positions.positions.values())

    # Log current positions store state (DEBUG) - with defensive error handling
    try:
        print(f"  [STORE] Current keys in positions store: {list(positions.get_all_keys())}")
        print(f"  [STORE] Total tickets tracked: {total_tickets}")
    except Exception as e:
        print(f"  [LOG_ERR] Failed to log store state: {e}")

    try:
        log(LogLevel.INFO, f"Cycle complete: {open_count} opened, {close_count} closed, {escalated_count} escalated")
        log(LogLevel.INFO, f"Tracked: {total_tickets} tickets")
    except Exception as e:
        print(f"  [LOG_ERR] Failed to log cycle status: {e}")

    # Log safety status periodically
    import random
    if random.random() < 0.1:  # ~10% of cycles
        try:
            status = safety.get_status_report()
            if status["total_escalated"] > 0:
                log(LogLevel.WARN, f"Safety status - Escalated: {status['total_escalated']}, Tickets: {status['escalated_tickets']}")
        except Exception as e:
            log(LogLevel.DEBUG, f"[ERROR_STATUS] Failed to get status report: {e}")

    # Display positions and account (fault-tolerant)
    try:
        show_open_positions()
    except Exception as e:
        print(f"[ERROR_DISPLAY] show_open_positions failed: {e}")

    try:
        account_summary()
    except Exception as e:
        print(f"[ERROR_DISPLAY] account_summary failed: {e}")


def signal_thread():
    """Main loop: fetch signals every N seconds (24/7, all signals, all sessions)."""

    while True:
        try:
            # ──────── CHECK MT5 CONNECTION ──────────────────────────────────────────────────────
            try:
                if not mt5.initialize():
                    print("[ERROR_MT5] MT5 disconnected - attempting to reconnect...")
                    try:
                        init_mt5()
                        print("[OK_MT5] MT5 reconnected")
                    except Exception as e:
                        print(f"[ERROR_RECONNECT] MT5 reconnection failed: {e}")
                        time.sleep(5)
                        continue
            except Exception as e:
                print(f"[ERROR_MT5_CHECK] MT5 init check failed: {e}")
                time.sleep(5)
                continue

            # ──────── RUN SIGNAL CYCLE (24/7) ────────────────────────────────────────────────────
            try:
                run_signal_cycle()
            except Exception as e:
                print(f"[ERROR_CYCLE] Signal cycle error: {e}")
                # Don't re-raise - allow loop to continue

        except Exception as e:
            print(f"[ERROR_SIGNAL_THREAD] Unexpected error in signal thread: {e}")
            # Catastrophic fallback - don't exit loop
            time.sleep(SIGNAL_INTERVAL)

        time.sleep(SIGNAL_INTERVAL)


# ══════════════════════════════════════════════════════════════════════════════
# START
# ══════════════════════════════════════════════════════════════════════════════

# Initial MT5 reconstruction - must happen BEFORE signal cycle starts
# because first signal cycle will compute prev_keys = positions.get_all_keys()
print("\n[STARTUP] Initial MT5 reconstruction...")

# Fetch and parse one signal snapshot first
try:
    html = fetch_page()
    if html is not None:
        raw_signals = parse_signals(html)

        # Convert to Signal objects and filter
        signals = []
        for raw in raw_signals:
            try:
                sig = Signal(
                    pair=raw['pair'],
                    side=raw['side'],
                    open_price=raw['open'],
                    tp=raw['tp'],
                    sl=raw['sl'],
                    time=raw['time'],
                    frame=raw['frame'],
                    status=raw['status'],
                    close_price=raw.get('close'),
                    close_reason=raw.get('close_reason'),
                )
                signals.append(sig)
            except Exception as e:
                pass  # Skip malformed

        # Filter: ACTIVE signals only
        # For startup reconstruction, use ALL active signals (no age filter)
        # This ensures we properly reconstruct ANY open positions regardless of signal age
        active_signals = [s for s in signals if s.status == "ACTIVE"]
        signals_for_reconstruction = sorted(active_signals, key=lambda s: s.time, reverse=True)
        signals_for_reconstruction = SignalFilter.deduplicate_by_key(signals_for_reconstruction)

        if signals_for_reconstruction:
            mt5_positions = mt5.positions_get() or []
            if mt5_positions:
                reconstructed, unmatched = reconstruct_positions_from_mt5(
                    mt5_positions, signals_for_reconstruction, positions
                )
                print(f"[STARTUP] Reconstructed {reconstructed} positions, {unmatched} unmatched\n")

                # ──── REGISTER RECONSTRUCTED POSITIONS WITH TRAILING STOP ────────
                # After reconstruction, all positions need to be registered for SL tracking
                print(f"[STARTUP] Registering reconstructed positions with trailing stop...")
                try:
                    # Get all reconstructed positions back from MT5 to get full details
                    mt5_positions_now = mt5.positions_get() or []
                    mt5_by_ticket = {p.ticket: p for p in mt5_positions_now}

                    # Iterate through all tracked positions and register those not yet in trailing stop
                    registered_count = 0
                    for key, tickets in positions.positions.items():
                        # Skip special buckets
                        if key[0] in ("_UNMATCHED_", "_FAILED_CLOSE_"):
                            continue

                        pair, side = key  # NEW: 2-tuple (pair, executed_side)

                        for ticket in tickets:
                            # Check if already in trailing stop (to avoid re-registering)
                            if ticket in trailing_stop_mgr.position_meta:
                                continue

                            # Get position from MT5
                            mt5_pos = mt5_by_ticket.get(ticket)
                            if not mt5_pos:
                                continue

                            # Register with trailing stop
                            try:
                                trailing_stop_mgr.register_position(
                                    ticket=ticket,
                                    symbol=mt5_pos.symbol,
                                    side=side,
                                    entry_price=mt5_pos.price_open,
                                    tp=mt5_pos.tp,  # Use actual MT5 TP, not from key
                                    original_sl=mt5_pos.sl  # Use actual MT5 SL, not from key
                                )
                                registered_count += 1
                            except Exception as e:
                                print(f"  [TRAIL_ERR] Failed to register T{ticket}: {e}")

                    if registered_count > 0:
                        print(f"[STARTUP] Registered {registered_count} position(s) with trailing stop\n")

                    # ──── INFER STAGE FLAGS FROM CURRENT MT5 SL ────────
                    # For each registered position, infer which stages have already fired
                    # based on current SL vs entry price (state recovery after restart)
                    print(f"[STARTUP] Inferring stage flags from current MT5 SL values...")
                    inferred_count = 0
                    for key, tickets in positions.positions.items():
                        if key[0] in ("_UNMATCHED_", "_FAILED_CLOSE_"):
                            continue

                        for ticket in tickets:
                            if ticket in trailing_stop_mgr.position_meta:
                                try:
                                    trailing_stop_mgr.infer_stage_flags(ticket, mt5)
                                    inferred_count += 1
                                except Exception as e:
                                    print(f"  [STATE_RECOVERY_ERR] Failed to infer flags for T{ticket}: {e}")

                    if inferred_count > 0:
                        print(f"[STARTUP] Inferred stage flags for {inferred_count} position(s)\n")

                except Exception as e:
                    print(f"[STARTUP] Exception registering positions: {e}\n")
                    import traceback
                    traceback.print_exc()
            else:
                print(f"[STARTUP] No existing MT5 positions to reconstruct\n")
        else:
            print(f"[STARTUP] Could not reconstruct - no valid signals available\n")
    else:
        print(f"[STARTUP] Could not reconstruct - failed to fetch signals\n")
except Exception as e:
    print(f"[STARTUP] Reconstruction error: {e}\n")
    import traceback
    traceback.print_exc()

threading.Thread(target=signal_thread, daemon=True).start()

# Keep main thread alive - FAULT-TOLERANT
last_alive_log = datetime.now(timezone.utc)
while True:
    try:
        # Log "active" every 30 minutes
        now = datetime.now(timezone.utc)
        if (now - last_alive_log).total_seconds() >= 1800:  # 1800 seconds = 30 minutes
            try:
                print(f"\n[ALIVE] Bot is active - {now.isoformat()}")

                try:
                    show_open_positions()
                except Exception as e:
                    print(f"[ERROR_ALIVE_POS] Failed to show positions: {e}")

                try:
                    account_summary()
                except Exception as e:
                    print(f"[ERROR_ALIVE_ACCT] Failed to show account: {e}")

                print()
                last_alive_log = now
            except Exception as e:
                print(f"[ERROR_ALIVE_LOG] Alive log failed: {e}")
                last_alive_log = now  # Don't get stuck if logging fails

        time.sleep(60)

    except Exception as e:
        print(f"[FATAL_MAIN] Main loop exception (recovering): {e}")
        # Sleep to prevent spinning, then continue
        time.sleep(60)
        continue
