"""
SIGNAL DEDUPLICATOR v3 - Content + Execution-aware hashing

Detects and prevents re-execution of identical signals across cycles and restarts.
Implements Layer 1 of 4-layer deduplication system.

V3 Enhancement:
- compute_hash() - Content-only (v2 compatible)
- compute_execution_hash() - Execution-aware (prices + time context) NEW
"""

import json
import hashlib
import time
from datetime import datetime, timezone
from atomic_io import safe_read_json, atomic_write_json


class SignalDeduplicator:
    """Track signal content via SHA256 hash to prevent duplicate execution."""

    def __init__(self, bot_id: int):
        """
        Initialize signal deduplicator for a bot.

        Args:
            bot_id: Bot identifier (1, 2, or 3)
        """
        self.bot_id = bot_id
        self.hash_file = f"last_hash_seen_bot_{bot_id}.json"
        self.last_hash = self._load_last_hash()
        print(f"[DEDUP_BOT{bot_id}] Initialized, last_hash={self.last_hash[:8] if self.last_hash else 'NONE'}")

    @staticmethod
    def compute_hash(signals: list) -> str:
        """
        Compute SHA256 hash of signal content (deterministic).

        Hashes the JSON-serialized signals with sorted keys to ensure
        consistency regardless of insertion order or version changes.

        Args:
            signals: List of signal dictionaries

        Returns:
            Hex string of SHA256 hash (64 characters)

        Example:
            >>> sig1 = [{"pair": "EURUSD", "side": "BUY", ...}]
            >>> sig2 = [{"pair": "EURUSD", "side": "BUY", ...}]
            >>> SignalDeduplicator.compute_hash(sig1) == SignalDeduplicator.compute_hash(sig2)
            True
        """
        # Serialize with sorted keys for deterministic output
        content = json.dumps(signals, sort_keys=True, separators=(',', ':'))
        return hashlib.sha256(content.encode('utf-8')).hexdigest()

    @staticmethod
    def compute_execution_hash(signals: list, prices: dict = None) -> str:
        """
        Compute execution-aware hash (v3 enhancement).

        Includes execution context: signal content + current prices + time bucket.
        Same signal but different prices/time → different hash.

        This prevents false duplicate detection when market conditions change.

        Args:
            signals: List of signal dictionaries
            prices: dict mapping symbol → current price (bid/ask average)
                   If None, defaults to empty dict

        Returns:
            Hex string of SHA256 hash (64 characters)

        Example:
            >>> sig = [{"pair": "EURUSD", "side": "BUY", ...}]
            >>> prices = {"EURUSD": 1.0805}
            >>> time_bucket = int(time.time() // 60)
            >>> hash1 = compute_execution_hash(sig, prices)
            >>> # Later, price changes to 1.0810
            >>> prices = {"EURUSD": 1.0810}
            >>> hash2 = compute_execution_hash(sig, prices)
            >>> hash1 != hash2  # Different hashes → can execute again
        """
        if prices is None:
            prices = {}

        # Round prices to avoid noise from tick-level variations
        rounded_prices = {k: round(v, 5) for k, v in prices.items()}

        # Bucket time to 1-minute granularity (avoids micro-variation)
        time_bucket = int(time.time() // 60)

        # Create execution context payload
        payload = {
            "signals": signals,
            "prices": rounded_prices,
            "time_bucket": time_bucket
        }

        # Serialize with sorted keys for deterministic output
        content = json.dumps(payload, sort_keys=True, separators=(',', ':'))
        return hashlib.sha256(content.encode('utf-8')).hexdigest()

    def _load_last_hash(self) -> str:
        """
        Load last processed hash from file on startup.

        Prevents duplicate execution after restart.

        Returns:
            Last hash string, or empty string if file doesn't exist
        """
        try:
            data = safe_read_json(self.hash_file)
            if data:
                return data.get('hash', '')
        except:
            pass
        return ''

    def should_process(self, current_hash: str) -> bool:
        """
        Check if current hash is new (not seen before).

        Layer 1 of deduplication: detects identical signals with new version.

        Args:
            current_hash: SHA256 hash of current signals

        Returns:
            True if hash is new (should process)
            False if hash matches last seen (skip duplicate)
        """
        is_new = current_hash != self.last_hash
        return is_new

    def save_hash(self, new_hash: str) -> bool:
        """
        Persist new hash on startup for next restart.

        Args:
            new_hash: SHA256 hash to save

        Returns:
            True on success, False on failure
        """
        payload = {
            'hash': new_hash,
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'bot_id': self.bot_id
        }
        success = atomic_write_json(self.hash_file, payload)
        if success:
            self.last_hash = new_hash
        return success

    def __repr__(self) -> str:
        """String representation for debugging."""
        return f"SignalDeduplicator(bot={self.bot_id}, last_hash={self.last_hash[:8] if self.last_hash else 'NONE'})"
