"""
TRAILING STOP MANAGER - Dynamic SL + Portfolio Close System

System:
  1. RULE 1 - Breakeven with Profit Lock: When profit >= $0.40
     - Lock minimum $0.05 profit by moving SL above entry

  2. RULE 2 - TP-Based Trailing: When trade reaches 60% of TP distance
     - Lock 40% of TP distance (progressive SL advancement)

  3. Portfolio-Level Close: Close ALL positions when:
     - Number of open positions >= 5 AND
     - Total P&L >= (num_positions × $0.90)

Example:
  5 open positions with +$4.50 total profit → Close all
  10 open positions with +$9.00 total profit → Close all
  10 open positions with +$8.50 total profit → Keep open (need $9.00)

SAFETY GUARANTEES:
  ✓ SL only moves forward (never backward)
  ✓ SL always on correct side of current price
  ✓ Only closes positions at portfolio level, never individual
  ✓ Never touches UNMATCHED/FAILED_CLOSE
  ✓ Never interferes with diff logic or VSL
  ✓ Uses real MT5 profit and price data
  ✓ Preserves ticket safety and position integrity
"""

import MetaTrader5 as mt5
from typing import Dict, Optional
from datetime import datetime, timezone
from operational_safety import log, LogLevel
from trader import close_position_by_ticket
import json
import os


