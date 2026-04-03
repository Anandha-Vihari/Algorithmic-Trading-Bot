"""
SIGNAL INVERTER - Reverse Trading Signals by Time Window

Inverts signals (BUY↔SELL) during specific IST hours.
Used by Bot 1 only for time-based trading mode switching.

Key logic:
- BUY → SELL (opposite direction)
- TP ↔ SL (swap because opposite direction)
- Time window: 13:00-17:00 IST (07:30-11:30 UTC)
"""

from datetime import datetime, timezone, timedelta
from signal_manager import Signal


class SignalInverter:
    """Invert trading signals (BUY↔SELL, swap TP/SL) based on time window."""

    # IST = UTC + 5:30
    # 13:00 IST = 07:30 UTC
    # 17:00 IST = 11:30 UTC
    FOLLOW_HOURS_IST_START = 13  # 13:00 IST
    FOLLOW_HOURS_IST_END = 17    # 17:00 IST (exclusive, so 16:59:59 is the last minute)
    IST_OFFSET = timedelta(hours=5, minutes=30)

    @staticmethod
    def is_inversion_time():
        """
        Check if current time is within signal inversion window (IST).

        Returns:
            True if 13:00 <= IST hour < 17:00
            False otherwise
        """
        now_utc = datetime.now(timezone.utc)
        now_ist = now_utc + SignalInverter.IST_OFFSET
        hour_ist = now_ist.hour

        # Check if within 13:00-17:00 IST range
        is_within = (
            SignalInverter.FOLLOW_HOURS_IST_START <= hour_ist
            < SignalInverter.FOLLOW_HOURS_IST_END
        )

        return is_within

    @staticmethod
    def invert_signal(sig: Signal) -> Signal:
        """
        Invert a single signal.

        Transformation:
        - BUY → SELL (opposite direction)
        - SELL → BUY
        - TP and SL are SWAPPED (because opposite direction)

        Why swap TP/SL?
        - Original BUY @ 1.100, TP 1.105, SL 1.095:
          Price goes UP → TP hits
        - Inverted SELL @ 1.100, TP 1.095, SL 1.105:
          Price goes DOWN → TP hits
        - Same net outcome: profit when price moves into predicted direction

        Args:
            sig: Signal object to invert

        Returns:
            New Signal object with inverted side and swapped TP/SL

        Raises:
            Exception if signal is invalid
        """
        if not sig.side in ("BUY", "SELL"):
            raise ValueError(f"Invalid signal side: {sig.side}")

        inverted_side = "SELL" if sig.side == "BUY" else "BUY"

        # Swap TP and SL for inverted direction
        inverted_tp = sig.sl
        inverted_sl = sig.tp

        return Signal(
            pair=sig.pair,
            side=inverted_side,
            open_price=sig.open_price,
            tp=inverted_tp,
            sl=inverted_sl,
            time=sig.time,
            frame=sig.frame,
            status=sig.status,
            close_price=sig.close_price,
            close_reason=sig.close_reason
        )

    @staticmethod
    def apply_inversion_filter(signals: list) -> list:
        """
        Apply inversion to signals during follow hours.

        Args:
            signals: List of Signal objects

        Returns:
            Filtered/inverted signal list
            - If within follow hours: return inverted signals (BUY↔SELL, TP/SL swapped)
            - If outside follow hours: return signals as-is

        On error:
            Skips malformed signal (neither uses inverted nor original)
        """
        if not SignalInverter.is_inversion_time():
            # Outside follow hours: keep signals as-is
            return signals

        # During follow hours (13:00-17:00 IST): invert all signals
        inverted_signals = []
        for sig in signals:
            try:
                inverted = SignalInverter.invert_signal(sig)
                inverted_signals.append(inverted)
            except Exception as e:
                print(f"[INVERTER_ERROR] Failed to invert {sig.pair} {sig.side}: {e}")
                # On error, skip this signal (don't use original or inverted)
                continue

        return inverted_signals

    @staticmethod
    def validate_inversion():
        """
        Sanity check: ensure inversion logic is correct.

        Raises:
            AssertionError if any validation fails
        """
        from signal_manager import Signal
        from datetime import datetime, timezone

        test_sig = Signal(
            pair="EURUSD",
            side="BUY",
            open_price=1.100,
            tp=1.105,
            sl=1.095,
            time=datetime.now(timezone.utc),
            frame="short",
            status="ACTIVE",
            close_price=None,
            close_reason=None
        )

        inverted = SignalInverter.invert_signal(test_sig)

        # Validate inversions
        assert inverted.side == "SELL", f"Side not inverted: {inverted.side}"
        assert inverted.tp == test_sig.sl, f"TP not set to original SL: {inverted.tp} != {test_sig.sl}"
        assert inverted.sl == test_sig.tp, f"SL not set to original TP: {inverted.sl} != {test_sig.tp}"
        assert inverted.pair == test_sig.pair, f"Pair changed: {inverted.pair} != {test_sig.pair}"
        assert inverted.open_price == test_sig.open_price, f"Entry changed: {inverted.open_price} != {test_sig.open_price}"

        print("[INVERTER] Validation passed ✓")


if __name__ == "__main__":
    # Run validation on module import
    SignalInverter.validate_inversion()
