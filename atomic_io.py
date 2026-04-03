"""
ATOMIC IO - Safe JSON read/write operations

Provides reusable atomic JSON I/O for all state files across the system.
Ensures data consistency and fault tolerance.
"""

import json
import tempfile
import os
import time
from datetime import datetime, timezone


def atomic_write_json(filepath: str, data: dict, indent: int = 2) -> bool:
    """
    Write JSON atomically using temp file + os.replace().

    Ensures that file is never partially written:
    1. Write to temp file
    2. fsync to disk
    3. Atomic rename (os.replace is atomic on POSIX + Windows)
    4. On failure, temp file is cleaned up

    Args:
        filepath: Target file path
        data: Dictionary to serialize
        indent: JSON indentation level

    Returns:
        True on success, False on failure
    """
    temp_fd = None
    temp_path = None

    try:
        # Create temp file in same directory (atomic rename requirement)
        temp_fd, temp_path = tempfile.mkstemp(suffix='.json', dir=os.path.dirname(filepath) or '.')

        # Write JSON to temp file
        with os.fdopen(temp_fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=indent)
            f.flush()
            os.fsync(f.fileno())

        # Atomic rename (temp → target)
        os.replace(temp_path, filepath)
        return True

    except Exception as e:
        # Cleanup on failure
        if temp_path and os.path.exists(temp_path):
            try:
                os.unlink(temp_path)
            except:
                pass
        print(f"[ERROR] Atomic write failed for {filepath}: {e}")
        return False


def safe_read_json(filepath: str, max_retries: int = 3, retry_delay: float = 0.1) -> dict:
    """
    Read JSON with retry logic on decode errors.

    Handles:
    - JSON decode errors (corrupted file, mid-write reads)
    - File not found (returns None)
    - Other I/O errors

    Args:
        filepath: File to read
        max_retries: Number of retry attempts
        retry_delay: Delay between retries (seconds)

    Returns:
        dict on success, None on failure (after retries exhausted)
    """
    last_error = None

    for attempt in range(max_retries):
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                return json.load(f)

        except FileNotFoundError:
            # File doesn't exist - not an error, just None
            return None

        except json.JSONDecodeError as e:
            # Corrupted JSON - retry
            last_error = e
            if attempt < max_retries - 1:
                time.sleep(retry_delay)

        except Exception as e:
            # Other errors - retry
            last_error = e
            if attempt < max_retries - 1:
                time.sleep(retry_delay)

    # All retries exhausted
    if last_error:
        print(f"[ERROR] Failed to read {filepath} after {max_retries} attempts: {last_error}")

    return None


def atomic_update_json(filepath: str, update_func, max_retries: int = 3) -> bool:
    """
    Atomically update a JSON file with a function.

    Reads current file, applies update function, writes back.
    Useful for appending to or modifying existing JSON data.

    Args:
        filepath: File to update
        update_func: Function(data) -> updated_data
        max_retries: Retry attempts

    Returns:
        True on success, False on failure
    """
    # Try to load existing data
    data = safe_read_json(filepath, max_retries=max_retries)
    if data is None:
        data = {}

    # Apply update
    try:
        updated_data = update_func(data)
    except Exception as e:
        print(f"[ERROR] Update function failed: {e}")
        return False

    # Write atomically
    return atomic_write_json(filepath, updated_data)


def ensure_json_dir(filepath: str):
    """Ensure directory exists for a file path."""
    dirpath = os.path.dirname(filepath)
    if dirpath and not os.path.exists(dirpath):
        os.makedirs(dirpath, exist_ok=True)