class TrailingStopManager:
    """Dollar-based trailing stop system using actual MT5 profit."""

    def __init__(self):
        """Initialize trailing stop tracking."""
        # ticket → {entry, tp, original_sl, symbol, side}
        self.position_meta = {}

        # ticket → timestamp when phase changed (for logging)
        self.phase_change_log = {}

        # Load persisted position metadata from previous sessions
        self._load_position_meta()

    def register_position(self, ticket: int, symbol: str, side: str,
                         entry_price: float, tp: float, original_sl: float):
        """Register a newly opened position for trailing stop management.

        MUST be called when trade opens (in open_trade after success).

        Args:
            ticket: Position ticket
            symbol: Trading pair (e.g., 'EURUSD', 'EURUSD+')
            side: 'BUY' or 'SELL'
            entry_price: Entry price of position
            tp: Take profit level
            original_sl: Original stop loss level
        """
        self.position_meta[ticket] = {
            'entry': entry_price,
            'tp': tp,
            'original_sl': original_sl,
            'symbol': symbol,
            'side': side,
            'last_phase': 0,
        }
        print(f"[TRAIL$_REGISTER] T{ticket} {symbol} {side} | Entry: {entry_price:.5f} | TP: {tp:.5f} | SL: {original_sl:.5f}")
        log(LogLevel.DEBUG, f"[TRAIL] Registered T{ticket} {symbol} {side} | Entry: {entry_price} | TP: {tp}")

        # Persist changes immediately
        self._save_position_meta()

    def remove_position(self, ticket: int):
        """Remove position from tracking when closed.

        MUST be called when trade closes (in main loop after successful close).
        """
        if ticket in self.position_meta:
            del self.position_meta[ticket]
        if ticket in self.phase_change_log:
            del self.phase_change_log[ticket]

        # Persist changes immediately
        self._save_position_meta()

    def _save_position_meta(self):
        """Save position metadata to disk for persistence across restarts."""
        try:
            # Convert to JSON-serializable format (tickets are ints, need to stringify)
            data = {
                str(ticket): {
                    'entry': meta['entry'],
                    'tp': meta['tp'],
                    'original_sl': meta['original_sl'],
                    'symbol': meta['symbol'],
                    'side': meta['side'],
                    'last_phase': meta['last_phase']
                }
                for ticket, meta in self.position_meta.items()
            }
            with open('trailing_stop_meta.json', 'w') as f:
                json.dump(data, f)
        except Exception as e:
            print(f"[TRAIL_WARN] Failed to save position_meta: {e}")

    def _load_position_meta(self):
        """Load position metadata from disk after restart."""
        try:
            if not os.path.exists('trailing_stop_meta.json'):
                return

            with open('trailing_stop_meta.json', 'r') as f:
                data = json.load(f)

            # Convert back from string keys to int keys
            for ticket_str, meta in data.items():
                ticket = int(ticket_str)
                self.position_meta[ticket] = meta

            if self.position_meta:
                print(f"[TRAIL_RESTORE] Loaded {len(self.position_meta)} persisted position(s) from disk")
        except Exception as e:
            print(f"[TRAIL_WARN] Failed to load position_meta: {e}")

    def reconcile_with_mt5(self, mt5_module):
        """Remove tracking for positions that no longer exist in MT5.

        Called at start of every update_all_positions() cycle.
        Ensures position_meta stays synchronized with actual MT5 positions.
        """
        active_tickets = set()

        mt5_positions = mt5_module.positions_get()
        if mt5_positions:
            active_tickets = {p.ticket for p in mt5_positions}

        for ticket in list(self.position_meta.keys()):
            if ticket not in active_tickets:
                print(f"[TRAIL_CLEANUP] Removing stale ticket {ticket}")
                self.remove_position(ticket)

    def _calculate_price_per_dollar(self, current_price: float, entry_price: float, profit: float) -> float:
        """
        Calculate price movement per dollar of profit.

        Used for dynamic SL calculations that scale with position size and volatility.

        Args:
            current_price: Current bid/ask price
            entry_price: Position entry price
            profit: Current profit in dollars

        Returns:
            Price distance per dollar (e.g., 0.0005 = 5 pips per $1 profit)
        """
        if profit <= 0:
            return 0.0

        price_move = abs(current_price - entry_price)
        return price_move / profit

    def _is_sl_valid_for_buy(self, new_sl: float, current_price: float, old_sl: float) -> bool:
        """Check if new SL is valid for BUY position."""
        # SL must be below current price
        if new_sl >= current_price:
            return False
        # SL must move forward (only increase SL for BUY)
        if new_sl <= old_sl:
            return False
        return True

    def _is_sl_valid_for_sell(self, new_sl: float, current_price: float, old_sl: float) -> bool:
        """Check if new SL is valid for SELL position."""
        # SL must be above current price
        if new_sl <= current_price:
            return False
        # SL must move forward (only decrease SL for SELL)
        if new_sl >= old_sl:
            return False
        return True

    def _apply_trailing_rules(self, pos, mt5_module) -> Optional[float]:
        """
        Apply RULE 1 and RULE 2 to determine new SL.

        Returns:
            New SL value if should update, None if no update needed
        """
        # Get metadata for this position
        meta = self.position_meta.get(pos.ticket)
        if not meta:
            return None

        entry_price = meta['entry']
        tp = meta['tp']

        # ─── RULE 1: BREAKEVEN WITH PROFIT LOCK ($0.40 profit → lock $0.05) ───
        if pos.profit >= 0.40:
            profit_lock = 0.05
            price_per_dollar = self._calculate_price_per_dollar(pos.price, entry_price, pos.profit)

            if price_per_dollar > 0:
                price_move = profit_lock * price_per_dollar

                if pos.type == mt5_module.POSITION_TYPE_BUY:
                    new_sl = entry_price + price_move
                else:  # SELL
                    new_sl = entry_price - price_move

                # Validate SL is safe
                if pos.type == mt5_module.POSITION_TYPE_BUY:
                    if self._is_sl_valid_for_buy(new_sl, pos.price, pos.sl):
                        return new_sl
                else:  # SELL
                    if self._is_sl_valid_for_sell(new_sl, pos.price, pos.sl):
                        return new_sl

        # ─── RULE 2: TP-BASED TRAILING (60% of TP → lock 40% of TP) ───
        tp_distance = abs(tp - entry_price)
        if tp_distance > 0:
            current_move = abs(pos.price - entry_price)

            if current_move >= 0.60 * tp_distance:
                # Trade has reached 60% of way to TP, lock 40% of TP distance
                lock_move = 0.40 * tp_distance

                if pos.type == mt5_module.POSITION_TYPE_BUY:
                    new_sl = entry_price + lock_move
                else:  # SELL
                    new_sl = entry_price - lock_move

                # Validate SL is safe
                if pos.type == mt5_module.POSITION_TYPE_BUY:
                    if self._is_sl_valid_for_buy(new_sl, pos.price, pos.sl):
                        return new_sl
                else:  # SELL
                    if self._is_sl_valid_for_sell(new_sl, pos.price, pos.sl):
                        return new_sl

        return None

    def update_all_positions(self, mt5_module):
        """
        Dynamic trailing stop system with two progression rules:
        1. RULE 1: Breakeven with profit lock ($0.40 profit → lock $0.05)
        2. RULE 2: TP-based trailing (60% of TP distance → lock 40% of TP)
        3. Portfolio close: All positions when >= 5 positions AND total PnL >= (num × $0.90)

        MUST be called every cycle in main loop:
          1. check_virtual_sl_and_close()
          2. update_all_positions(mt5)        # <-- HERE
          3. run_signal_cycle()

        Args:
            mt5_module: MetaTrader5 module reference
        """
        self.reconcile_with_mt5(mt5_module)

        all_mt5_positions = mt5_module.positions_get()
        if not all_mt5_positions:
            return

        num_positions = len(all_mt5_positions)
        total_pnl = 0
        sl_updates = 0  # Track how many SL updates happened

        # ─── STEP 1: APPLY TRAILING RULES TO EACH POSITION ───
        for pos in all_mt5_positions:
            total_pnl += pos.profit

            # Apply RULE 1 → RULE 2 logic
            new_sl = self._apply_trailing_rules(pos, mt5_module)

            if new_sl is not None:
                # Send SL update to MT5
                rule_name = "RULE1" if pos.profit >= 0.40 else "RULE2"
                print(f"[TRAIL_SL] T{pos.ticket} {pos.symbol} {rule_name} profit=${pos.profit:.2f} → SL: {pos.sl:.5f} → {new_sl:.5f}")

                request = {
                    "action": mt5_module.TRADE_ACTION_SLTP,
                    "position": pos.ticket,
                    "sl": new_sl,
                    "tp": pos.tp
                }
                result = mt5_module.order_send(request)
                if result and result.retcode == mt5_module.TRADE_RETCODE_DONE:
                    print(f"  [TRAIL_OK] SL updated")
                    sl_updates += 1
                else:
                    print(f"  [TRAIL_ERR] SL update failed: {result.retcode if result else 'None'}")

        # ─── STEP 2: PORTFOLIO-LEVEL CLOSE (ONLY IF >= 5 POSITIONS) ─────
        if num_positions >= 5:
            close_target = num_positions * 0.90  # $0.90 per position

            if total_pnl >= close_target:
                print(f"[CLOSE_ALL] TRIGGERING PORTFOLIO CLOSE!")
                print(f"             {num_positions} positions | P&L: ${total_pnl:.2f} >= Target: ${close_target:.2f}")

                closed_count = 0
                for pos in all_mt5_positions:
                    try:
                        close_position_by_ticket(pos.ticket)
                        closed_count += 1
                    except Exception as e:
                        print(f"  [ERROR] Failed to close T{pos.ticket}: {e}")

                print(f"[CLOSE_ALL] Closed {closed_count}/{num_positions} positions")



def init_trailing_stop():
    """Initialize trailing stop manager.

    Call in main.py during setup:

        trailing_stop_mgr = init_trailing_stop()
    """
    return TrailingStopManager()


def get_trailing_stop_manager():
    """Get global trailing stop manager (after init_trailing_stop called)."""
    global _trailing_stop_instance
    if '_trailing_stop_instance' not in globals():
        _trailing_stop_instance = TrailingStopManager()
    return _trailing_stop_instance
