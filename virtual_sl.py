"""Virtual SL - Spread-Aware Stop Loss Management

Prevents premature SL hits due to spread widening.
Keeps original broker SL as safety net.
Prevents immediate reopen after bot-triggered closes.
"""

from typing import Dict, Tuple, Set
from operational_safety import log, LogLevel


class VirtualSLManager:
    """Manages spread-aware stop losses for all open positions."""

    def __init__(self, spread_factor: float = 1.5):
        """
        Initialize Virtual SL manager.
        
        Args:
            spread_factor: Multiplier for spread compensation (1.5-2.0)
                          Higher = more protection from spread spikes
        """
        self.spread_factor = spread_factor
        
        # {ticket: {original_sl, tp, side, pair, entry_price}}
        self.metadata = {}
        
        # {key} - positions closed by bot (prevent immediate reopen)
        self.closed_by_bot = set()

    def add_position(self, ticket: int, pair: str, side: str, 
                     original_sl: float, tp: float, entry_price: float):
        """Register position for virtual SL tracking."""
        self.metadata[ticket] = {
            "ticket": ticket,
            "pair": pair,
            "side": side,
            "original_sl": original_sl,
            "tp": tp,
            "entry_price": entry_price,
        }

    def remove_position(self, ticket: int):
        """Unregister position (normal close)."""
        self.metadata.pop(ticket, None)

    def mark_closed_by_bot(self, key: Tuple):
        """Mark key as closed by bot (prevent reopen)."""
        self.closed_by_bot.add(key)

    def clear_closed_by_bot(self, key: Tuple):
        """Remove from closed_by_bot (signal reappeared)."""
        self.closed_by_bot.discard(key)

    def is_closed_by_bot(self, key: Tuple) -> bool:
        """Check if position was closed by virtual SL."""
        return key in self.closed_by_bot

    def check_and_close_all(self, mt5, positions, close_position_cb):
        """Check virtual SL for all positions and close if triggered.
        
        Args:
            mt5: MT5 API object
            positions: PositionStore instance
            close_position_cb: Callback function(ticket, pair) -> bool
            
        Returns:
            List of (ticket, key, close_reason) closed by virtual SL
        """
        closed_tickets = []

        # Iterate through all positions
        for key, tickets in list(positions.positions.items()):
            if not tickets:
                continue

            # Skip special buckets
            if key[0] in ("_UNMATCHED_", "_FAILED_CLOSE_"):
                continue

            pair = key[0]
            side = key[1]

            try:
                # Get current tick price and spread
                tick = mt5.symbol_info_tick(pair)
                if not tick:
                    log(LogLevel.DEBUG, f"No tick for {pair}, skipping virtual SL check")
                    continue

                spread = tick.ask - tick.bid
                bid = tick.bid
                ask = tick.ask

                # Check each ticket in this key
                for ticket in tickets[:]:  # Copy list to iterate safely
                    if ticket not in self.metadata:
                        log(LogLevel.DEBUG, f"No metadata for ticket {ticket}, skipping")
                        continue

                    meta = self.metadata[ticket]
                    original_sl = meta["original_sl"]

                    # Determine trigger SL
                    should_close = False
                    close_reason = None

                    if side == "BUY":
                        # For BUY: SL is below entry
                        # Add spread compensation below SL
                        trigger_sl = original_sl - (spread * self.spread_factor)

                        if bid <= trigger_sl:
                            should_close = True
                            close_reason = (
                                f"Virtual SL triggered | "
                                f"BID {bid:.5f} <= trigger {trigger_sl:.5f} | "
                                f"Spread {spread:.5f} (original SL: {original_sl:.5f})"
                            )

                    elif side == "SELL":
                        # For SELL: SL is above entry
                        # Add spread compensation above SL
                        trigger_sl = original_sl + (spread * self.spread_factor)

                        if ask >= trigger_sl:
                            should_close = True
                            close_reason = (
                                f"Virtual SL triggered | "
                                f"ASK {ask:.5f} >= trigger {trigger_sl:.5f} | "
                                f"Spread {spread:.5f} (original SL: {original_sl:.5f})"
                            )

                    # Execute close if triggered
                    if should_close:
                        try:
                            result = close_position_cb(ticket, pair)
                            if result:
                                # Successful close
                                positions.remove_ticket(ticket)
                                self.remove_position(ticket)
                                self.mark_closed_by_bot(key)
                                closed_tickets.append((ticket, key, close_reason))
                                
                                log(LogLevel.INFO, f"Virtual SL closed ticket {ticket}: {close_reason}")
                            else:
                                # Close failed
                                log(LogLevel.WARN, f"Failed to close ticket {ticket} on virtual SL: {close_reason}")
                        except Exception as e:
                            log(LogLevel.ERROR, f"Error closing ticket {ticket} via virtual SL: {e}")

            except Exception as e:
                log(LogLevel.ERROR, f"Error checking virtual SL for {pair}: {e}")

        return closed_tickets

    def cleanup_closed_signals(self, curr_keys):
        """Remove from closed_by_bot if signal reappeared.
        
        When a signal disappears and reappears, allow reopening.
        Call this after computing curr_keys in main loop.
        """
        # Convert to set for efficient lookup
        curr_keys_set = set(curr_keys)

        # Remove any keys no longer in current signals
        to_remove = [key for key in self.closed_by_bot if key not in curr_keys_set]
        for key in to_remove:
            self.closed_by_bot.discard(key)
            log(LogLevel.DEBUG, f"Signal {key} reappeared, allowing reopen")


# Global instance
virtual_sl_manager = None


def init_virtual_sl(spread_factor: float = 1.5):
    """Initialize virtual SL manager."""
    global virtual_sl_manager
    virtual_sl_manager = VirtualSLManager(spread_factor=spread_factor)
    return virtual_sl_manager


def get_virtual_sl_manager():
    """Get singleton instance."""
    global virtual_sl_manager
    if virtual_sl_manager is None:
        virtual_sl_manager = VirtualSLManager()
    return virtual_sl_manager
