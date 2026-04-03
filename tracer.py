"""
TRACER - Structured trace logging for execution debugging

Provides consistent, structured logging for:
- Signal processing decisions
- Hash transitions
- Validation checks
- Execution outcomes

Key design: All logs include context for post-session analysis.
"""

from datetime import datetime, timezone


class ExecutionTracer:
    """Structured tracer for debugging execution flows."""

    def __init__(self, bot_id: int):
        """
        Initialize execution tracer.

        Args:
            bot_id: Bot identifier (1, 2, or 3)
        """
        self.bot_id = bot_id

    def trace_signal_received(self, symbol: str, side: str, signal_price: float):
        """Log signal reception."""
        print(f"[TRACE_BOT{self.bot_id}] Signal received: {symbol} {side} @ {signal_price:.5f}")

    def trace_hash_check(self, current_hash: str, last_hash: str, is_new: bool):
        """Log hash deduplication check."""
        status = "NEW" if is_new else "DUPLICATE"
        print(f"[TRACE_BOT{self.bot_id}] Hash check: current={current_hash[:8]} "
              f"last={last_hash[:8] if last_hash else 'NONE'} → {status}")

    def trace_execution_hash(self, exec_hash: str, price: float, time_bucket: int):
        """Log execution-aware hash computation."""
        print(f"[TRACE_BOT{self.bot_id}] Execution hash: {exec_hash[:8]} "
              f"(price={price:.5f}, time_bucket={time_bucket})")

    def trace_mt5_sync(self, synced: bool, removed: int, added: int, live_count: int):
        """Log MT5 reconciliation."""
        print(f"[TRACE_BOT{self.bot_id}] MT5 sync: "
              f"removed={removed} added={added} live={live_count} synced={synced}")

    def trace_position_check(self, symbol: str, side: str, in_mt5: bool, in_store: bool):
        """Log duplicate position checks."""
        print(f"[TRACE_BOT{self.bot_id}] Position check: {symbol} {side} "
              f"in_mt5={in_mt5} in_store={in_store}")

    def trace_price_drift(self, symbol: str, signal_price: float, current_price: float,
                         drift_pips: float, max_slippage: float, passed: bool):
        """Log latency guard (price drift) check."""
        status = "PASS" if passed else "FAIL"
        print(f"[TRACE_BOT{self.bot_id}] Price drift {status}: {symbol} "
              f"signal={signal_price:.5f} current={current_price:.5f} "
              f"drift={drift_pips:.1f}pips max={max_slippage:.1f}pips")

    def trace_stale_check(self, age_seconds: float, max_age: float, is_stale: bool):
        """Log stale data check."""
        status = "STALE" if is_stale else "FRESH"
        print(f"[TRACE_BOT{self.bot_id}] Freshness {status}: age={age_seconds:.1f}s max={max_age:.1f}s")

    def trace_pre_execution_validation(self, checks: dict):
        """
        Log pre-execution validation summary.

        Args:
            checks: dict with validation results:
            {
                "hash_unique": bool,
                "not_in_mt5": bool,
                "not_in_store": bool,
                "not_stale": bool,
                "price_drift_ok": bool,
                "all_pass": bool
            }
        """
        results = " ".join([f"{k}={v}" for k, v in checks.items() if k != "all_pass"])
        status = "ALL_PASS" if checks.get("all_pass") else "FAILED"
        print(f"[TRACE_BOT{self.bot_id}] Pre-execution validation {status}: {results}")

    def trace_execution_decision(self, symbol: str, side: str, decision: str, reason: str):
        """
        Log execution decision.

        Args:
            symbol: Trading pair
            side: "BUY" or "SELL"
            decision: "OPEN" or "SKIP"
            reason: Why this decision (e.g., "READY", "DUPLICATE", "STALE")
        """
        print(f"[TRACE_BOT{self.bot_id}] Execution: {symbol} {side} "
              f"decision={decision} reason={reason}")

    def trace_execution_completed(self, symbol: str, side: str, ticket: int = None):
        """Log successful trade execution."""
        if ticket:
            print(f"[TRACE_BOT{self.bot_id}] Trade opened: {symbol} {side} ticket={ticket}")
        else:
            print(f"[TRACE_BOT{self.bot_id}] Signal processed: {symbol} {side} (no ticket)")

    def trace_execution_failed(self, symbol: str, side: str, error: str):
        """Log failed execution."""
        print(f"[TRACE_BOT{self.bot_id}] Execution FAILED: {symbol} {side} error={error}")

    def trace_cycle_summary(self, signals_count: int, executed_count: int, skipped_count: int,
                          cycle_duration_ms: float):
        """Log cycle summary for monitoring."""
        print(f"[TRACE_BOT{self.bot_id}] Cycle summary: "
              f"signals={signals_count} executed={executed_count} skipped={skipped_count} "
              f"duration={cycle_duration_ms:.0f}ms")

    def trace_watchdog_reset(self, last_success_ago_seconds: float):
        """Log watchdog timer reset."""
        print(f"[TRACE_BOT{self.bot_id}] Watchdog reset: last_success={last_success_ago_seconds:.1f}s ago")

    def trace_watchdog_critical(self, last_success_ago_seconds: float, threshold_seconds: float):
        """Log watchdog critical alert."""
        print(f"[TRACE_BOT{self.bot_id}] ⚠️  WATCHDOG CRITICAL: "
              f"no success for {last_success_ago_seconds:.1f}s (threshold={threshold_seconds}s)")

    def __repr__(self) -> str:
        """String representation for debugging."""
        return f"ExecutionTracer(bot={self.bot_id})"
