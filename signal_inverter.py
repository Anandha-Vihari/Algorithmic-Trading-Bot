"""
SIGNAL INVERSION MODULE

Implements deterministic signal inversion for reverse-trade testing.
Inverts direction (BUY↔SELL) and swaps TP/SL at execution layer.

Safety Features:
- Validation that inverted levels are on correct side of entry price
- Logging of original vs inverted signals with outcomes
- Configurable on/off via REVERSE_MODE
- Zero-distance prevention
"""

from dataclasses import replace
from datetime import datetime, timezone
from signal_manager import Signal


# Global inversion log file
INVERSION_LOG_FILE = "signal_inversion.log"


def _log_inversion(message: str):
    """Write to inversion log file (thread-safe append)."""
    try:
        with open(INVERSION_LOG_FILE, 'a', encoding='utf-8') as f:
            timestamp = datetime.now(timezone.utc).isoformat()
            f.write(f"[{timestamp}] {message}\n")
            f.flush()
    except Exception as e:
        print(f"[INVERSION_LOG_ERR] Failed to write inversion log: {e}")


def validate_inverted_levels(side: str, entry_price: float, tp: float, sl: float) -> tuple[bool, str]:
    """
    Validate that inverted TP/SL are on correct sides of entry price.

    Args:
        side: "BUY" or "SELL" (AFTER inversion)
        entry_price: Market execution price
        tp: Take profit level (AFTER inversion)
        sl: Stop loss level (AFTER inversion)

    Returns:
        (is_valid: bool, reason: str)
    """
    # Check for zero distances
    if abs(tp - entry_price) < 0.00001:
        return False, "TP too close to entry (< 0.00001)"

    if abs(sl - entry_price) < 0.00001:
        return False, "SL too close to entry (< 0.00001)"

    # For BUY: SL must be BELOW entry, TP must be ABOVE entry
    if side == "BUY":
        if not (sl < entry_price < tp):
            return (False,
                   f"BUY: SL ({sl:.5f}) must be < entry ({entry_price:.5f}) < TP ({tp:.5f})")

    # For SELL: TP must be BELOW entry, SL must be ABOVE entry
    elif side == "SELL":
        if not (tp < entry_price < sl):
            return (False,
                   f"SELL: TP ({tp:.5f}) must be < entry ({entry_price:.5f}) < SL ({sl:.5f})")

    else:
        return False, f"Invalid side: {side}"

    return True, "Valid"


def invert_signal(signal: Signal, reverse_mode: bool) -> tuple[Signal, dict]:
    """
    Invert signal direction and swap TP/SL if reverse_mode is enabled.

    Args:
        signal: Original Signal object
        reverse_mode: If False, return signal unchanged

    Returns:
        (final_signal, metadata) where metadata contains:
            - was_inverted: bool
            - original_side: str
            - original_tp: float
            - original_sl: float
            - validation_result: (is_valid, reason)

    Raises:
        ValueError: If inversion produces invalid trade levels
    """

    metadata = {
        'was_inverted': False,
        'original_side': signal.side,
        'original_tp': signal.tp,
        'original_sl': signal.sl,
        'validation_result': (True, "Normal mode (no inversion)"),
    }

    # If reverse mode disabled, return original signal
    if not reverse_mode:
        return signal, metadata

    # ──── INVERT DIRECTION ──────────────────────────────────────────────────
    inverted_side = "SELL" if signal.side == "BUY" else "BUY"

    # ──── SWAP TP/SL ────────────────────────────────────────────────────────
    inverted_tp = signal.sl
    inverted_sl = signal.tp

    # ──── VALIDATE INVERTED LEVELS ───────────────────────────────────────────
    is_valid, reason = validate_inverted_levels(
        inverted_side, signal.open_price, inverted_tp, inverted_sl
    )

    metadata = {
        'was_inverted': True,
        'original_side': signal.side,
        'original_tp': signal.tp,
        'original_sl': signal.sl,
        'validation_result': (is_valid, reason),
    }

    if not is_valid:
        _log_inversion(
            f"VALIDATION FAILED | {signal.pair} {signal.side} @ {signal.open_price:.5f} "
            f"| Reason: {reason}"
        )
        raise ValueError(f"Invalid inverted levels: {reason}")

    # ──── CREATE INVERTED SIGNAL ─────────────────────────────────────────────
    inverted_signal = replace(
        signal,
        side=inverted_side,
        tp=inverted_tp,
        sl=inverted_sl
    )

    # ──── LOG INVERSION ──────────────────────────────────────────────────────
    _log_inversion(
        f"INVERTED | {signal.pair} | "
        f"Original: {signal.side:4s} @ {signal.open_price:.5f} | TP={signal.tp:.5f} SL={signal.sl:.5f} | "
        f"Inverted: {inverted_side:4s} @ {signal.open_price:.5f} | TP={inverted_tp:.5f} SL={inverted_sl:.5f}"
    )

    return inverted_signal, metadata


def log_trade_outcome(signal: Signal, ticket: int, success: bool, metadata: dict,
                     close_price: float = None, profit: float = None):
    """
    Log the final outcome of an inverted trade.

    Args:
        signal: Original (non-inverted) Signal object
        ticket: MT5 ticket number (or None if failed to open)
        success: Whether trade was successfully opened
        metadata: Metadata from invert_signal()
        close_price: Price if trade was closed
        profit: P&L if available
    """
    outcome = "SUCCESS" if success else "FAILED"

    original_info = (
        f"{signal.side} @ {signal.open_price:.5f} | "
        f"TP={signal.tp:.5f} SL={signal.sl:.5f}"
    )

    if metadata['was_inverted']:
        inverted_side = 'SELL' if signal.side == 'BUY' else 'BUY'
        inverted_info = (
            f"{inverted_side} @ {signal.open_price:.5f} | "
            f"TP={metadata['original_sl']:.5f} SL={metadata['original_tp']:.5f}"
        )
        ticket_str = str(ticket) if ticket else 'NONE'
        log_entry = (
            f"TRADE_OUTCOME | {outcome} | T{ticket_str:>10s} | "
            f"{signal.pair} | Original: {original_info} | Inverted: {inverted_info}"
        )
    else:
        ticket_str = str(ticket) if ticket else 'NONE'
        log_entry = f"TRADE_OUTCOME | {outcome} | T{ticket_str:>10s} | {signal.pair} | {original_info}"

    if close_price is not None:
        log_entry += f" | Close: {close_price:.5f}"

    if profit is not None:
        log_entry += f" | Profit: ${profit:.2f}"

    _log_inversion(log_entry)


def get_inversion_mode_status() -> dict:
    """Return current inversion mode configuration."""
    try:
        from config import REVERSE_MODE
        return {
            'enabled': REVERSE_MODE,
            'log_file': INVERSION_LOG_FILE,
            'status': 'INVERSION ENABLED' if REVERSE_MODE else 'Normal mode (inversion disabled)'
        }
    except ImportError:
        return {
            'enabled': False,
            'log_file': INVERSION_LOG_FILE,
            'status': 'Config import failed'
        }
