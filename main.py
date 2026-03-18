"""
BLIND FOLLOWER BOT - Ultra Simple Version

Just fetches signals and opens/closes trades exactly as website says.
No intelligence, no fancy risk management, no complexity.
"""

import time
import sys
import threading
import MetaTrader5 as mt5
from datetime import datetime, timezone

# Log to file
sys.stdout = open("bot.log", "a", buffering=1, encoding="utf-8")
sys.stderr = sys.stdout

from scraper import fetch_page
from parser import parse_signals
from trader import open_trade, close_trade, get_position, init_mt5, show_open_positions, account_summary
from state import processed_signals
from config import SIGNAL_INTERVAL, MAX_POSITIONS, TRADE_VOLUME, DOLLAR_STOP_LOSS

print(f"\n{'='*80}")
print("BLIND FOLLOWER BOT - STARTED")
print(f"Signal interval: {SIGNAL_INTERVAL}s | Max positions: {MAX_POSITIONS} | Volume: {TRADE_VOLUME}")
print(f"{'='*80}\n")

init_mt5()

# ══════════════════════════════════════════════════════════════════════════════
# MAIN SIGNAL LOOP
# ══════════════════════════════════════════════════════════════════════════════

def run_signal_cycle():
    """Fetch signals and open/close trades. That's it."""

    now = datetime.now(timezone.utc)

    # ─────────────────────────────────────────────────────────────────────────
    # FETCH & PARSE SIGNALS
    # ─────────────────────────────────────────────────────────────────────────

    html = fetch_page()
    if html is None:
        print(f"[{now.strftime('%H:%M:%S')}] WARNING: Could not fetch signals (proxy failed)")
        return

    signals = parse_signals(html)

    # ─────────────────────────────────────────────────────────────────────────
    # PROCESS ACTIVE SIGNALS
    # ─────────────────────────────────────────────────────────────────────────

    opened = 0
    for s in signals:
        if s["status"] != "ACTIVE":
            continue

        pair = s["pair"]
        signal_id = f"{pair}_{s['time']}_{s['side']}_{s['frame']}"

        # Skip if already processed
        if signal_id in processed_signals:
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
            print(f"  → OPENED ✓")

        processed_signals[signal_id] = now

    # ─────────────────────────────────────────────────────────────────────────
    # PROCESS CLOSE SIGNALS
    # ─────────────────────────────────────────────────────────────────────────

    closed = 0
    for s in signals:
        if s["status"] != "CLOSE":
            continue

        pair = s["pair"]
        pos = get_position(pair)

        if pos:
            print(f"[{now.strftime('%H:%M:%S')}] CLOSE: {pair} (website signal)")
            close_trade(pair)
            closed += 1
            print(f"  → CLOSED ✓")

    # ─────────────────────────────────────────────────────────────────────────
    # STATUS
    # ─────────────────────────────────────────────────────────────────────────

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
