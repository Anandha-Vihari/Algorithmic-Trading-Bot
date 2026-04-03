# ═══════════════════════════════════════════════════════════════════════════════
# BOT 1 CONFIG - SIGNAL INVERTER (13:00-17:00 IST)
# ═══════════════════════════════════════════════════════════════════════════════

from config import *  # Import all shared configuration

# ─── BOT IDENTITY ──────────────────────────────────────────────────────────
BOT_ID = 1
BOT_NAME = "BOT-INVERTER"

# ─── TRADING PARAMETERS ───────────────────────────────────────────────────
TRADE_VOLUME = 0.01

# ─── MT5 CREDENTIALS ───────────────────────────────────────────────────────
MT5_LOGIN = 24446623
MT5_PASSWORD = "Z2Nf&3eE"

# ─── SIGNAL INVERSION (BOT 1 ONLY) ────────────────────────────────────────
# Reverses signals during specific IST time window
# IST = UTC + 5:30, so 13:00 IST = 07:30 UTC, 17:00 IST = 11:30 UTC
USE_SIGNAL_INVERTER = True
FOLLOW_HOURS_IST_START = 13  # 13:00 IST (07:30 UTC)
FOLLOW_HOURS_IST_END = 17    # 17:00 IST (11:30 UTC)

# ─── STRATEGY SELECTION ────────────────────────────────────────────────────
# Strategy determines signal transformation and risk management
# Options: "mirror", "reverse", "time_based_hybrid"
STRATEGY = "mirror"  # Bot 1: Use mirror strategy (original signals + trailing + max loss)
