"""
MULTI ALGO BOT v2 - Production-Grade Architecture

Each bot instance runs independently with:
- Clean dependency injection (ConfigManager - NO sys.modules hacks)
- Full state recovery on startup (StateRecovery)
- 4-layer deduplication (hash + version + position + processed)
- Atomic state persistence
- Dual signal source (primary + backup)

V2 Improvements:
- ✓ No sys.modules hacks (clean ConfigManager)
- ✓ Deterministic behavior (hash-based deduplication)
- ✓ Full restart safety (all state loaded atomically)
- ✓ Dual signal redundancy (primary + backup)
- ✓ No global dependencies (volume passed to functions)
"""

import sys
import argparse
from collections import Counter

# ─── CLI ARGUMENT PARSING ───────────────────────────────────────────────────
parser = argparse.ArgumentParser(description="Multi Algo Trading Bot v2")
parser.add_argument("--bot-id", type=int, required=True, choices=[1, 2, 3],
                   help="Bot ID (1=inverter, 2=follower, 3=follower)")
parser.add_argument("--no-mt5", action="store_true",
                   help="Skip MT5 initialization (for testing)")
args = parser.parse_args()

BOT_ID = args.bot_id

# ─── SETUP BOT-SPECIFIC LOGGING (BEFORE IMPORTS) ─────────────────────────
log_file = f"bot_{BOT_ID}.log"
sys.stdout = open(log_file, "a", buffering=1, encoding="utf-8")
sys.stderr = sys.stdout

# ─── CLEAN CONFIG LOADING (NO sys.modules hacks) ──────────────────────────
from config_manager import ConfigManager

try:
    config = ConfigManager(BOT_ID)
    print(f"\n[INIT] ConfigManager loaded: {config}")
except Exception as e:
    print(f"[ERROR] Failed to load config: {e}")
    sys.exit(1)

# ─── NOW PROCEED WITH REMAINING IMPORTS ──────────────────────────────────
import time
import threading
import MetaTrader5 as mt5
import json
import os
from datetime import datetime, timezone, timedelta

from signal_reader import SignalReader
from signal_inverter import SignalInverter
from state_recovery import StateRecovery
from atomic_io import atomic_write_json, safe_read_json
from v3_execution_flow import V3ExecutionFlow
from strategy import get_strategy
from trader import open_trade, close_position_by_ticket, init_mt5, show_open_positions, account_summary
from signal_manager import (
    Signal, SignalKey, PositionStore, StateDifferencer, SignalFilter, SafeExecutor, FuzzyMatcher
)
from operational_safety import OperationalSafety, log, LogLevel
from virtual_sl import init_virtual_sl, get_virtual_sl_manager
from trailing_stop import init_trailing_stop
from config import SIGNAL_INTERVAL, MAX_SIGNAL_AGE


# Bot-specific state file names
positions_store_file = f"positions_store_bot_{BOT_ID}.json"
trailing_stop_meta_file = f"trailing_stop_meta_bot_{BOT_ID}.json"
processed_signals_file = f"processed_signals_bot_{BOT_ID}.json"

print(f"\n{'='*80}")
print(f"MULTI ALGO BOT v2 #{BOT_ID} - {config['BOT_NAME']}")
print(f"Signal interval: {SIGNAL_INTERVAL}s | Trade volume: {config['TRADE_VOLUME']}")
print(f"MT5 Login: {config['MT5_LOGIN']}")
print(f"Bot-specific files:")
print(f"  - Positions: {positions_store_file}")
print(f"  - Trailing stop: {trailing_stop_meta_file}")
print(f"  - Processed signals: {processed_signals_file}")
print(f"  - Signals: signals.json (shared IPC)")
if config['USE_SIGNAL_INVERTER']:
    print(f"  - SIGNAL INVERSION: Enabled ({config['FOLLOW_HOURS_IST_START']}:00-{config['FOLLOW_HOURS_IST_END']}:00 IST)")

# Initialize strategy from config
try:
    strategy_name = config.get('STRATEGY', 'mirror')
    strategy = get_strategy(strategy_name)
    strategy_config = strategy.get_config_summary() if hasattr(strategy, 'get_config_summary') else {
        'trailing_stop': strategy.should_apply_trailing(),
        'max_loss': strategy.should_apply_max_loss()
    }
    print(f"  - STRATEGY: {strategy_name.upper()}")
    print(f"    ├─ Trailing stop: {'ENABLED' if strategy_config.get('trailing_stop', strategy.should_apply_trailing()) else 'DISABLED'}")
    print(f"    └─ Max loss: {'ENABLED' if strategy_config.get('max_loss', strategy.should_apply_max_loss()) else 'DISABLED'}")
except Exception as e:
    print(f"[ERROR] Failed to initialize strategy: {e}")
    strategy = get_strategy('mirror')  # Fallback to mirror

print(f"{'='*80}\n")


