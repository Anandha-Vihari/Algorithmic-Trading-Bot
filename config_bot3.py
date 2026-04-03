# ═══════════════════════════════════════════════════════════════════════════════
# BOT 3 CONFIG - FOLLOWER (NO INVERSION)
# ═══════════════════════════════════════════════════════════════════════════════

from config import *  # Import all shared configuration

# ─── BOT IDENTITY ──────────────────────────────────────────────────────────
BOT_ID = 3
BOT_NAME = "BOT-FOLLOWER"

# ─── TRADING PARAMETERS ───────────────────────────────────────────────────
TRADE_VOLUME = 0.015

# ─── MT5 CREDENTIALS ───────────────────────────────────────────────────────
MT5_LOGIN = 24446625
MT5_PASSWORD = "PLACEHOLDER_PASSWORD_BOT3"

# ─── SIGNAL INVERSION (DISABLED FOR BOT 3) ────────────────────────────────
USE_SIGNAL_INVERTER = False

# ─── STRATEGY SELECTION ────────────────────────────────────────────────────
# Strategy determines signal transformation and risk management
# Options: "mirror", "reverse", "time_based_hybrid"
STRATEGY = "mirror"  # Bot 3: Use mirror strategy (original signals + trailing + max loss)

