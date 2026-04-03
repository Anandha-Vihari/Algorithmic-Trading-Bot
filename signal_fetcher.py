"""
SIGNAL FETCHER v2 - Central Signal Distribution with Redundancy

Enhanced signal fetcher with:
- SHA256 content hashing for deduplication
- Backup signal file (signals_backup.json)
- Health logging
- Atomic writes via atomic_io
"""

import sys
import json
import time
import shutil
from datetime import datetime, timezone

# Redirect stdout to log file
sys.stdout = open("signal_fetcher.log", "a", buffering=1, encoding="utf-8")
sys.stderr = sys.stdout

# Import signal fetching logic
from scraper import fetch_page
from parser import parse_signals
from atomic_io import atomic_write_json, safe_read_json
from signal_deduplicator import SignalDeduplicator

# Configuration
SIGNAL_FETCHER_INTERVAL = 10  # seconds
MAX_RETRIES = 3
SIGNALS_FILE = "signals.json"
SIGNALS_BACKUP_FILE = "signals_backup.json"


def log(message: str):
    """Log message with timestamp."""
    now = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
    print(f"[{now}] {message}")


def load_current_version() -> int:
    """
    Load current version from signals.json.

    Returns:
        Current version (int) if file exists and valid
        0 if file doesn't exist or invalid
    """
    try:
        data = safe_read_json(SIGNALS_FILE)
        if data:
            return int(data.get('version', 0))
    except:
        pass
    return 0


def convert_signals_to_json(signals: list) -> list:
    """
    Convert parser signals to JSON-serializable format.

    Args:
        signals: List of Signal dicts from parser.parse_signals()

    Returns:
        List of dicts ready for JSON serialization
    """
    json_signals = []
    for sig in signals:
        json_signals.append({
            "pair": sig["pair"],
            "side": sig["side"],
            "open_price": sig["open"],
            "tp": sig["tp"],
            "sl": sig["sl"],
            "time": sig["time"].isoformat(),
            "frame": sig["frame"],
            "status": sig["status"],
            "close_price": sig["close"],
            "close_reason": sig["close_reason"]
        })
    return json_signals


def create_payload(version: int, signals: list, error: str = None) -> dict:
    """
    Create versioned signal payload with hash and metadata.

    Args:
        version: Version number
        signals: List of signal dicts
        error: Optional error message (sets status to ERROR)

    Returns:
        Complete payload dict ready for JSON write
    """
    # Compute content hash
    content_hash = SignalDeduplicator.compute_hash(signals)

    payload = {
        "version": version,
        "hash": content_hash,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": "ERROR" if error else "OK",
        "signals": signals,
        "_meta": {
            "count": len(signals),
            "error": error
        }
    }

    return payload


def write_signals_atomically(version: int, signals: list) -> bool:
    """
    Write signals.json atomically with backup.

    Process:
    1. Create payload
    2. Write atomically to signals.json
    3. Create backup copy
    4. Log health

    Args:
        version: Version number
        signals: List of signal dicts

    Returns:
        True on success, False on failure
    """
    payload = create_payload(version, signals)
    content_hash = payload['hash']

    # Atomic write to primary file
    success = atomic_write_json(SIGNALS_FILE, payload)

    if success:
        # Create backup copy
        try:
            shutil.copy(SIGNALS_FILE, SIGNALS_BACKUP_FILE)
        except Exception as e:
            log(f"[WARNING] Failed to create backup: {e}")

        # Health logging
        log(f"✓ v{version} hash={content_hash[:8]} count={len(signals)}")
        return True
    else:
        log("✗ Atomic write failed, keeping previous signals.json")
        return False


def fetch_and_publish_signals():
    """
    Main fetcher loop: fetch signals and publish to file.

    Fetches every 10 seconds. Never crashes - errors are logged and retried.
    """
    log(f"{'='*80}")
    log("SIGNAL FETCHER v2 - Multi-Algo Distribution System")
    log(f"Interval: {SIGNAL_FETCHER_INTERVAL}s | Primary: {SIGNALS_FILE} | Backup: {SIGNALS_BACKUP_FILE}")
    log(f"{'='*80}\n")

    cycle_count = 0

    while True:
        cycle_count += 1
        now_str = datetime.now(timezone.utc).strftime('%H:%M:%S UTC')

        try:
            # Load current version
            current_version = load_current_version()
            next_version = current_version + 1

            # Fetch website
            log(f"Cycle {cycle_count}: Fetching website...")
            html = fetch_page()

            if html is None:
                log("  ✗ Fetch failed - keeping previous signals")
                # Don't update version, will retry next cycle

            else:
                # Parse signals
                try:
                    signals = parse_signals(html)
                    log(f"  ✓ Parsed {len(signals)} raw signals")

                    if signals:
                        # Convert to JSON format
                        signals_json = convert_signals_to_json(signals)

                        # Write atomically with backup
                        write_signals_atomically(next_version, signals_json)

                    else:
                        log("  [WARNING] Empty signal list from parser")

                except Exception as e:
                    log(f"  ✗ Parse error: {e}")

        except Exception as e:
            log(f"✗ CRITICAL: {e}")
            # Log but don't crash - continue next cycle

        # Wait for next cycle
        log(f"  → Sleeping {SIGNAL_FETCHER_INTERVAL}s...\n")
        time.sleep(SIGNAL_FETCHER_INTERVAL)


if __name__ == "__main__":
    try:
        fetch_and_publish_signals()
    except KeyboardInterrupt:
        log("Signal fetcher stopped by user (Ctrl+C)")
        sys.exit(0)
    except Exception as e:
        log(f"FATAL ERROR: {e}")
        time.sleep(1)
        sys.exit(1)