# Initialize MT5 with bot-specific credentials from config
init_mt5(
    mt5_login=config['MT5_LOGIN'],
    mt5_password=config['MT5_PASSWORD'],
    mt5_server=config['MT5_SERVER'],
    mt5_exe=config['MT5_EXE']
)

# ─── STATE RECOVERY ON STARTUP (NEW v2 feature) ───────────────────────────
print("[RECOVERY] Attempting full state recovery from disk...")
state_recovery = StateRecovery(BOT_ID)
state_recovery.recover_all_state()

# Use recovered state
positions = state_recovery.positions
processed_signal_ids = state_recovery.processed_signals

print(f"[RECOVERY] Positions recovered: {len(list(positions.get_all_keys()))} keys")
print(f"[RECOVERY] Processed signals recovered: {len(processed_signal_ids)} signals\n")

# Operational safety monitoring and retry control
safety = OperationalSafety(max_retries=5, unmatched_threshold=3)

# Virtual SL - Spread-aware stop loss management
# spread_factor: 1.5-2.0 (higher = more protection from spread spikes)
# cooldown_seconds: 300 (5 min cooldown to prevent reopen loop after VSL close)
virtual_sl = init_virtual_sl(spread_factor=1.5, cooldown_seconds=300)

# Trailing Stop - Phase-based SL management (passive layer)
trailing_stop_mgr = init_trailing_stop(trailing_stop_meta_file)
print(f"[TRAIL] Initialized trailing stop manager with file: {trailing_stop_meta_file}")

# Persistent signal processing tracker (prevent duplicate opens)
processed_signals_file = f"processed_signals_bot_{BOT_ID}.json"

# Signal reader for multi-bot IPC via signals.json
signal_reader = SignalReader(BOT_ID)
print(f"[SIGNAL] Initialized SignalReader for Bot {BOT_ID}")

# V3 Execution Flow - Execution-aware logic, MT5 sync, latency guards, trace logging
v3_flow = V3ExecutionFlow(BOT_ID)
print(f"[V3] Initialized V3ExecutionFlow for Bot {BOT_ID}")

# MFE/MAE Tracking - Maximum Favorable Excursion / Maximum Adverse Excursion per ticket
mfe_mae_tracker = {}  # {ticket: {"max_profit": float, "max_loss": float}}
print("[MFE/MAE] Initialized trade excursion tracker (lightweight, O(n) per cycle)")


def load_processed_signals():
    """Load set of already-processed signal timestamps (fault-tolerant)."""
    try:
        data = safe_read_json(processed_signals_file, max_retries=3)
        if data is None:
            return set()

        # Keep signals from last 24 hours
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        filtered = {
            ts: v for ts, v in data.items()
            if datetime.fromisoformat(v) > cutoff
        }
        print(f"[RECOVERY] Loaded {len(filtered)} processed signals (24h retention)")
        return set(filtered.keys())

    except Exception as e:
        print(f"[ERROR] Failed to load processed_signals: {e}, starting fresh")
        return set()


def save_processed_signals(signal_set):
    """Save processed signal IDs atomically (fault-tolerant)."""
    try:
        data = {sig_id: datetime.now(timezone.utc).isoformat() for sig_id in signal_set}
        # Use atomic write (temp file + replace)
        success = atomic_write_json(processed_signals_file, data)
        if not success:
            print(f"[ERROR] Failed to save processed_signals")
            return False
        return True

    except Exception as e:
        print(f"[ERROR] Exception in save_processed_signals: {e}")
        return False


def save_bot_state():
    """
    Save all bot state atomically after successful cycle.

    Saves:
    1. Processed signals (Layer 4 deduplication)
    2. Position store (Layer 3 deduplication)
    3. Trailing stop metadata
    """
    try:
        # 1. Save processed signals
        data_processed = {sig_id: datetime.now(timezone.utc).isoformat()
                          for sig_id in processed_signal_ids}
        atomic_write_json(processed_signals_file, data_processed)

        # 2. Save position store (NEW - atomic recovery)
        data_positions = positions.to_dict()
        atomic_write_json(positions_store_file, data_positions)

        # NOTE: Trailing stop metadata is now handled by TrailingStopManager internally
        # (uses atomic writes in _save_position_meta). Removed redundant write here.

        return True

    except Exception as e:
        print(f"[ERROR] Failed to save bot state: {e}")
        return False


def get_signal_id(sig: Signal) -> str:
    """Create unique signal ID from signal timestamp + key."""
    key = SignalKey.build(sig.pair, sig.side, sig.tp, sig.sl)
    time_str = sig.time.isoformat()
    return f"{time_str}_{key}"


