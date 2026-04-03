"""
Strategy Abstraction Layer - Clean separation of strategy-specific behavior

Supports multiple strategies that can be mixed and matched without affecting:
- Counter diff execution logic
- Position tracking
- Risk management infrastructure
- Multi-bot isolation

Each strategy defines:
1. Signal transformation (inversion, reversal, etc.)
2. Risk management policy (trailing stop, max loss)
3. No execution intelligence (purely observational)
"""

from abc import ABC, abstractmethod
from datetime import datetime
import copy

try:
    import pytz
    HAS_PYTZ = True
except ImportError:
    HAS_PYTZ = False


# ── Base Interface ────────────────────────────────────────────────────────

class BaseStrategy(ABC):
    """Abstract base. All strategies must implement transform_signal."""

    @abstractmethod
    def transform_signal(self, signal):
        """Return a transformed copy of the signal. Never mutate in-place.

        Args:
            signal: Signal object to transform

        Returns:
            Transformed signal copy (or same signal if no transform needed)
        """
        return copy.deepcopy(signal)

    @abstractmethod
    def should_apply_trailing(self) -> bool:
        """Whether this strategy uses trailing stop loss."""
        return False

    @abstractmethod
    def should_apply_max_loss(self) -> bool:
        """Whether this strategy uses max loss protection."""
        return False

    @property
    @abstractmethod
    def name(self) -> str:
        """Return strategy name for logging and config reference."""
        return self.__class__.__name__


# ── Strategy 1: Mirror ────────────────────────────────────────────────────

class MirrorStrategy(BaseStrategy):
    """Follow signals exactly as-is. Full risk management (trailing + max loss)."""

    def transform_signal(self, signal):
        """Pass signal through unchanged."""
        return copy.deepcopy(signal)  # No changes, just return copy

    def should_apply_trailing(self) -> bool:
        """Mirror strategy uses trailing stop."""
        return True

    def should_apply_max_loss(self) -> bool:
        """Mirror strategy uses max loss protection."""
        return True

    @property
    def name(self) -> str:
        """Strategy identifier."""
        return "mirror"


# ── Strategy 2: Reverse ──────────────────────────────────────────────────

class ReverseStrategy(BaseStrategy):
    """Always invert signal direction. No risk management."""

    def transform_signal(self, signal):
        """Invert signal: BUY↔SELL, swap TP↔SL."""
        sig = copy.deepcopy(signal)
        # Flip side
        sig.side = "BUY" if sig.side == "SELL" else "SELL"
        # Swap TP and SL
        sig.tp, sig.sl = sig.sl, sig.tp
        return sig

    def should_apply_trailing(self) -> bool:
        """Reverse strategy does NOT use trailing stop."""
        return False

    def should_apply_max_loss(self) -> bool:
        """Reverse strategy does NOT use max loss protection."""
        return False

    @property
    def name(self) -> str:
        """Strategy identifier."""
        return "reverse"


# ── Strategy 3: Time-Based Hybrid ────────────────────────────────────────

