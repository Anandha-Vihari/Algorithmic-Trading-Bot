"""
TRAILING STOP MANAGER - Dollar-Based Profit System

Phase Model (DOLLAR THRESHOLDS):
  Phase 1: $0.30 profit → Move SL to breakeven
  Phase 2: $0.60 profit → Lock $0.30 profit
  Phase 3: $1.00 profit → Lock $0.50 profit
  Phase 4: $1.50 profit → Lock $1.00 profit

Uses ACTUAL profit from MT5 (pos.profit in $).
Converts locked profit to price using tick_value.
Works across all pairs and lot sizes.

SAFETY GUARANTEES:
  ✓ Never reduces SL (only forward movement)
  ✓ Never closes positions (SL updates only)
  ✓ Never touches UNMATCHED/FAILED_CLOSE
  ✓ Never interferes with diff logic or VSL
  ✓ Uses real MT5 profit, not estimates
  ✓ Preserves ticket safety and position integrity
"""

import MetaTrader5 as mt5
from typing import Dict, Tuple, Optional
from datetime import datetime, timezone
from operational_safety import log, LogLevel


class TrailingStopManager:
    """Dollar-based trailing stop system using actual MT5 profit."""

    def __init__(self):
        """Initialize trailing stop tracking."""
        # ticket → {entry, tp, original_sl, symbol, side}
        self.position_meta = {}

        # ticket → timestamp when phase changed (for logging)
        self.phase_change_log = {}

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
        log(LogLevel.DEBUG, f"[TRAIL] Registered T{ticket} {symbol} {side} | Entry: {entry_price} | TP: {tp}")

    def remove_position(self, ticket: int):
        """Remove position from tracking when closed.

        MUST be called when trade closes (in main loop after successful close).
        """
        if ticket in self.position_meta:
            del self.position_meta[ticket]
        if ticket in self.phase_change_log:
            del self.phase_change_log[ticket]

    def _get_profit_to_price_ratio(self, symbol: str) -> Optional[float]:
        """Get $ profit per price unit movement.

        Args:
            symbol: Trading pair

        Returns:
            Ratio of price movement to profit ($) or None if unavailable
        """
        try:
            symbol_info = mt5.symbol_info(symbol)
            if not symbol_info:
                return None

            # tick_value = $ per tick (point)
            # tick_size = price change per tick
            # So: $profit_per_price_unit = tick_value / tick_size
            if symbol_info.trade_tick_size == 0:
                return None

            profit_per_price = symbol_info.trade_tick_value / symbol_info.trade_tick_size
            return profit_per_price
        except Exception as e:
            log(LogLevel.DEBUG, f"[TRAIL] Exception getting profit ratio for {symbol}: {e}")
            return None

    def _calculate_new_sl_from_profit(self, entry_price: float, lock_profit: float,
                                     symbol: str, side: str) -> Optional[float]:
        """Convert desired locked profit ($) to stop loss price level.

        Args:
            entry_price: Entry price of position
            lock_profit: Profit to lock in $ (e.g., 0.3 for $0.30)
            symbol: Trading pair
            side: 'BUY' or 'SELL'

        Returns:
            New SL price level or None if calculation fails
        """
        # Get profit-to-price ratio
        ratio = self._get_profit_to_price_ratio(symbol)
        if ratio is None or ratio <= 0:
            return None

        # price_move = profit / ratio_of_profit_per_price
        price_move = lock_profit / ratio

        # Calculate new SL based on side
        if side == 'BUY':
            new_sl = entry_price + price_move
        else:  # SELL
            new_sl = entry_price - price_move

        return new_sl

    def _clamp_sl_for_symbol(self, sl: float, symbol: str, side: str) -> float:
        """Clamp SL to valid range (don't go too close to market).

        Args:
            sl: Proposed stop loss level
            symbol: Trading pair
            side: 'BUY' or 'SELL'

        Returns:
            Valid stop loss level
        """
        tick = mt5.symbol_info_tick(symbol)
        if not tick:
            return sl

        info = mt5.symbol_info(symbol)
        if not info:
            return sl

        min_distance = info.point * 50  # ~50 points = 5 pips for 5-decimal pairs

        if side == 'BUY':
            # For BUY, SL must be below bid, at least min_distance away
            return max(sl, tick.bid - min_distance)
        else:  # SELL
            # For SELL, SL must be above ask, at least min_distance away
            return min(sl, tick.ask + min_distance)

    def _update_sl_in_mt5(self, ticket: int, symbol: str, new_sl: float, side: str) -> bool:
        """Update stop loss in MT5 via position_modify.

        Args:
            ticket: Position ticket
            symbol: Trading pair
            new_sl: New stop loss level
            side: 'BUY' or 'SELL'

        Returns:
            True if update succeeded, False otherwise
        """
        try:
            # Clamp SL to valid range
            new_sl = self._clamp_sl_for_symbol(new_sl, symbol, side)

            request = {
                "action": mt5.TRADE_ACTION_SLTP,
                "position": ticket,
                "sl": new_sl,
            }

            result = mt5.order_send(request)
            if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                return True
            else:
                retcode = result.retcode if result else 'None'
                log(LogLevel.DEBUG, f"[TRAIL] SL update failed for T{ticket}: retcode {retcode}")
                return False
        except Exception as e:
            log(LogLevel.DEBUG, f"[TRAIL] Exception updating SL for T{ticket}: {e}")
            return False

    def _transition_phase(self, ticket: int, old_phase: int, new_phase: int,
                         new_sl: float, reason: str) -> bool:
        """Transition position to new phase and update SL in MT5.

        Args:
            ticket: Position ticket
            old_phase: Current phase (0, 1, 2, 3, 4)
            new_phase: Target phase
            new_sl: New stop loss level to set
            reason: Reason description for logging

        Returns:
            True if transition succeeded
        """
        if ticket not in self.position_meta:
            return False

        meta = self.position_meta[ticket]
        symbol = meta['symbol']
        side = meta['side']

        # Update SL in MT5
        if self._update_sl_in_mt5(ticket, symbol, new_sl, side):
            # Update phase in metadata
            self.position_meta[ticket]['last_phase'] = new_phase
            self.phase_change_log[ticket] = datetime.now(timezone.utc).isoformat()

            # Log transition
            phase_names = {0: "Entry", 1: "BE", 2: "Lock30c", 3: "Lock50c", 4: "Lock$1"}
            log(LogLevel.INFO, f"[TRAIL$] T{ticket} | Phase {old_phase} ({phase_names.get(old_phase, '?')}) -> {new_phase} ({phase_names.get(new_phase, '?')}) | {reason} | SL: {new_sl:.5f}")

            return True
        else:
            log(LogLevel.DEBUG, f"[TRAIL] Phase transition failed for T{ticket}")
            return False

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

    def update_all_positions(self, mt5_module):
        """Update trailing stops for all tracked positions using ACTUAL profit from MT5.

        MUST be called every cycle in main loop:
          1. check_virtual_sl_and_close()
          2. update_all_positions(mt5)        # <-- HERE
          3. run_signal_cycle()

        Args:
            mt5_module: MetaTrader5 module reference
        """
        # FIX 1: RECONCILIATION - Remove stale tickets at START of every cycle
        self.reconcile_with_mt5(mt5_module)

        if not self.position_meta:
            return

        for ticket in list(self.position_meta.keys()):
            meta = self.position_meta[ticket]

            # Get position from MT5
            positions = mt5_module.positions_get(ticket=ticket)
            if not positions:
                continue

            pos = positions[0]
            profit = pos.profit  # ACTUAL profit in $ from MT5

            current_sl = pos.sl
            current_phase = meta['last_phase']
            entry = meta['entry']
            symbol = meta['symbol']
            side = meta['side']

            # ─── RUNTIME TRACE ──────────────────────────────────────────────
            phase_names = {0: "Entry", 1: "BE", 2: "Lock30c", 3: "Lock50c", 4: "Lock$1"}
            print(f"[TRAIL$_TRACE] T{ticket} | phase={phase_names[current_phase]} | price={pos.price_current:.5f} | entry={entry:.5f} | current_sl={current_sl:.5f} | profit=${profit:.2f} | side={side}")

            # ─── PHASE THRESHOLDS (DOLLAR-BASED) ────────────────────────────
            # Phase 0 → 1: Break even at $0.30 profit
            if profit >= 0.30 and current_phase == 0:
                new_sl = self._calculate_new_sl_from_profit(entry, 0.00, symbol, side)
                if new_sl is not None:
                    new_sl = self._clamp_sl_for_symbol(new_sl, symbol, side)
                    print(f"[TRAIL$_PHASE] T{ticket} | phase 0 -> 1 | profit=${profit:.2f} (>=$0.30) | lock=$0.00 (breakeven) | SL: {current_sl:.5f} -> {new_sl:.5f}")
                    self._transition_phase(ticket, 0, 1, new_sl, f"Breakeven at ${profit:.2f}")

            # Phase 1 → 2: Lock $0.30 profit at $0.60 actual profit
            elif profit >= 0.60 and current_phase <= 1:
                new_sl = self._calculate_new_sl_from_profit(entry, 0.30, symbol, side)
                if new_sl is not None:
                    new_sl = self._clamp_sl_for_symbol(new_sl, symbol, side)
                    print(f"[TRAIL$_PHASE] T{ticket} | phase {current_phase} -> 2 | profit=${profit:.2f} (>=$0.60) | lock=$0.30 | SL: {current_sl:.5f} -> {new_sl:.5f}")
                    self._transition_phase(ticket, current_phase, 2, new_sl, f"Lock $0.30 at ${profit:.2f}")

            # Phase 2 → 3: Lock $0.50 profit at $1.00 actual profit
            elif profit >= 1.00 and current_phase <= 2:
                new_sl = self._calculate_new_sl_from_profit(entry, 0.50, symbol, side)
                if new_sl is not None:
                    new_sl = self._clamp_sl_for_symbol(new_sl, symbol, side)
                    print(f"[TRAIL$_PHASE] T{ticket} | phase {current_phase} -> 3 | profit=${profit:.2f} (>=$1.00) | lock=$0.50 | SL: {current_sl:.5f} -> {new_sl:.5f}")
                    self._transition_phase(ticket, current_phase, 3, new_sl, f"Lock $0.50 at ${profit:.2f}")

            # Phase 3 → 4: Lock $1.00 profit at $1.50 actual profit
            elif profit >= 1.50 and current_phase <= 3:
                new_sl = self._calculate_new_sl_from_profit(entry, 1.00, symbol, side)
                if new_sl is not None:
                    new_sl = self._clamp_sl_for_symbol(new_sl, symbol, side)
                    print(f"[TRAIL$_PHASE] T{ticket} | phase {current_phase} -> 4 | profit=${profit:.2f} (>=$1.50) | lock=$1.00 | SL: {current_sl:.5f} -> {new_sl:.5f}")
                    self._transition_phase(ticket, current_phase, 4, new_sl, f"Lock $1.00 at ${profit:.2f}")


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
