"""
BLIND FOLLOWER BOT - Ultra Simple Version

Just fetches signals and opens/closes trades exactly as website says.
No intelligence, no fancy risk management, no complexity.

CORE BEHAVIORS:
1. Most recent signal only (per pair+frame)
2. Frame lock (first-come-first-served)
3. MT5 duplicate prevention (check before opening)
4. Proper signal processing order
5. Frame-matched close only
6. State file pruning at startup
"""

import time
import sys
import threading
import MetaTrader5 as mt5
import json
import os
from datetime import datetime, timezone, timedelta

# Log to file
sys.stdout = open("bot.log", "a", buffering=1, encoding="utf-8")
sys.stderr = sys.stdout

from scraper import fetch_page
from parser import parse_signals
from trader import open_trade, close_trade, get_position, init_mt5, show_open_positions, account_summary
from state import processed_signals
from config import SIGNAL_INTERVAL, MAX_POSITIONS, TRADE_VOLUME

print(f"\n{'='*80}")
print("BLIND FOLLOWER BOT - STARTED")
print(f"Signal interval: {SIGNAL_INTERVAL}s | Max positions: {MAX_POSITIONS} | Volume: {TRADE_VOLUME}")
print(f"{'='*80}\n")

# Prune old signals at startup
def prune_signals(filepath, hours=24):
    """Delete processed signals older than N hours."""
    try:
        with open(filepath, 'r') as f:
            data = json.load(f)
        cutoff = datetime.utcnow() - timedelta(hours=hours)
        pruned = {
            k: v for k, v in data.items()
            if datetime.fromisoformat(v) > cutoff
        }
        with open(filepath, 'w') as f:
            json.dump(pruned, f)
        removed = len(data) - len(pruned)
        if removed > 0:
            print(f"[STARTUP] Pruned {removed} old signals from state (>24h)")
    except FileNotFoundError:
        pass

prune_signals('processed_signals.json', hours=24)

init_mt5()

# Track which frame is active per pair (frame lock)
active_frame = {}

# ══════════════════════════════════════════════════════════════════════════════
# MAIN SIGNAL LOOP
# ══════════════════════════════════════════════════════════════════════════════

def run_signal_cycle():
    """
    Fetch signals and open/close trades with proper deduplication and frame locking.

    Order:
    1. Fetch HTML via proxy
    2. Parse all signals
    3. Sort by timestamp DESC, deduplicate per pair+frame (keep most recent only)
    4. Process ACTIVE signals (with frame lock + MT5 duplicate check)
    5. Process CLOSE signals (frame-matched only)
    6. Log status + sleep
    """

    global active_frame
    now = datetime.now(timezone.utc)

    # ──── FETCH & PARSE SIGNALS ──────────────────────────────────────────────

    html = fetch_page()
    if html is None:
        print(f"[{now.strftime('%H:%M:%S')}] WARNING: Could not fetch signals (proxy failed)")
        return

    signals = parse_signals(html)
    if not signals:
        return

    # ──── SORT & DEDUPLICATE: Most recent signal only per pair+frame ─────────

    signals.sort(key=lambda x: x['time'], reverse=True)
    seen = set()
    filtered_signals = []

    for s in signals:
        key = f"{s['pair']}_{s['frame']}"
        if key not in seen:
            seen.add(key)
            filtered_signals.append(s)

    signals = filtered_signals

    # ──── PROCESS ACTIVE SIGNALS (with frame lock + MT5 check) ──────────────

    opened = 0
    for s in signals:
        if s["status"] != "ACTIVE":
            continue

        pair = s["pair"]
        frame = s["frame"]
        signal_id = f"{pair}_{s['time']}_{s['side']}_{frame}"

        # Skip if already processed
        if signal_id in processed_signals:
            continue

        # Frame lock: if this pair has a different frame active, skip
        if pair in active_frame and active_frame[pair] != frame:
            continue

        # MT5 duplicate prevention: check if position already exists
        if get_position(pair):
            processed_signals[signal_id] = now
            continue

        # Check position cap
        open_count = len(mt5.positions_get() or [])
        if open_count >= MAX_POSITIONS:
            print(f"[{now.strftime('%H:%M:%S')}] Position cap ({MAX_POSITIONS}) reached. Skipping {pair}")
            processed_signals[signal_id] = now
            continue

        # Open trade
        print(f"[{now.strftime('%H:%M:%S')}] SIGNAL: {pair} {s['side']} @ {s['open']} SL:{s['sl']} TP:{s['tp']}")

        if open_trade(s):
            opened += 1
            active_frame[pair] = frame  # Lock this frame for this pair
            print(f"  → OPENED ✓")

        processed_signals[signal_id] = now

    # ──── PROCESS CLOSE SIGNALS (frame-matched only) ───────────────────────

    closed = 0
    for s in signals:
        if s["status"] != "CLOSE":
            continue

        pair = s["pair"]
        frame = s["frame"]

        # Only close if frame matches
        if pair in active_frame and active_frame[pair] != frame:
            continue

        pos = get_position(pair)

        if pos:
            print(f"[{now.strftime('%H:%M:%S')}] CLOSE: {pair} (website signal)")
            close_trade(pair)
            closed += 1
            if pair in active_frame:
                del active_frame[pair]  # Unlock pair
            print(f"  → CLOSED ✓")

    # ──── STATUS ──────────────────────────────────────────────────────────────

    print(f"[{now.strftime('%H:%M:%S')}] Status: {opened} opened, {closed} closed")
    show_open_positions()
    account_summary()


def signal_thread():
    """Main loop: fetch signals every N seconds."""
    while True:
        try:
            run_signal_cycle()
        except Exception as e:
            print(f"ERROR: {e}")

        time.sleep(SIGNAL_INTERVAL)


# ══════════════════════════════════════════════════════════════════════════════
# START
# ══════════════════════════════════════════════════════════════════════════════

threading.Thread(target=signal_thread, daemon=True).start()

# Keep main thread alive
while True:
    time.sleep(60)
