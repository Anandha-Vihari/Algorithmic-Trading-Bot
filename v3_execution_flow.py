"""
V3 ENHANCEMENTS - Integration helpers for execution-aware logic

Minimal add-ons to existing main.py to enable:
- Execution-aware hashing
- MT5 reconciliation every cycle
- Latency guards
- Trace logging
- ExecutionState persistence
- Watchdog monitoring

This module is self-contained and integrates cleanly with v2 architecture.
"""

import time
import MetaTrader5 as mt5
from datetime import datetime, timezone
from typing import Optional, Tuple, Dict
from mt5_sync import sync_positions_with_mt5, validate_position_on_broker
from execution_state import ExecutionState
from tracer import ExecutionTracer
from signal_deduplicator import SignalDeduplicator


class V3ExecutionFlow:
    """Encapsulates v3 execution logic for seamless integration with main.py."""

    def __init__(self, bot_id: int):
        """Initialize v3 execution flow."""
        self.bot_id = bot_id
        self.execution_state = ExecutionState(bot_id)
        self.tracer = ExecutionTracer(bot_id)
        self.last_successful_cycle = time.time()
        self.watchdog_threshold_seconds = 180  # 3 minutes

    # ──────────────────────────────────────────────────────────────────────────
    # STEP 1: MT5 RECONCILIATION (called at start of each cycle)
    # ──────────────────────────────────────────────────────────────────────────

    def reconcile_mt5_positions(self, positions_store) -> Dict:
        """
        Sync positions_store with actual MT5 state.

        Called EVERY cycle BEFORE any trading decisions.

        Args:
            positions_store: PositionStore object

        Returns:
            dict with reconciliation summary
        """
        try:
            stats = sync_positions_with_mt5(positions_store)
            self.tracer.trace_mt5_sync(
                synced=True,
                removed=stats.get('removed', 0),
                added=stats.get('added', 0),
                live_count=stats.get('live_count', 0)
            )
            return stats
        except Exception as e:
            print(f"[V3_ERROR] MT5 reconciliation failed: {e}")
            self.tracer.trace_mt5_sync(synced=False, removed=0, added=0, live_count=-1)
            return {"removed": 0, "added": 0, "live_count": -1, "error": str(e)}

    # ──────────────────────────────────────────────────────────────────────────
    # STEP 2: EXECUTION-AWARE HASH (include prices + time context)
    # ──────────────────────────────────────────────────────────────────────────

    def compute_execution_hash(self, signals: list) -> str:
        """
        Compute execution-aware hash (v3 enhancement).

        Includes: signal content + current bid/ask prices + time bucket
        Same signal different prices → different hash → can execute

        Args:
            signals: List of signal dictionaries

        Returns:
            Execution-aware hash hex string (64 chars)
        """
        try:
            # Get current prices from MT5
            prices = self._get_current_prices(signals)
            exec_hash = SignalDeduplicator.compute_execution_hash(signals, prices)

            # Log
            time_bucket = int(time.time() // 60)
            avg_price = sum(prices.values()) / len(prices) if prices else 0
            self.tracer.trace_execution_hash(exec_hash, avg_price, time_bucket)

            return exec_hash

        except Exception as e:
            print(f"[V3_ERROR] Failed to compute execution hash: {e}")
            # Fallback to content-only hash (v2 compatible)
            return SignalDeduplicator.compute_hash(signals)

    @staticmethod
    def _get_current_prices(signals: list) -> dict:
        """Get current prices for all signal symbols."""
        prices = {}

        # Extract unique symbols
        symbols = set()
        for sig in signals:
            if isinstance(sig, dict) and 'pair' in sig:
                symbols.add(sig['pair'])
            elif hasattr(sig, 'pair'):
                symbols.add(sig.pair)

        # Query MT5 for bid/ask
        for symbol in symbols:
            try:
                tick = mt5.symbol_info_tick(symbol)
                if tick:
                    # Use midpoint (bid + ask) / 2
                    price = (tick.bid + tick.ask) / 2.0
                    prices[symbol] = price
            except Exception:
                pass  # Skip on error

        return prices

    # ──────────────────────────────────────────────────────────────────────────
    # STEP 3: LATENCY GUARD (price drift protection)
    # ──────────────────────────────────────────────────────────────────────────

    def validate_price_drift(self, symbol: str, signal_price: float,
                            max_slippage: float = 0.0005) -> Tuple[bool, float]:
        """
        Check if price has drifted too far since signal creation.

        Max slippage example: 0.0005 = 5 pips for 5-digit pairs

        Args:
            symbol: Trading pair (e.g., "EURUSD")
            signal_price: Price from signal
            max_slippage: Maximum acceptable drift (in price units)

        Returns:
            (passed: bool, drift_pips: float)
        """
        try:
            tick = mt5.symbol_info_tick(symbol)
            if not tick:
                return True, 0.0  # Assume OK if can't get price

            current_price = (tick.bid + tick.ask) / 2.0
            drift = abs(current_price - signal_price)

            # Get point size for pip calculation
            info = mt5.symbol_info(symbol)
            point = info.point if info else 0.00001
            drift_pips = drift / point

            passed = drift <= max_slippage

            self.tracer.trace_price_drift(
                symbol=symbol,
                signal_price=signal_price,
                current_price=current_price,
                drift_pips=drift_pips,
                max_slippage=max_slippage,
                passed=passed
            )

            return passed, drift_pips

        except Exception as e:
            print(f"[V3_ERROR] Price drift check failed for {symbol}: {e}")
            return True, 0.0  # Assume OK on error

    # ──────────────────────────────────────────────────────────────────────────
    # STEP 4: PRE-EXECUTION VALIDATION (3-point check)
    # ──────────────────────────────────────────────────────────────────────────

    def pre_execution_validation(self, symbol: str, side: str,
                                exec_hash: str, positions_store) -> Dict:
        """
        3-point pre-execution validation before opening trade.

        Checks:
        1. Hash uniqueness (execution-aware, not duplicate)
        2. Position not in MT5
        3. Position not in store

        Args:
            symbol: Trading pair
            side: "BUY" or "SELL"
            exec_hash: Execution-aware hash
            positions_store: PositionStore object

        Returns:
            dict with validation results:
            {
                "hash_unique": bool,
                "not_in_mt5": bool,
                "not_in_store": bool,
                "all_pass": bool
            }
        """
        # Check 1: Hash uniqueness
        hash_unique = exec_hash != self.execution_state.last_execution_hash

        # Check 2: Not in MT5 (source of truth)
        not_in_mt5 = not validate_position_on_broker(symbol, side)

        # Check 3: Not in store
        not_in_store = (symbol, side) not in positions_store.get_all_keys()

        checks = {
            "hash_unique": hash_unique,
            "not_in_mt5": not_in_mt5,
            "not_in_store": not_in_store,
            "all_pass": all([hash_unique, not_in_mt5, not_in_store])
        }

        self.tracer.trace_pre_execution_validation(checks)

        return checks

    # ──────────────────────────────────────────────────────────────────────────
    # STEP 5: EXECUTION DECISION (log decision logic)
    # ──────────────────────────────────────────────────────────────────────────

    def log_execution_decision(self, symbol: str, side: str,
                              should_execute: bool, reason: str, checks: Dict = None):
        """
        Log execution decision with full context.

        Args:
            symbol: Trading pair
            side: "BUY" or "SELL"
            should_execute: Whether to execute
            reason: Why (e.g., "READY", "DUPLICATE", "PRICE_DRIFT")
            checks: Optional validation checks dict
        """
        decision = "OPEN" if should_execute else "SKIP"
        self.tracer.trace_execution_decision(symbol, side, decision, reason)

    # ──────────────────────────────────────────────────────────────────────────
    # STEP 6: EXECUTION SUCCESS (update state)
    # ──────────────────────────────────────────────────────────────────────────

    def on_execution_success(self, symbol: str, side: str, ticket: int,
                            exec_hash: str, positions_snapshot: list):
        """
        Update state after successful trade execution.

        Args:
            symbol: Trading pair
            side: "BUY" or "SELL"
            ticket: MT5 ticket number
            exec_hash: Execution-aware hash
            positions_snapshot: Current open positions list
        """
        # Update execution state
        self.execution_state.update(exec_hash, positions_snapshot)
        self.execution_state.save()

        # Trace
        self.tracer.trace_execution_completed(symbol, side, ticket)

        # Reset watchdog
        self.last_successful_cycle = time.time()

    # ──────────────────────────────────────────────────────────────────────────
    # STEP 7: EXECUTION FAILURE (log error)
    # ──────────────────────────────────────────────────────────────────────────

    def on_execution_failure(self, symbol: str, side: str, error: str):
        """
        Log execution failure.

        Args:
            symbol: Trading pair
            side: "BUY" or "SELL"
            error: Error message
        """
        self.tracer.trace_execution_failed(symbol, side, error)

    # ──────────────────────────────────────────────────────────────────────────
    # STEP 8: CYCLE MONITORING (watchdog + summary)
    # ──────────────────────────────────────────────────────────────────────────

    def log_cycle_summary(self, signals_count: int, executed_count: int,
                         skipped_count: int, cycle_duration_ms: float):
        """Log cycle summary."""
        self.tracer.trace_cycle_summary(
            signals_count, executed_count, skipped_count, cycle_duration_ms
        )

    def check_watchdog(self) -> bool:
        """
        Check if system is healthy (successful cycle within threshold).

        Returns:
            True if healthy, False if critical timeout
        """
        elapsed = time.time() - self.last_successful_cycle

        if elapsed > self.watchdog_threshold_seconds:
            self.tracer.trace_watchdog_critical(elapsed, self.watchdog_threshold_seconds)
            return False

        return True

    def reset_watchdog(self):
        """Reset watchdog timer."""
        elapsed = time.time() - self.last_successful_cycle
        self.tracer.trace_watchdog_reset(elapsed)
        self.last_successful_cycle = time.time()

    # ──────────────────────────────────────────────────────────────────────────
    # UTILITY: Get current positions snapshot
    # ──────────────────────────────────────────────────────────────────────────

    @staticmethod
    def get_positions_snapshot(positions_store) -> list:
        """Get list of (symbol, side) tuples for current open positions."""
        try:
            return list(positions_store.get_all_keys())
        except Exception:
            return []
