"""
test_reverse_all.py
───────────────────
One-shot script: scrapes the signal page right now and opens a reversed
trade for every ACTIVE signal found, regardless of confluence.

Uses the same open_trade() logic as the main bot, so REVERSE_SIGNALS,
REVERSE_RR, SL/TP calculation, R:R check, and duplicate guards all apply.

Run:
    python test_reverse_all.py
"""

from scraper import fetch_page
from parser  import parse_signals
from trader  import init_mt5, open_trade
import MetaTrader5 as mt5

# ── connect ──────────────────────────────────────────────────────────────────
init_mt5()

# ── fetch & parse ─────────────────────────────────────────────────────────────
print("Fetching signals...")
html    = fetch_page()
signals = parse_signals(html)

active = [s for s in signals if s["status"] == "ACTIVE"]

if not active:
    print("No ACTIVE signals found on the page right now.")
    mt5.shutdown()
    exit()

print(f"Found {len(active)} active signal(s):\n")
for s in active:
    print(f"  {s['pair']:<10} {s['side']:<4} [{s['frame']}]"
          f"  open={s['open']}  tp={s['tp']}  sl={s['sl']}")

print()

# ── open reversed trades ──────────────────────────────────────────────────────
ok  = []
skipped = []

for s in active:
    print(f"-- {s['pair']} [{s['frame']}] signal={s['side']} --")
    result = open_trade(s)
    if result:
        ok.append(s)
    else:
        skipped.append(s)
    print()

# ── summary ──────────────────────────────────────────────────────────────────
print("=" * 44)
print(f"  Total signals : {len(active)}")
print(f"  Opened        : {len(ok)}")
print(f"  Skipped/failed: {len(skipped)}")
print("=" * 44)

mt5.shutdown()
