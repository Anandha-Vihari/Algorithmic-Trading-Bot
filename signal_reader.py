"""
SIGNAL READER v2 - Safe IPC Read with Hash Deduplication and Backup Fallback

Enhanced signal reader with:
- Primary + backup file reading
- Hash-based deduplication checks
- Dynamic stale data detection
- Version tracking
"""

import json
import time
from datetime import datetime, timezone
from signal_manager import Signal
from atomic_io import safe_read_json
from signal_deduplicator import SignalDeduplicator
from config import SIGNAL_FETCHER_INTERVAL


class SignalReader:
    """Read signals.json with hash deduplication and backup fallback."""

    MAX_RETRIES = 3
    RETRY_DELAY = 0.1  # seconds
    PRIMARY_FILE = "signals.json"
    BACKUP_FILE = "signals_backup.json"

    def __init__(self, bot_id: int):
        """
        Initialize signal reader for a bot.

        Args:
            bot_id: Bot identifier (1, 2, or 3)
        """
        self.bot_id = bot_id
        self.last_version_seen = -1
        self.deduplicator = SignalDeduplicator(bot_id)
        # Dynamic stale threshold: 2 * SIGNAL_FETCHER_INTERVAL
        self.max_age_seconds = 2 * SIGNAL_FETCHER_INTERVAL
        print(f"[READER_BOT{bot_id}] Initialized (stale threshold={self.max_age_seconds}s)")

    def read_signals_safe(self):
        """
        Read signals.json with redundancy and deduplication.

        Process:
        1. Try primary signals.json
        2. If failed, fallback to signals_backup.json
        3. If both failed, skip cycle
        4. Validate hash (Layer 1 deduplication)
        5. Check stale age
        6. Convert JSON back to Signal objects

        Returns:
            (signals_list, version, is_new) on success
            (None, -1, False) on failure/stale/duplicate
        """
        data = self._read_signals_with_fallback()

        if data is None:
            return None, -1, False

        # Validate structure
        if not isinstance(data, dict) or 'version' not in data:
            print(f"[READER_BOT{self.bot_id}] Invalid signals structure")
            return None, -1, False

        version = data['version']
        status = data.get('status', 'UNKNOWN')
        timestamp_str = data.get('timestamp', '')
        content_hash = data.get('hash', '')

        # Check status (allow processing even if ERROR, but log warning)
        if status != "OK":
            print(f"[READER_BOT{self.bot_id}] WARNING: Signal status is {status}")

        # ──── LAYER 1: Hash-based deduplication ────────────────────────────
        if not content_hash:
            print(f"[READER_BOT{self.bot_id}] ERROR: Missing hash in signals")
            return None, -1, False

        # Check if hash is new (deduplicator layer)
        if not self.deduplicator.should_process(content_hash):
            print(f"[READER_BOT{self.bot_id}] [SKIP] Hash unchanged: {content_hash[:8]}")
            return None, version, False

        # ──── Check stale: Skip if data > max_age_seconds old ────────────────
        if timestamp_str:
            try:
                signal_time = datetime.fromisoformat(timestamp_str)
                age_seconds = (datetime.now(timezone.utc) - signal_time).total_seconds()

                if age_seconds > self.max_age_seconds:
                    print(f"[READER_BOT{self.bot_id}] [STALE] {age_seconds:.1f}s > {self.max_age_seconds}s")
                    return None, version, False

            except Exception as e:
                print(f"[READER_BOT{self.bot_id}] ERROR: Failed to parse timestamp: {e}")

        # ──── Check version: Skip if version unchanged ──────────────────────
        is_new = version > self.last_version_seen
        if not is_new:
            print(f"[READER_BOT{self.bot_id}] [SKIP] Version unchanged: {version}")
            return None, version, False

        # ──── Parse signals back to Signal objects ─────────────────────────
        signals = self._parse_signals_from_json(data.get('signals', []))

        if not signals:
            print(f"[READER_BOT{self.bot_id}] No valid signals after parsing")
            return None, version, False

        # ──── Success: Update tracking, save hash ──────────────────────────
        self.last_version_seen = version
        self.deduplicator.save_hash(content_hash)

        # Log health
        print(f"[HEALTH] bot={self.bot_id} version={version} hash={content_hash[:8]} signals={len(signals)}")

        return signals, version, True

    def _read_signals_with_fallback(self) -> dict:
        """
        Try to read signals.json, fallback to backup if needed.

        Process:
        1. Try primary file (with retries)
        2. If failed, try backup file (with retries)
        3. If both failed, return None

        Returns:
            dict on success, None on failure
        """
        # Try primary file
        data = safe_read_json(self.PRIMARY_FILE, max_retries=self.MAX_RETRIES, retry_delay=self.RETRY_DELAY)

        if data is not None:
            return data

        # Primary failed, try backup
        print(f"[READER_BOT{self.bot_id}] Primary read failed, trying backup...")
        data = safe_read_json(self.BACKUP_FILE, max_retries=self.MAX_RETRIES, retry_delay=self.RETRY_DELAY)

        if data is not None:
            print(f"[READER_BOT{self.bot_id}] Backup read successful")
            return data

        # Both failed
        print(f"[READER_BOT{self.bot_id}] ERROR: Both primary and backup read failed")
        return None

    def _parse_signals_from_json(self, signals_json: list) -> list:
        """
        Convert JSON signals back to Signal objects.

        Args:
            signals_json: List of signal dicts from JSON

        Returns:
            List of Signal objects
        """
        signals = []

        for sig_dict in signals_json:
            try:
                sig = Signal(
                    pair=sig_dict['pair'],
                    side=sig_dict['side'],
                    open_price=sig_dict['open_price'],
                    tp=sig_dict['tp'],
                    sl=sig_dict['sl'],
                    time=datetime.fromisoformat(sig_dict['time']),
                    frame=sig_dict['frame'],
                    status=sig_dict['status'],
                    close_price=sig_dict.get('close_price'),
                    close_reason=sig_dict.get('close_reason')
                )
                signals.append(sig)

            except Exception as e:
                print(f"[READER_BOT{self.bot_id}] WARN: Skipping malformed signal: {e}")

        return signals

    def __repr__(self) -> str:
        """String representation for debugging."""
        return (f"SignalReader(bot={self.bot_id}, "
                f"version={self.last_version_seen}, "
                f"hash={self.deduplicator.last_hash[:8] if self.deduplicator.last_hash else 'NONE'})")
