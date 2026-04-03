# ═══════════════════════════════════════════════════════════════════════════════
# BOT 2 CONFIG - FOLLOWER (NO INVERSION)
# ═══════════════════════════════════════════════════════════════════════════════

from config import *  # Import all shared configuration

# ─── BOT IDENTITY ──────────────────────────────────────────────────────────
BOT_ID = 2
BOT_NAME = "BOT-FOLLOWER"

# ─── TRADING PARAMETERS ───────────────────────────────────────────────────
TRADE_VOLUME = 0.02

# ─── MT5 CREDENTIALS ───────────────────────────────────────────────────────
MT5_LOGIN = 24446624
MT5_PASSWORD = "PLACEHOLDER_PASSWORD_BOT2"

# ─── SIGNAL INVERSION (DISABLED FOR BOT 2) ────────────────────────────────
USE_SIGNAL_INVERTER = False

# ─── STRATEGY SELECTION ────────────────────────────────────────────────────
# Strategy determines signal transformation and risk management
# Options: "mirror", "reverse", "time_based_hybrid"
STRATEGY = "mirror"  # Bot 2: Use mirror strategy (original signals + trailing + max loss)