class TimeBasedStrategy(BaseStrategy):
    """
    Determines mode from SIGNAL TIME, not wall-clock time.

    Mode rules (based on signal.time in IST):
      4:00 PM – 7:59 PM IST  →  MIRROR  (follow signal as-is)
      All other hours         →  REVERSE (invert direction, swap tp/sl)

    Trailing stop + max loss always active regardless of mode.

    Why signal time?
      - Deterministic: same signal always produces same output
      - No mid-trade flipping: a trade opened as MIRROR stays MIRROR
      - Restart-safe: signal.time is fixed, runtime clock is not
    """

    FOLLOW_START = 16  # 4 PM IST
    FOLLOW_END = 20    # 8 PM IST

    @property
    def name(self) -> str:
        """Strategy identifier."""
        return "time_based"

    def _get_signal_hour_ist(self, signal) -> tuple:
        """
        Extract IST hour from signal.time.

        Args:
            signal: Signal object with .time attribute (datetime)

        Returns:
            Tuple of (hour: int, sig_time_ist: datetime)

        Falls back to current time ONLY if signal.time is missing.
        Fallback is logged as a warning — should not happen in production.
        """
        if HAS_PYTZ:
            ist = pytz.timezone("Asia/Kolkata")
        else:
            # Fallback to UTC offset (IST = UTC + 5:30)
            from datetime import timezone as tz_module, timedelta
            ist = tz_module(timedelta(hours=5, minutes=30))

        sig_time = getattr(signal, "time", None)

        if sig_time is None:
            # Fallback: use current time ONCE (signal ingestion gap)
            # This should only happen if signal_fetcher didn't stamp time
            sig_time = datetime.now(ist) if HAS_PYTZ else datetime.now(ist)
            print(
                f"[STRATEGY][WARNING] signal.time missing on "
                f"{getattr(signal, 'pair', 'UNKNOWN')} "
                f"{getattr(signal, 'side', '?')} — "
                f"falling back to current time: {sig_time.strftime('%H:%M:%S IST')}"
            )
        else:
            # Normalize to IST if naive or different timezone
            if sig_time.tzinfo is None:
                sig_time = ist.localize(sig_time)
            elif sig_time.tzinfo != ist:
                # Different timezone - convert to IST
                sig_time = sig_time.astimezone(ist)

        return sig_time.hour, sig_time

    def transform_signal(self, signal):
        """Transform signal based on SIGNAL TIME (not wall-clock time).

        Mode decision is bound to signal.time for determinism and restart-safety.
        """
        sig = copy.deepcopy(signal)

        try:
            hour, sig_time_ist = self._get_signal_hour_ist(signal)
        except Exception as e:
            # Safety: on any error, default to MIRROR (safest strategy)
            print(f"[STRATEGY][ERROR] Failed to extract signal time: {e} — defaulting to MIRROR")
            return sig

        # Determine mode from signal time hour
        is_mirror = self.FOLLOW_START <= hour < self.FOLLOW_END
        mode = "MIRROR" if is_mirror else "REVERSE"

        # Log transformation decision
        print(
            f"[STRATEGY] time_based | "
            f"pair={getattr(sig, 'pair', 'UNKNOWN')} "
            f"side={getattr(sig, 'side', '?')} | "
            f"signal_time={sig_time_ist.strftime('%Y-%m-%d %H:%M IST')} | "
            f"hour={hour} | "
            f"mode={mode}"
        )

        if is_mirror:
            # Follow signal as-is (MIRROR mode)
            return sig
        else:
            # Reverse: invert direction and swap TP/SL (REVERSE mode)
            sig.side = "BUY" if sig.side == "SELL" else "SELL"
            sig.tp, sig.sl = sig.sl, sig.tp
            return sig

    def should_apply_trailing(self) -> bool:
        """Time-based strategy always uses trailing stop."""
        return True

    def should_apply_max_loss(self) -> bool:
        """Time-based strategy always uses max loss protection."""
        return True



# ── Strategy Factory ─────────────────────────────────────────────────────

STRATEGY_MAP = {
    "mirror": MirrorStrategy,
    "reverse": ReverseStrategy,
    "time_based": TimeBasedStrategy,
}


def get_strategy(name: str) -> BaseStrategy:
    """
    Load strategy instance by name string from config.

    Args:
        name: Strategy name ("mirror", "reverse", or "time_based")

    Returns:
        Strategy instance

    Raises:
        ValueError: If strategy name is not recognized

    Usage:
        strategy = get_strategy(config.STRATEGY)
    """
    key = name.lower().strip()
    if key not in STRATEGY_MAP:
        available = ", ".join(sorted(STRATEGY_MAP.keys()))
        raise ValueError(
            f"Unknown strategy '{name}'. Valid options: {available}"
        )
    return STRATEGY_MAP[key]()
