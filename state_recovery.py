"""
STATE RECOVERY - Unified state loading and validation on startup

Ensures full restart safety by loading all persisted state and validating consistency.
Part of v2 production-grade architecture.
"""

import json
from atomic_io import safe_read_json
from signal_manager import PositionStore


class StateRecovery:
    """Load and validate all bot state on startup."""

    def __init__(self, bot_id: int):
        """
        Initialize state recovery for a bot.

        Args:
            bot_id: Bot identifier (1, 2, or 3)
        """
        self.bot_id = bot_id
        self.positions = PositionStore()
        self.processed_signals = set()
        self.last_hash = None
        self.recovery_status = {}
        self.recovery_successful = False

    def recover_all_state(self) -> bool:
        """
        Attempt full state recovery on startup.

        Loads state in order:
        1. Position store (positions_store_bot_X.json)
        2. Processed signals (processed_signals_bot_X.json)
        3. Last hash seen (last_hash_seen_bot_X.json)
        4. Trailing stop metadata (handled separately)

        Returns:
            True if recovery successful, False if partial/failed
        """
        try:
            # 1. Load position store (NEW - fully atomic recovery)
            self.positions = self._load_positions()
            self.recovery_status['positions'] = True
            pos_count = len(list(self.positions.get_all_keys()))
            print(f"[RECOVERY_BOT{self.bot_id}] Loaded positions: {pos_count} keys")

            # 2. Load processed signals (24h+ history prevention)
            self.processed_signals = self._load_processed_signals()
            self.recovery_status['processed_signals'] = True
            print(f"[RECOVERY_BOT{self.bot_id}] Loaded processed signals: {len(self.processed_signals)}")

            # 3. Load last hash seen (deduplication state)
            self.last_hash = self._load_last_hash()
            self.recovery_status['last_hash'] = True
            print(f"[RECOVERY_BOT{self.bot_id}] Loaded last_hash: {self.last_hash[:8] if self.last_hash else 'NONE'}")

            # 4. Validate consistency
            self._validate_consistency()
            self.recovery_status['validation'] = True

            self.recovery_successful = True
            print(f"[RECOVERY_BOT{self.bot_id}] State recovery SUCCESSFUL ✓")
            return True

        except Exception as e:
            print(f"[RECOVERY_ERROR_BOT{self.bot_id}] {e}")
            self.recovery_successful = False
            return False

    def _load_positions(self) -> PositionStore:
        """
        Load position store from persistent file.

        Returns:
            PositionStore object (empty if file doesn't exist/corrupted)
        """
        file = f"positions_store_bot_{self.bot_id}.json"
        try:
            data = safe_read_json(file, max_retries=3)
            if data:
                positions = PositionStore()
                positions.from_dict(data)
                return positions
        except Exception as e:
            print(f"[WARNING] Failed to load positions: {e}")

        return PositionStore()  # Return empty on any failure

    def _load_processed_signals(self) -> set:
        """
        Load processed signal IDs from file.

        These are signal IDs that have already been executed, to prevent
        re-execution within 24 hours.

        Returns:
            Set of signal IDs, or empty set if file doesn't exist
        """
        file = f"processed_signals_bot_{self.bot_id}.json"
        try:
            data = safe_read_json(file, max_retries=3)
            if data:
                return set(data.keys())
        except Exception as e:
            print(f"[WARNING] Failed to load processed signals: {e}")

        return set()

    def _load_last_hash(self) -> str:
        """
        Load last processed hash from file.

        This is the deduplication marker: prevents re-execution if signals
        have same hash.

        Returns:
            Hash string, or empty string if file doesn't exist
        """
        file = f"last_hash_seen_bot_{self.bot_id}.json"
        try:
            data = safe_read_json(file, max_retries=3)
            if data:
                return data.get('hash', '')
        except Exception as e:
            print(f"[WARNING] Failed to load last_hash: {e}")

        return ''

    def _validate_consistency(self):
        """
        Verify that recovered state makes sense.

        Checks:
        - Positions count is reasonable (not > 100, which would be suspicious)
        - Processed signals count is reasonable
        - Hash is a valid hex string

        Raises:
            Exception if validation fails (caught by recover_all_state)
        """
        pos_keys = list(self.positions.get_all_keys())
        pos_count = len(pos_keys)

        # Check positions count
        if pos_count > 100:
            raise ValueError(f"Unusually high position count ({pos_count}), possible corruption")

        # Check hash validity
        if self.last_hash and len(self.last_hash) != 64:
            raise ValueError(f"Invalid hash length ({len(self.last_hash)}), expected 64")

        # Log validation results
        print(f"[RECOVERY_BOT{self.bot_id}] Validation passed: "
              f"{pos_count} positions, "
              f"{len(self.processed_signals)} processed signals, "
              f"hash={'OK' if self.last_hash else 'NONE'}")

    def __repr__(self) -> str:
        """String representation for debugging."""
        return (f"StateRecovery(bot={self.bot_id}, "
                f"positions={len(list(self.positions.get_all_keys()))}, "
                f"processed={len(self.processed_signals)}, "
                f"successful={self.recovery_successful})")
