"""
EXECUTION STATE - Enhanced state persistence for v3

Tracks execution context beyond just signal deduplication.
Stores execution-aware hash, position snapshots, and timestamps.

Ensures recovery with full execution context after crash/restart.
"""

import json
from datetime import datetime, timezone
from atomic_io import atomic_write_json, safe_read_json


class ExecutionState:
    """Track execution context for recovery and deduplication."""

    def __init__(self, bot_id: int):
        """
        Initialize execution state tracker.

        Args:
            bot_id: Bot identifier (1, 2, or 3)
        """
        self.bot_id = bot_id
        self.state_file = f"execution_state_bot_{bot_id}.json"
        self.last_execution_hash = None
        self.positions_snapshot = []
        self.execution_timestamp = None
        self._load_state()

    def _load_state(self):
        """Load execution state from file on startup."""
        try:
            data = safe_read_json(self.state_file)
            if data:
                self.last_execution_hash = data.get('last_execution_hash')
                self.positions_snapshot = data.get('positions_snapshot', [])
                self.execution_timestamp = data.get('execution_timestamp')
                print(f"[EXECSTATE_BOT{self.bot_id}] Loaded execution state: "
                      f"hash={self.last_execution_hash[:8] if self.last_execution_hash else 'NONE'} "
                      f"positions={len(self.positions_snapshot)}")
        except Exception as e:
            print(f"[EXECSTATE_BOT{self.bot_id}] WARNING: Failed to load state: {e}")

    def update(self, execution_hash: str, positions_snapshot: list):
        """
        Update execution state after successful trade execution.

        Args:
            execution_hash: Execution-aware hash (content + prices + time)
            positions_snapshot: List of (symbol, side) tuples currently open
        """
        self.last_execution_hash = execution_hash
        self.positions_snapshot = positions_snapshot
        self.execution_timestamp = datetime.now(timezone.utc).isoformat()

    def save(self) -> bool:
        """
        Persist execution state atomically.

        Returns:
            True on success, False on failure
        """
        payload = {
            'bot_id': self.bot_id,
            'last_execution_hash': self.last_execution_hash,
            'positions_snapshot': self.positions_snapshot,
            'execution_timestamp': self.execution_timestamp,
            'saved_at': datetime.now(timezone.utc).isoformat()
        }

        success = atomic_write_json(self.state_file, payload)

        if success:
            print(f"[EXECSTATE_BOT{self.bot_id}] State saved: "
                  f"hash={self.last_execution_hash[:8] if self.last_execution_hash else 'NONE'}")

        return success

    def has_same_execution(self, execution_hash: str) -> bool:
        """
        Check if execution hash matches last execution.

        Used to detect duplicate execution attempts.

        Args:
            execution_hash: Current execution hash

        Returns:
            True if hash matches previous execution, False otherwise
        """
        return execution_hash == self.last_execution_hash

    def __repr__(self) -> str:
        """String representation for debugging."""
        return (f"ExecutionState(bot={self.bot_id}, "
                f"hash={self.last_execution_hash[:8] if self.last_execution_hash else 'NONE'}, "
                f"positions={len(self.positions_snapshot)})")
