"""
MT5 RECONCILIATION ENGINE - Broker-truth synchronization

Ensures positions_store matches actual MT5 state.
Eliminates desync between local tracking and broker reality.

Key Functions:
- sync_positions_with_mt5() - Reconcile store with broker
- get_live_positions() - Get current positions from MT5
- validate_position_on_broker() - Check if position exists
"""

import MetaTrader5 as mt5
from signal_manager import PositionStore, SignalKey
from datetime import datetime, timezone


# Map MT5 position types to trading sides
POSITION_TYPE_MAP = {
    mt5.ORDER_TYPE_BUY: "BUY",
    mt5.ORDER_TYPE_SELL: "SELL",
    0: "BUY",   # Fallback for order type 0
    1: "SELL"   # Fallback for order type 1
}


def get_live_positions() -> dict:
    """
    Get current positions from MT5.

    Returns:
        dict mapping (symbol, side) → MT5 position object
        Empty dict if query fails
    """
    try:
        mt5_positions = mt5.positions_get()
        if mt5_positions is None:
            print("[MT5SYNC] WARNING: positions_get() returned None")
            return {}

        live_map = {}
        for pos in mt5_positions:
            symbol = pos.symbol
            side = POSITION_TYPE_MAP.get(pos.type, "UNKNOWN")

            if side != "UNKNOWN":
                key = (symbol, side)
                live_map[key] = pos

        return live_map

    except Exception as e:
        print(f"[MT5SYNC] ERROR: Failed to query MT5 positions: {e}")
        return {}


def sync_positions_with_mt5(positions_store: PositionStore) -> dict:
    """
    Reconcile positions_store with actual MT5 state.

    Process:
    1. Get live positions from MT5
    2. Remove stale entries from store (closed on broker)
    3. Add missing entries to store (opened on broker)
    4. Return reconciliation summary

    Args:
        positions_store: PositionStore object to update

    Returns:
        dict with reconciliation stats:
        {
            "removed": N,      # entries removed from store
            "added": N,        # entries added to store
            "live_count": N,   # total live positions
            "store_count": N   # total store count after sync
        }
    """
    try:
        # Get broker positions
        live_map = get_live_positions()
        live_keys = set(live_map.keys())

        # Get store positions
        store_keys = set(positions_store.get_all_keys())

        # Phase 1: Remove stale entries (closed on broker)
        removed_keys = store_keys - live_keys
        removed_count = 0

        for key in removed_keys:
            try:
                positions_store.remove(key)
                removed_count += 1
                symbol, side = key
                print(f"[MT5SYNC] Removed stale: {symbol} {side}")
            except Exception as e:
                print(f"[MT5SYNC] WARNING: Failed to remove {key}: {e}")

        # Phase 2: Add missing entries (opened on broker)
        added_keys = live_keys - store_keys
        added_count = 0

        for key in added_keys:
            try:
                positions_store.add(key)
                added_count += 1
                symbol, side = key
                print(f"[MT5SYNC] Added missing: {symbol} {side}")
            except Exception as e:
                print(f"[MT5SYNC] WARNING: Failed to add {key}: {e}")

        # Phase 3: Summary
        after_sync_keys = set(positions_store.get_all_keys())
        stats = {
            "removed": removed_count,
            "added": added_count,
            "live_count": len(live_keys),
            "store_count": len(after_sync_keys),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

        # Log summary
        if removed_count > 0 or added_count > 0:
            print(f"[MT5SYNC] Reconciliation: removed={removed_count} added={added_count} "
                  f"live={len(live_keys)} store={len(after_sync_keys)}")

        return stats

    except Exception as e:
        print(f"[MT5SYNC] CRITICAL ERROR: {e}")
        return {
            "removed": 0,
            "added": 0,
            "live_count": -1,
            "store_count": -1,
            "error": str(e)
        }


def validate_position_on_broker(symbol: str, side: str) -> bool:
    """
    Check if a specific position exists on broker.

    Args:
        symbol: Trading pair (e.g., "EURUSD")
        side: "BUY" or "SELL"

    Returns:
        True if position exists, False otherwise
    """
    try:
        live_map = get_live_positions()
        return (symbol, side) in live_map
    except Exception as e:
        print(f"[MT5SYNC] ERROR: validate_position failed: {e}")
        return False


def get_position_from_broker(symbol: str, side: str):
    """
    Get position object from broker.

    Args:
        symbol: Trading pair
        side: "BUY" or "SELL"

    Returns:
        MT5 position object, or None if not found
    """
    try:
        live_map = get_live_positions()
        return live_map.get((symbol, side))
    except Exception as e:
        print(f"[MT5SYNC] ERROR: get_position failed: {e}")
        return None
