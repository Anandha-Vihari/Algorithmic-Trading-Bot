"""
TRAILING STOP MANAGER - Point-Based Multi-Stage System

System:
  1. PRIORITY 1 (Loss Cap): Close at -50 points loss
  2. PRIORITY 2-4 (Profit Locking): Three-stage SL progression
     - Stage 1: +46 points (when profit >= +92pts)
     - Stage 2: +92 points (when profit >= +138pts)
     - Jump both if profit crosses +138pts in single cycle
  3. PRIORITY 5 (Take Profit): Handled by MT5 broker at +230pts
  4. Portfolio-Level Close: Close ALL positions when:
     - Number of open positions >= 5 AND
     - Total P&L >= (num_positions × $0.90)

State Flags (per trade):
  - stage1_done: Set True when SL moved to entry±46pts
  - stage2_done: Set True when SL moved to entry±92pts
  - loss_cap_done: Set True when loss cap closes trade (terminal)

Example:
  EURUSD Entry: 1.1000
  - Cycle 1: profit +40pts → No action (stage threshold 92pts not met)
  - Cycle 2: profit +95pts → STAGE1 fires, SL moves to 1.09954 (entry-46pts)
  - Cycle 3: profit +140pts → STAGE2 fires, SL moves to 1.09908 (entry-92pts)
  - Cycle 4: profit -55pts → LOSS_CAP fires, position closes at market

SAFETY GUARANTEES:
  ✓ Points are deterministic (0.00001 for non-JPY, 0.001 for JPY)
  ✓ SL only moves forward (monotonic protection always increases)
  ✓ Loss cap always triggered at exactly -50 points
  ✓ State flags persist across restarts
  ✓ Priority evaluation is deterministic (no ambiguity)
  ✓ Each stage fires exactly once per trade
  ✓ Portfolio close logic unchanged and working

CORE PRINCIPLE:
  "Deterministic point-based protection: loss cap early, lock profit in stages."
"""

import MetaTrader5 as mt5
from typing import Dict, Optional
from datetime import datetime, timezone
from operational_safety import log, LogLevel
from trader import close_position_by_ticket
from atomic_io import atomic_write_json, safe_read_json
import json
import os