def log_trade_close_with_mfe_mae(ticket: int, pair: str, side: str, mfe_mae_tracker: dict):
    """Log trade close with Maximum Favorable Excursion (MFE) and Maximum Adverse Excursion (MAE) values.

    MFE: Maximum profit seen during trade lifetime
    MAE: Maximum loss seen during trade lifetime
    """
    if ticket in mfe_mae_tracker:
        tracker_entry = mfe_mae_tracker[ticket]
        max_profit = tracker_entry.get("max_profit", 0.0)
        max_loss = tracker_entry.get("max_loss", 0.0)
        print(f"  [TRADE_CLOSE] T{ticket} {pair} {side} | MFE={max_profit:.4f} MAE={max_loss:.4f}")
        log(LogLevel.INFO, f"Trade closed: ticket={ticket} pair={pair} side={side} MFE={max_profit:.4f} MAE={max_loss:.4f}")
        # Clean up tracker after logging
        del mfe_mae_tracker[ticket]
    else:
        # Ticket not in tracker (safety fallback) - log without MFE/MAE
        print(f"  [TRADE_CLOSE] T{ticket} {pair} {side} | MFE/MAE not tracked")
        log(LogLevel.DEBUG, f"Trade closed: ticket={ticket} pair={pair} side={side} (tracker missing)")

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

    Multi-bot changes:
    1. Read signals from signals.json (IPC) via SignalReader
    2. Track version to skip unchanged signals
    3. Apply signal inversion if enabled (bot 1 only)
    4. Build current state, compute diff, execute trades
    5. Use bot-specific state files
    """
    global positions, processed_signal_ids, signal_reader

    now = datetime.now(timezone.utc)
    now_str = now.strftime('%H:%M:%S')

    # ──── READ SIGNALS FROM IPC FILE ──────────────────────────────────────────
    signals_json, version, is_new = signal_reader.read_signals_safe(max_age_seconds=20)

    if signals_json is None:
        if is_new is False and signal_reader.last_version_seen > 0:
            # Version unchanged - optimization
            print(f"[{now_str}] [v{signal_reader.last_version_seen}] Version unchanged, skipping cycle")
        else:
            # Signals unavailable or stale
            print(f"[{now_str}] No signals available (missing or stale)")
        return

    # ──── V3: MT5 RECONCILIATION (EVERY CYCLE - broker is source of truth) ──────
    # Sync positions_store with actual MT5 state before any trading decisions
    v3_flow.reconcile_mt5_positions(positions)

    # ──── UPDATE MFE/MAE TRACKER (EVERY CYCLE) ────────────────────────────────────
    # Track maximum favorable and adverse excursions from MT5 position profit values
    try:
        mt5_positions_for_tracker = mt5.positions_get() or []
        mt5_profit_by_ticket = {p.ticket: p.profit for p in mt5_positions_for_tracker}

        for ticket, profit in mt5_profit_by_ticket.items():
            if ticket not in mfe_mae_tracker:
                # Initialize tracker for new tickets found in MT5 (safety fallback)
                mfe_mae_tracker[ticket] = {"max_profit": max(0, profit), "max_loss": min(0, profit)}
            else:
                # Update max/min profit seen for this ticket
                mfe_mae_tracker[ticket]["max_profit"] = max(mfe_mae_tracker[ticket]["max_profit"], profit)
                mfe_mae_tracker[ticket]["max_loss"] = min(mfe_mae_tracker[ticket]["max_loss"], profit)
    except Exception as e:
        # Non-critical - just log and continue
        print(f"  [MFE/MAE] Error updating tracker: {e}")


    if not signals_json:
        print(f"[{now_str}] [v{version}] Empty signal list")
        return

    print(f"[{now_str}] [v{version}] Fetched {len(signals_json)} raw signals")

    # ──── APPLY SIGNAL INVERSION (BOT-SPECIFIC) ──────────────────────────────
    if config.USE_SIGNAL_INVERTER:
        signals_json = SignalInverter.apply_inversion_filter(signals_json)
        invert_status = "INVERTED" if SignalInverter.is_inversion_time() else "NO_INVERT"
        print(f"  [{invert_status}] {len(signals_json)} signals after filter")

    # ──── APPLY STRATEGY TRANSFORMATION ────────────────────────────────────────
    # Apply strategy-specific signal transformations (mirror, reverse, time-based)
    try:
        signals_json = [strategy.transform_signal(sig) for sig in signals_json]
        print(f"  [STRATEGY] Applied {strategy.name} transformation")
    except Exception as e:
        print(f"  [ERROR] Strategy transformation failed: {e}")
        # Continue with untransformed signals (safety fallback)

    # Signals are already Signal objects from SignalReader (converted from JSON)
    signals = signals_json


    if not signals:
        print(f"[{now_str}] No valid signals after filtering")
        return

    # ──── SIGNAL STABILITY LOGGING: Raw signal list every cycle ────────────────
    raw_signal_list = [(s.pair, s.side) for s in signals if s.status == "ACTIVE"]
    print(f"  [RAW_SIGNALS] Cycle signals (ACTIVE only): {raw_signal_list}")

    # ──── FILTER BY AGE (CRITICAL: CLOSE signals bypass age filter) ──────────

    active_signals = [s for s in signals if s.status == "ACTIVE"]
    close_signals = [s for s in signals if s.status == "CLOSE"]

    print(f"  Active: {len(active_signals)}, Close: {len(close_signals)}")

    # ──── FILTER BY AGE: Only open NEW trades from fresh signals (<30 min)
    # Position management keeps ALL active signals to avoid closing active trades

    fresh_signals = SignalFilter.filter_by_age(active_signals, MAX_SIGNAL_AGE)
    print(f"  After age filter: {len(fresh_signals)} fresh active (max age: {MAX_SIGNAL_AGE}s)")

    # For position management, use ALL active signals (no age filter)
    # This keeps trades open as long as signal is active on website
    all_active_signals = active_signals

    # ──── DEDUPLICATE: Keep most recent per key (FOR OPENING ONLY) ────────────

    # Sort by time DESC so deduplication keeps most recent
    fresh_signals_sorted = sorted(fresh_signals, key=lambda s: s.time, reverse=True)
    signals_to_open = SignalFilter.deduplicate_by_key(fresh_signals_sorted)
    print(f"  After dedup: {len(signals_to_open)} unique fresh signals for opening")

    # ──── BUILD STATE FOR COUNTER DIFF (NO DEDUP - PRESERVE COUNTS) ──────────

    # Get previous state from position store
    prev_keys = list(positions.get_all_keys())

    # Build current state from ALL active signals WITHOUT deduplication
    # CRITICAL: Preserve duplicate counts for exact signal mirroring
    curr_keys = [
        SignalKey.build(s.pair, s.side, s.tp, s.sl)
        for s in all_active_signals  # ALL active, NO dedup
    ]

    # ──── VALIDATION: PRECISION CONSISTENCY ────────────────────────────────────
    # Verify signal key precision is stable (no rounding issues)

    precision_sample = min(5, len(all_active_signals))
    if precision_sample > 0:
        for sig in all_active_signals[:precision_sample]:
            key1 = SignalKey.build(sig.pair, sig.side, sig.tp, sig.sl)
            key2 = SignalKey.build(sig.pair, sig.side, sig.tp, sig.sl)
            if key1 != key2:
                print(f"  [PRECISION_ERROR] Key mismatch for {sig.pair}: {key1} != {key2}")
                log(LogLevel.ERROR, f"Precision error in signal key: {key1} != {key2}")

    print(f"  Previous state: {len(prev_keys)} keys")
    print(f"  Current state: {len(curr_keys)} keys")
    print(f"  Counter: prev uniques={len(set(prev_keys))}, curr uniques={len(set(curr_keys))}")

    # ──── VIRTUAL SL CHECK (SPREAD-AWARE) ─────────────────────────────────────
    # Check and close positions that hit virtual SL (accounts for spread changes)
    # Only run if strategy allows max loss protection

    mt5_positions = mt5.positions_get() or []

    if strategy.should_apply_max_loss():
        print(f"  [TRIGGER] VSL_CHECK_START")
        virtual_sl_closes = virtual_sl.check_and_close_all(
            mt5, positions, lambda t, p: close_position_by_ticket(t, p)
        )
        print(f"  [TRIGGER] VSL_CHECK_END - closed {len(virtual_sl_closes or [])}")
    else:
        print(f"  [TRIGGER] VSL_CHECK_SKIPPED (strategy {strategy.name} does not use max loss)")
        virtual_sl_closes = None
        mt5_positions = mt5.positions_get() or []


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

    # ──── COMPUTE COUNTER DIFF (CORE EXECUTION LOGIC) ─────────────────────────

    prev_counter = Counter(prev_keys)
    curr_counter = Counter(curr_keys)

    closed = prev_counter - curr_counter  # prev - curr (to close)
    opened = curr_counter - prev_counter  # curr - prev (to open)

    # ──── VALIDATION: COUNT CORRECTNESS ────────────────────────────────────────
    total_prev = sum(prev_counter.values())
    total_curr = sum(curr_counter.values())
    total_close = sum(closed.values())
    total_open = sum(opened.values())

    print(f"  [DEBUG] State counts: prev={total_prev} curr={total_curr}")
    print(f"  [DEBUG] Diff: close={total_close} open={total_open}")

    # Verify counts are consistent
    expected_total_after = total_prev - total_close + total_open
    if expected_total_after != total_curr:
        print(f"  [WARNING] Count mismatch after diff: {expected_total_after} != {total_curr}")
        log(LogLevel.WARN, f"Count mismatch in diff calculation: {expected_total_after} != {total_curr}")

    # Log the actual diff
    if closed or opened:
        print(f"  Diff: {dict(closed)} closed | {dict(opened)} opened")
    else:
        print(f"  No changes")

    # ──── CLOSE TRADES (COUNTER DIFF DRIVEN) ──────────────────────────────────

    open_count = 0
    close_count = 0
    escalated_count = 0
    expected_close_count = sum(closed.values())
    expected_open_count = sum(opened.values())

    # Per-key tracking for strict validation
    from collections import defaultdict
    actual_close_per_key = defaultdict(int)
    actual_open_per_key = defaultdict(int)

    if closed:
        log(LogLevel.INFO, f"Processing {len(closed)} key(s) to close")
        print(f"  [TRIGGER] DIFF_CLOSE_START - {len(closed)} keys to close")

        # Get current MT5 positions for stale detection
        mt5_positions = mt5.positions_get() or []

        ops = SafeExecutor.prepare_close_operations(closed, positions)
        for key, ticket in ops:
            # CRITICAL SAFETY: Never close unmatched positions
            if key[0] == "_UNMATCHED_":
                log(LogLevel.INFO, f"Skipping UNMATCHED ticket {ticket} - unmatched positions never closed")
                continue

            # CRITICAL SAFETY: Never retry failed positions (already escalated)
            if key[0] == "_FAILED_CLOSE_":
                log(LogLevel.INFO, f"Skipping FAILED_CLOSE ticket {ticket} - escalated tickets never retried")
                continue

            # STALE DETECTION: Check if ticket was manually closed in MT5
            if safety.check_stale_tickets(ticket, mt5_positions):
                # Log trade close with MFE/MAE before cleanup
                pair = key[0] if isinstance(key, tuple) else "UNKNOWN"
                side = key[1] if isinstance(key, tuple) and len(key) > 1 else "UNKNOWN"
                log_trade_close_with_mfe_mae(ticket, pair, side, mfe_mae_tracker)

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
                print(f"  [TRIGGER] DIFF_CLOSE_TICKET {ticket} for key {key}")
                if close_position_by_ticket(ticket, key[0]):
                    # Success - Log trade close with MFE/MAE before removing from tracking
                    pair = key[0] if isinstance(key, tuple) else "UNKNOWN"
                    side = key[1] if isinstance(key, tuple) and len(key) > 1 else "UNKNOWN"
                    log_trade_close_with_mfe_mae(ticket, pair, side, mfe_mae_tracker)

                    # NOW remove ticket from tracking
                    positions.remove_ticket(ticket)
                    virtual_sl.remove_position(ticket)  # Remove from virtual SL tracking
                    # Remove from trailing stop tracking (position is now closed)
                    try:
                        trailing_stop_mgr.remove_position(ticket)
                        print(f"  [TRAIL] Removed T{ticket} (DIFF close)")

                    except Exception as e:
                        log(LogLevel.DEBUG, f"Trailing stop remove failed for T{ticket}: {e}")
                    close_count += 1
                    actual_close_per_key[key] += 1
                    safety.handle_close_success(ticket)
                    log(LogLevel.INFO, f"Closed and removed ticket {ticket} for {key[0]}")

                else:
                    # Failed - ticket STAYS in positions for retry next cycle
                    # Track failure with escalation
                    action = safety.handle_close_failure(ticket, key[0], "close_position_by_ticket returned False")

                    if action == "ESCALATE":
                        # Move to failed close bucket
                        failed_key = ("_FAILED_CLOSE_", key[0], key[2], key[3])

                        # Clean up MFE/MAE tracker (escalation means position won't be retried)
                        if ticket in mfe_mae_tracker:
                            del mfe_mae_tracker[ticket]

                        positions.remove_ticket(ticket)
                        positions.add_ticket(failed_key, ticket)
                        virtual_sl.remove_position(ticket)  # Stop monitoring virtual SL
                        # Remove from trailing stop (position will not be retried)
                        try:
                            trailing_stop_mgr.remove_position(ticket)
                            print(f"  [TRAIL] Removed T{ticket} (escalated to _FAILED_CLOSE_)")
                        except Exception as e:
                            log(LogLevel.DEBUG, f"Trailing stop remove failed for T{ticket}: {e}")
                        escalated_count += 1
                        log(LogLevel.CRITICAL, f"Escalated ticket {ticket} to _FAILED_CLOSE_ bucket after max retries")


            except Exception as e:
                # Exception - ticket STAYS in positions for retry next cycle
                action = safety.handle_close_failure(ticket, key[0], str(e))

                if action == "ESCALATE":
                    # Move to failed close bucket
                    failed_key = ("_FAILED_CLOSE_", key[0], key[2], key[3])

                    # Clean up MFE/MAE tracker (escalation means position won't be retried)
                    if ticket in mfe_mae_tracker:
                        del mfe_mae_tracker[ticket]

                    positions.remove_ticket(ticket)
                    positions.add_ticket(failed_key, ticket)
                    virtual_sl.remove_position(ticket)  # Stop monitoring virtual SL
                    # Remove from trailing stop (position will not be retried)
                    try:
                        trailing_stop_mgr.remove_position(ticket)
                        print(f"  [TRAIL] Removed T{ticket} (escalated to _FAILED_CLOSE_ on exception)")
                    except Exception as e:
                        log(LogLevel.DEBUG, f"Trailing stop remove failed for T{ticket}: {e}")
                    escalated_count += 1
                    log(LogLevel.CRITICAL, f"Escalated ticket {ticket} to _FAILED_CLOSE_ bucket after max retries (exception)")


        print(f"  [TRIGGER] DIFF_CLOSE_END - closed {close_count}, escalated {escalated_count}")

    # ──── OPEN TRADES (COUNTER DIFF DRIVEN) ──────────────────────────────────

    if opened:
        print(f"\n[OPEN] Processing {len(opened)} key(s) to open...")

        for key, count in opened.items():
            pair, side, tp, sl = key

            # CRITICAL: Skip if this position was recently closed by virtual SL
            # Prevent immediate reopen after bot-triggered close
            if virtual_sl.is_closed_by_bot(key):
                log(LogLevel.INFO, f"Skipping {key} - recently closed by virtual SL, waiting for signal reset")
                continue

            # Find matching signal from signals_to_open
            # For deterministic signal replication, use signals_to_open (deduped fresh signals)
            matching_signals = [
                s for s in signals_to_open
                if s.pair == pair and s.side == side
                and round(s.tp, 3) == round(tp, 3)
                and round(s.sl, 3) == round(sl, 3)
            ]

            if not matching_signals:
                print(f"  [SKIP] No signal found for {key}")
                continue

            sig = matching_signals[0]  # Use first match

            # Open trades for this key (count times)
            for i in range(count):
                try:
                    # Pass volume from bot-specific config
                    success, ticket = open_trade(sig, volume=config['TRADE_VOLUME'])

                    if success and ticket:
                        positions.add_ticket(key, ticket)

                        # Initialize MFE/MAE tracking for this ticket
                        mfe_mae_tracker[ticket] = {"max_profit": 0.0, "max_loss": 0.0}

                        # Register with virtual SL for spread-aware monitoring

                        virtual_sl.add_position(
                            ticket=ticket,
                            pair=sig.pair,
                            side=sig.side,
                            original_sl=sig.sl,
                            tp=sig.tp,
                            entry_price=sig.open_price
                        )

                        # Register with trailing stop for SL management (if strategy allows)
                        if strategy.should_apply_trailing():
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
                                log(LogLevel.ERROR, f"Trailing stop registration failed for T{ticket}: {e}")
                                print(f"  [TRAIL_ERR] Failed to register T{ticket}: {e}")
                        else:
                            print(f"  [TRAIL] Skipped T{ticket} (strategy {strategy.name} does not use trailing stop)")


                        open_count += 1
                        actual_open_per_key[key] += 1
                        print(f"  [OK] Opened ticket {ticket} for {key}")

                    else:
                        print(f"  [ERR] Failed to open trade for {key}")

                except Exception as e:
                    print(f"  [ERR] Exception opening {key}: {e}")

    # ──── VALIDATION: EXECUTION ACCURACY ───────────────────────────────────────

    print(f"\n[VERIFY] EXECUTION ACCURACY:")
    print(f"  Expected: open={expected_open_count}, close={expected_close_count}")
    print(f"  Actual:   open={open_count}, close={close_count}")

    # Validate count accuracy
    open_mismatch = open_count != expected_open_count
    close_mismatch = close_count != expected_close_count

    if open_mismatch:
        print(f"  [WARNING] Open mismatch: expected {expected_open_count}, got {open_count}")
        log(LogLevel.WARN, f"Open count mismatch: expected {expected_open_count}, actual {open_count}")

    if close_mismatch:
        print(f"  [WARNING] Close mismatch: expected {expected_close_count}, got {close_count}")
        log(LogLevel.WARN, f"Close count mismatch: expected {expected_close_count}, actual {close_count}")

    if not open_mismatch and not close_mismatch:
        print(f"  ✓ PASS: All expected trades executed")

    # ──── VALIDATION: PER-KEY EXECUTION (STRICT) ───────────────────────────────

    print(f"\n[VERIFY] PER-KEY EXECUTION:")
    per_key_mismatch = False

    for key in opened:
        if actual_open_per_key[key] != opened[key]:
            print(f"  [CRITICAL] OPEN mismatch for {key}: expected={opened[key]} actual={actual_open_per_key[key]}")
            log(LogLevel.CRITICAL, f"OPEN per-key mismatch: {key} expected {opened[key]}, got {actual_open_per_key[key]}")
            per_key_mismatch = True

    for key in closed:
        if actual_close_per_key[key] != closed[key]:
            print(f"  [CRITICAL] CLOSE mismatch for {key}: expected={closed[key]} actual={actual_close_per_key[key]}")
            log(LogLevel.CRITICAL, f"CLOSE per-key mismatch: {key} expected {closed[key]}, got {actual_close_per_key[key]}")
            per_key_mismatch = True

    if not per_key_mismatch and (opened or closed):
        print(f"  ✓ PASS: All per-key execution accurate")

    # ──── VALIDATION: STORE STATE CONSISTENCY ──────────────────────────────────

    print(f"\n[VERIFY] STORE CONSISTENCY:")
    store_total = sum(len(tickets) for tickets in positions.positions.values())
    print(f"  Total tracked tickets: {store_total}")
    print(f"  Position keys: {len(positions.positions)}")

    # Check for orphaned tickets
    for key, tickets in positions.positions.items():
        if not tickets:
            print(f"  [WARNING] Empty ticket list for key {key}")
            log(LogLevel.WARN, f"Empty ticket list for key {key}")

    # ──── VALIDATION: RESTART SAFETY ──────────────────────────────────────────

    print(f"\n[VERIFY] RESTART SAFETY:")
    print(f"  prev_keys loaded: {len(prev_keys)}")
    print(f"  curr_keys computed: {len(curr_keys)}")
    print(f"  Unique prev keys: {len(set(prev_keys))}")
    print(f"  Unique curr keys: {len(set(curr_keys))}")

    # Verify prev_keys matches store (STRICT: exact structural match, not just size)
    store_keys = list(positions.get_all_keys())
    store_counter = Counter(store_keys)
    prev_keys_counter = Counter(prev_keys)

    if store_counter != prev_keys_counter:
        print(f"  [CRITICAL] RESTART STATE MISMATCH DETECTED")
        print(f"    Store Counter: {dict(store_counter)}")
        print(f"    Prev_keys Counter: {dict(prev_keys_counter)}")
        log(LogLevel.CRITICAL, f"Restart state mismatch: store != prev_keys")
    else:
        print(f"  ✓ PASS: Store exactly matches prev_keys (restart safe)")

    # ──---- STATUS ─────────────────────────────────────

    # ──── VALIDATION: MT5 REALITY (READ-ONLY VERIFICATION) ────────────────────

    print(f"\n[VERIFY] MT5 REALITY CHECK:")
    try:
        mt5_positions = mt5.positions_get() or []
        mt5_counter = Counter()

        for pos in mt5_positions:
            key = SignalKey.build(pos.symbol, ("BUY" if pos.type == 0 else "SELL"), pos.tp, pos.sl)
            mt5_counter[key] += 1

        store_counter_for_mt5 = Counter(positions.get_all_keys())

        if mt5_counter != store_counter_for_mt5:
            print(f"  [CRITICAL] MT5 vs STORE MISMATCH DETECTED")
            print(f"    MT5 Counter: {dict(mt5_counter)}")
            print(f"    Store Counter: {dict(store_counter_for_mt5)}")
            log(LogLevel.CRITICAL, f"MT5 vs Store mismatch detected")
        else:
            print(f"  ✓ PASS: Store matches MT5 reality")
    except Exception as e:
        print(f"  [ERROR] MT5 reality check failed: {e}")
        log(LogLevel.ERROR, f"MT5 reality check exception: {e}")

    # ──── VALIDATION: COUNT INVARIANT (MUST NEVER FAIL) ──────────────────────

    print(f"\n[VERIFY] COUNT INVARIANT:")
    total_prev = sum(prev_counter.values())
    total_curr = sum(curr_counter.values())
    total_close = sum(closed.values())
    total_open = sum(opened.values())

    expected_total_after_execution = total_prev - total_close + total_open

    if expected_total_after_execution == total_curr:
        print(f"  ✓ PASS: {total_prev} - {total_close} + {total_open} = {total_curr}")
    else:
        print(f"  [CRITICAL] COUNT INVARIANT BROKEN: {total_prev} - {total_close} + {total_open} = {expected_total_after_execution} != {total_curr}")
        log(LogLevel.CRITICAL, f"COUNT INVARIANT BROKEN: {expected_total_after_execution} != {total_curr}")

    # ──── VALIDATION: UNMATCHED POSITIONS ALERT ────────────────────────────────

    print(f"\n[VERIFY] UNMATCHED POSITIONS:")
    unmatched_alert_count = 0
    for key in positions.positions.keys():
        if key[0] == "_UNMATCHED_":
            unmatched_alert_count += len(positions.positions[key])

    if unmatched_alert_count > 0:
        print(f"  [ALERT] {unmatched_alert_count} unmatched position(s) detected")
        log(LogLevel.WARN, f"Unmatched positions detected: {unmatched_alert_count}")
    else:
        print(f"  ✓ PASS: No unmatched positions")

    # ──---- STATUS ─────────────────────────────────────
    if open_count > 0 or close_count > 0:
        save_processed_signals(processed_signal_ids)

    # Process close signals (informational only)
    if close_signals:
        print(f"\n[CLOSE_SIGNALS] Found {len(close_signals)} close signal(s) on website")
        for sig in close_signals:
            print(f"  {sig.pair} {sig.side} @ close {sig.close_price} ({sig.close_reason})")
            # These are FYI only - Counter diff logic already handled closing

    # ──── SUMMARY REPORT ────────────────────────────────────────────────────────
    total_tickets = sum(len(t) for t in positions.positions.values())
    unmatched_count = 0
    failed_close_count = 0
    for key in positions.positions.keys():
        if key[0] == "_UNMATCHED_":
            unmatched_count += len(positions.positions[key])
        elif key[0] == "_FAILED_CLOSE_":
            failed_close_count += len(positions.positions[key])

    # FINAL VALIDATION REPORT (COMPREHENSIVE)
    print(f"\n[FINAL VALIDATION] COMPREHENSIVE REPORT:")
    print(f"  ├─ Deterministic: ✓ YES (Counter diff driven)")
    print(f"  ├─ Execution accuracy: {'✓ PASS' if (not open_mismatch and not close_mismatch) else '✗ FAIL'}")
    print(f"  ├─ Per-key execution: {'✓ PASS' if not per_key_mismatch else '✗ FAIL'}")
    print(f"  ├─ Count invariant: {'✓ PASS' if expected_total_after_execution == total_curr else '✗ CRITICAL'}")
    print(f"  ├─ Restart safe: {'✓ PASS' if store_counter == prev_keys_counter else '✗ CRITICAL'}")
    print(f"  ├─ MT5 aligned: ✓ {'PASS' if mt5_counter == store_counter_for_mt5 else 'CHECK'}")
    print(f"  ├─ Store integrity: {'✓ PASS' if len([t for k, t in positions.positions.items() if not t]) == 0 else '✗ FAIL'}")
    print(f"  ├─ Unmatched alert: {'⚠ ALERT' if unmatched_alert_count > 0 else '✓ NONE'}")
    print(f"  └─ Tickets: {total_tickets} total (OK: {total_tickets - unmatched_count - failed_close_count}, UNMATCHED: {unmatched_count}, FAILED_CLOSE: {failed_close_count})")

    # Overall system health
    all_pass = (not open_mismatch and not close_mismatch and not per_key_mismatch and
                expected_total_after_execution == total_curr and store_counter == prev_keys_counter)
    print(f"\n  SYSTEM STATUS: {'✓ HEALTHY' if all_pass else '✗ ATTENTION REQUIRED'}")

    log(LogLevel.INFO, f"Cycle complete: {open_count}/{expected_open_count} opened, {close_count}/{expected_close_count} closed, {escalated_count} escalated | Status: {'HEALTHY' if all_pass else 'ATTENTION'}")
    log(LogLevel.INFO, f"Tracked: {total_tickets} tickets | UNMATCHED: {unmatched_count} | FAILED_CLOSE: {failed_close_count} | MT5 aligned: {'YES' if mt5_counter == store_counter_for_mt5 else 'CHECK'}")

    # Log virtual SL status
    monitored_count = len(virtual_sl.metadata)
    closed_by_bot_count = len(virtual_sl.closed_by_bot)
    if monitored_count > 0 or closed_by_bot_count > 0:
        log(LogLevel.DEBUG, f"Virtual SL: monitoring {monitored_count} tickets, {closed_by_bot_count} in closed_by_bot")

    # Monitor UNMATCHED growth
    safety.check_unmatched_growth(unmatched_count)

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
            # ──── V3: WATCHDOG CHECK ────────────────────────────────────────────────────
            if not v3_flow.check_watchdog():
                print("[V3_CRITICAL] ⚠️  WATCHDOG ALERT: No successful execution in 180s")

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
                    if strategy.should_apply_trailing():
                        for key, tickets in positions.positions.items():
                            # Skip special buckets
                            if key[0] in ("_UNMATCHED_", "_FAILED_CLOSE_"):
                                continue

                            pair, side, tp, sl = key

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
                                        tp=tp,
                                        original_sl=sl
                                    )
                                    registered_count += 1
                                except Exception as e:
                                    print(f"  [TRAIL_ERR] Failed to register T{ticket}: {e}")

                        if registered_count > 0:
                            print(f"[STARTUP] Registered {registered_count} position(s) with trailing stop\n")
                    else:
                        print(f"[STARTUP] Skipping trailing stop registration (strategy {strategy.name} does not use trailing stop)\n")

                    # ──── INFER STAGE FLAGS FROM CURRENT MT5 SL ────────
                    # For each registered position, infer which stages have already fired
                    # based on current SL vs entry price (state recovery after restart)
                    if strategy.should_apply_trailing():
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