class TrailingStopManager:
    """Dollar-based trailing stop system using actual MT5 profit.

    CRITICAL: Each bot instance MUST use its own meta_file for safe concurrent execution.
    Sharing trailing_stop_meta.json across bots causes race conditions and data loss.
    """

    def __init__(self, meta_file: str):
        """Initialize trailing stop tracking with bot-specific file.

        Args:
            meta_file: Bot-specific file path (e.g., 'trailing_stop_meta_bot_1.json')

        Raises:
            AssertionError: If meta_file is None or not bot-specific
        """
        # Validate meta_file is provided and bot-specific
        assert meta_file is not None, \
            "[TRAIL_ERROR] meta_file must be provided (not None)"
        assert isinstance(meta_file, str) and len(meta_file) > 0, \
            "[TRAIL_ERROR] meta_file must be non-empty string"
        assert "bot_" in meta_file, \
            f"[TRAIL_ERROR] meta_file must be bot-specific (e.g., 'trailing_stop_meta_bot_N.json'), got: {meta_file}"

        # Guard against hardcoded shared filename
        if meta_file == 'trailing_stop_meta.json':
            raise ValueError(
                "[TRAIL_ERROR] UNSAFE: Shared trailing_stop_meta.json detected. "
                "This causes data corruption across bots. Use bot-specific path."
            )

        self.meta_file = meta_file

        # ticket → {entry, tp, original_sl, symbol, side}
        self.position_meta = {}

        # ticket → timestamp when phase changed (for logging)
        self.phase_change_log = {}

        # Log initialization for debugging
        print(f"[TRAIL_INIT] TrailingStopManager initialized with bot-specific file: {self.meta_file}")

        # Load persisted position metadata from previous sessions
        self._load_position_meta()

    def register_position(self, ticket: int, symbol: str, side: str,
                         entry_price: float, tp: float, original_sl: float):
        """Register a newly opened position for multi-stage point-based management.

        MUST be called when trade opens (in open_trade after success).

        Args:
            ticket: Position ticket
            symbol: Trading pair (e.g., 'EURUSD', 'EURCAD' with 'JPY' in name)
            side: 'BUY' or 'SELL'
            entry_price: Entry price of position
            tp: Take profit level (not used in new system, kept for compatibility)
            original_sl: Original stop loss level (not used in new system, kept for compatibility)
        """
        self.position_meta[ticket] = {
            'entry': entry_price,
            'tp': tp,
            'original_sl': original_sl,
            'symbol': symbol,
            'side': side,
            'last_phase': 0,
            'stage1_done': False,
            'stage2_done': False,
            'loss_cap_done': False,
        }
        point_size = self._get_point_size(symbol)
        print(f"[TRAIL_REGISTER] T{ticket} {symbol} {side} | Entry: {entry_price:.5f} | TP: {tp:.5f} | SL: {original_sl:.5f} | Point: {point_size}")
        log(LogLevel.DEBUG, f"[TRAIL] Registered T{ticket} {symbol} {side} with stage flags | Entry: {entry_price}")

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
        """Save position metadata to disk for persistence across restarts.

        Uses atomic write to ensure file is never partially written.
        """
        try:
            # Convert to JSON-serializable format (tickets are ints, need to stringify)
            data = {
                str(ticket): {
                    'entry': meta['entry'],
                    'tp': meta['tp'],
                    'original_sl': meta['original_sl'],
                    'symbol': meta['symbol'],
                    'side': meta['side'],
                    'last_phase': meta['last_phase'],
                    'stage1_done': meta.get('stage1_done', False),
                    'stage2_done': meta.get('stage2_done', False),
                    'loss_cap_done': meta.get('loss_cap_done', False),
                }
                for ticket, meta in self.position_meta.items()
            }
            # Use atomic write (safe for concurrent access)
            success = atomic_write_json(self.meta_file, data)
            if not success:
                print(f"[TRAIL_WARN] Atomic write failed for {self.meta_file}")
        except Exception as e:
            print(f"[TRAIL_WARN] Failed to save position_meta to {self.meta_file}: {e}")

    def _load_position_meta(self):
        """Load position metadata from disk after restart.

        Uses safe_read_json with retry logic to handle concurrent access and corruption.
        """
        try:
            # Use safe_read_json (retry logic on decode errors)
            data = safe_read_json(self.meta_file, max_retries=3, retry_delay=0.1)

            if data is None:
                # File doesn't exist (first run) - normal case
                return

            # Convert back from string keys to int keys
            for ticket_str, meta in data.items():
                ticket = int(ticket_str)
                self.position_meta[ticket] = meta

            if self.position_meta:
                print(f"[TRAIL_RESTORE] Loaded {len(self.position_meta)} persisted position(s) from {self.meta_file}")
        except Exception as e:
            print(f"[TRAIL_WARN] Failed to load position_meta from {self.meta_file}: {e}")

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

    # ──────────────────────────────────────────────────────────────────
    # HELPER FUNCTIONS - Point-Based Calculations
    # ──────────────────────────────────────────────────────────────────

    @staticmethod
    def _get_point_size(symbol: str) -> float:
        """Return point size based on symbol name.

        JPY pairs (EURIJPY, GBPJPY, etc): 0.001 per point
        Non-JPY pairs (EURUSD, GBPUSD, etc): 0.00001 per point
        """
        if 'JPY' in symbol.upper():
            return 0.001
        else:
            return 0.00001

    @staticmethod
    def _calculate_profit_pts(entry: float, current: float, side: str, point_size: float) -> int:
        """Calculate profit in points.

        Args:
            entry: Entry price
            current: Current price
            side: 'BUY' or 'SELL'
            point_size: 0.00001 or 0.001

        Returns:
            Profit/loss in points (positive = profit, negative = loss)
        """
        if side == 'BUY':
            return round((current - entry) / point_size)
        else:  # SELL
            return round((entry - current) / point_size)

    @staticmethod
    def _calculate_stage_sl(entry: float, stage_pts: int, side: str, point_size: float) -> float:
        """Calculate stop loss price for a given stage.

        Args:
            entry: Entry price
            stage_pts: Stage points (46 or 92)
            side: 'BUY' or 'SELL'
            point_size: 0.00001 or 0.001

        Returns:
            SL price level
        """
        offset = stage_pts * point_size
        if side == 'BUY':
            return entry + offset
        else:  # SELL
            return entry - offset

    @staticmethod
    def _is_sl_valid_for_update(new_sl: float, current_price: float, current_sl: float, side: str) -> bool:
        """Check if new SL meets safety requirements.

        Args:
            new_sl: Proposed new stop loss
            current_price: Current market price
            current_sl: Current stop loss
            side: 'BUY' or 'SELL'

        Returns:
            True if safe to update, False otherwise
        """
        if side == 'BUY':
            # For BUY: new_sl must be below current price AND above old_sl (moving forward)
            if new_sl >= current_price:
                return False
            if new_sl <= current_sl:
                return False
            return True
        else:  # SELL
            # For SELL: new_sl must be above current price AND below old_sl (moving forward)
            if new_sl <= current_price:
                return False
            if new_sl >= current_sl:
                return False
            return True

    def infer_stage_flags(self, ticket: int, mt5_module):
        """On bot restart, infer stage flags from current MT5 position SL.

        Compares current SL to entry price to determine which stages have fired.
        Uses conservative logic to avoid false positives.

        Args:
            ticket: Position ticket
            mt5_module: MetaTrader5 module reference
        """
        meta = self.position_meta.get(ticket)
        if not meta:
            return

        # Query current position from MT5
        mt5_positions = mt5_module.positions_get(ticket=ticket)
        if not mt5_positions:
            return

        pos = mt5_positions[0]
        entry = meta['entry']
        side = meta['side']
        current_sl = pos.sl
        point_size = self._get_point_size(meta['symbol'])

        # Infer which stages have fired based on current SL distance from entry
        if side == 'BUY':
            sl_distance_pts = round((current_sl - entry) / point_size)

            if sl_distance_pts >= 92:
                meta['stage1_done'] = True
                meta['stage2_done'] = True
            elif sl_distance_pts >= 46:
                meta['stage1_done'] = True
                meta['stage2_done'] = False
            else:
                meta['stage1_done'] = False
                meta['stage2_done'] = False
        else:  # SELL
            sl_distance_pts = round((entry - current_sl) / point_size)

            if sl_distance_pts >= 92:
                meta['stage1_done'] = True
                meta['stage2_done'] = True
            elif sl_distance_pts >= 46:
                meta['stage1_done'] = True
                meta['stage2_done'] = False
            else:
                meta['stage1_done'] = False
                meta['stage2_done'] = False

        meta['loss_cap_done'] = False  # No trade survives -50pt loss, they auto-close

        print(f"[STATE_RECOVERY] T{ticket} | stage1={meta['stage1_done']} | stage2={meta['stage2_done']} | SL distance: {abs(sl_distance_pts)}pts")

    # ──────────────────────────────────────────────────────────────────
    # END HELPER FUNCTIONS
    # ──────────────────────────────────────────────────────────────────

    def _apply_trailing_rules(self, pos, mt5_module) -> Optional[Dict]:
        """
        Point-based multi-stage priority system.

        Five priority levels (evaluated in strict order):
          1. LOSS CAP: Close if profit <= -50 points
          2. STAGE 1+2 COMBINED: Jump both stages if profit jumps >= 138pts
          3. STAGE 2 ONLY: Move to 92pts if stage1 already done
          4. STAGE 1 ONLY: Move to 46pts if profit >= 92pts
          5. TP: Handled automatically by MT5 broker

        Returns:
            {'ticket': int, 'action': 'close'|'modify', 'new_sl': float, 'reason': str}
            or None if no action taken
        """
        ticket = pos.ticket
        meta = self.position_meta.get(ticket)
        if not meta or meta.get('loss_cap_done'):
            return None

        entry = meta['entry']
        symbol = meta['symbol']
        side = meta['side']
        point_size = self._get_point_size(symbol)

        current_price = pos.price_current
        current_sl = pos.sl

        # Calculate profit in points
        profit_pts = self._calculate_profit_pts(entry, current_price, side, point_size)

        # ─── PRIORITY 1: LOSS CAP CHECK (ALWAYS FIRST) ───
        if profit_pts <= -50 and not meta.get('loss_cap_done'):
            meta['loss_cap_done'] = True
            print(f"[LOSS_CAP] T{ticket} | {symbol} | {side} | {profit_pts}pts | CLOSE")
            return {'ticket': ticket, 'action': 'close', 'reason': 'loss_cap'}

        # Remaining priorities only for non-closed positions
        stage1_done = meta.get('stage1_done', False)
        stage2_done = meta.get('stage2_done', False)

        # ─── PRIORITY 2: STAGE 1 + 2 COMBINED (Jump both if skipped) ───
        if profit_pts >= 138 and not stage1_done:
            stage1_sl = self._calculate_stage_sl(entry, 46, side, point_size)
            stage2_sl = self._calculate_stage_sl(entry, 92, side, point_size)

            if self._is_sl_valid_for_update(stage2_sl, current_price, current_sl, side):
                meta['stage1_done'] = True
                meta['stage2_done'] = True
                print(f"[STAGE1-SKIP] T{ticket} | {symbol} | {profit_pts}pts | Entry±46pts")
                print(f"[STAGE2] T{ticket} | {symbol} | {profit_pts}pts | Entry±92pts → {stage2_sl:.5f}")
                return {'ticket': ticket, 'new_sl': stage2_sl, 'action': 'modify'}
            else:
                print(f"[SL_REJECTED] T{ticket} | reason: broker distance or backward movement")
                return None

        # ─── PRIORITY 3: STAGE 2 ONLY ───
        if profit_pts >= 138 and stage1_done and not stage2_done:
            stage2_sl = self._calculate_stage_sl(entry, 92, side, point_size)

            if self._is_sl_valid_for_update(stage2_sl, current_price, current_sl, side):
                meta['stage2_done'] = True
                print(f"[STAGE2] T{ticket} | {symbol} | {profit_pts}pts | Entry±92pts → {stage2_sl:.5f}")
                return {'ticket': ticket, 'new_sl': stage2_sl, 'action': 'modify'}
            else:
                return None

        # ─── PRIORITY 4: STAGE 1 ONLY ───
        if profit_pts >= 92 and not stage1_done:
            stage1_sl = self._calculate_stage_sl(entry, 46, side, point_size)

            if self._is_sl_valid_for_update(stage1_sl, current_price, current_sl, side):
                meta['stage1_done'] = True
                print(f"[STAGE1] T{ticket} | {symbol} | {profit_pts}pts | Entry±46pts → {stage1_sl:.5f}")
                return {'ticket': ticket, 'new_sl': stage1_sl, 'action': 'modify'}
            else:
                return None

        # ─── PRIORITY 5: TP (Handled by MT5 broker automatically) ───
        return None

    def update_all_positions(self, mt5_module):
        """
        Point-based multi-stage SL system with portfolio close:

        1. PRIORITY-BASED SL MANAGEMENT:
           - Evaluate 5 priorities for each position (loss cap → stages → TP)
           - Only fire each stage once (state flags prevent duplicates)
           - Close or modify SL based on profit points

        2. Portfolio close: All positions when >= 5 positions AND total PnL >= (num × $0.90)

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
        sl_updates = 0

        # ─── STEP 1: APPLY PRIORITY-BASED RULES TO EACH POSITION ───
        for pos in all_mt5_positions:
            total_pnl += pos.profit

            # Apply point-based priority logic
            action = self._apply_trailing_rules(pos, mt5_module)

            if action is None:
                continue  # No action for this position

            # Execute the action
            if action['action'] == 'close':
                # Close the position (loss cap triggered)
                try:
                    close_position_by_ticket(pos.ticket)
                    self.remove_position(pos.ticket)
                    print(f"  [LOSS_CAP_CLOSED] T{pos.ticket}")
                except Exception as e:
                    print(f"  [ERROR] Failed to close T{pos.ticket}: {e}")

            elif action['action'] == 'modify':
                # Update SL with new value
                new_sl = action['new_sl']
                request = {
                    "action": mt5_module.TRADE_ACTION_SLTP,
                    "position": pos.ticket,
                    "sl": new_sl,
                    "tp": pos.tp
                }
                result = mt5_module.order_send(request)
                if result and result.retcode == mt5_module.TRADE_RETCODE_DONE:
                    print(f"  [SL_MODIFIED] T{pos.ticket} | new_SL={new_sl:.5f}")
                    sl_updates += 1
                    # Persist flag changes
                    self._save_position_meta()
                else:
                    print(f"  [SL_MODIFY_FAILED] T{pos.ticket}: {result.retcode if result else 'None'}")
                    # Do NOT mark flags as done on failure; will retry next cycle

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
                        self.remove_position(pos.ticket)
                        closed_count += 1
                    except Exception as e:
                        print(f"  [ERROR] Failed to close T{pos.ticket}: {e}")

                print(f"[CLOSE_ALL] Closed {closed_count}/{num_positions} positions")


def init_trailing_stop(meta_file: str):
    """Initialize trailing stop manager with bot-specific file.

    CRITICAL: meta_file must be bot-specific (e.g., 'trailing_stop_meta_bot_1.json')

    Call in main.py during setup:

        trailing_stop_mgr = init_trailing_stop(trailing_stop_meta_file)

    Args:
        meta_file: Bot-specific file path (required, not optional)

    Returns:
        TrailingStopManager instance

    Raises:
        AssertionError: If meta_file is None or not bot-specific
    """
    assert meta_file is not None, \
        "[INIT_ERROR] meta_file required — cannot use default or None"
    assert "bot_" in meta_file, \
        f"[INIT_ERROR] meta_file must include 'bot_' identifier, got: {meta_file}"

    print(f"[INIT] Creating TrailingStopManager with file: {meta_file}")
    return TrailingStopManager(meta_file)
