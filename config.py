# ═══════════════════════════════════════════════════════════════════════════════
# BLIND FOLLOWER - MINIMAL CONFIG
# ═══════════════════════════════════════════════════════════════════════════════

URL = "http://massyart.com/ringsignal/"

# ─── PROXIES ────────────────────────────────────────────────────────────────
PROXY_API_URL = "https://api.proxyscrape.com/v4/free-proxy-list/get?request=display_proxies&proxy_format=protocolipport&format=text"
PROXY_CACHE_SECONDS = 300
PROXY_ROTATION_STRATEGY = "round_robin"

# ─── TIMING ────────────────────────────────────────────────────────────────
SIGNAL_INTERVAL = 7   # Check website every 7 seconds

# ─── TRADING ────────────────────────────────────────────────────────────────
TRADE_VOLUME = 0.01    # Lot size
MAX_POSITIONS = 10     # Max concurrent positions

# ─── MT5 ────────────────────────────────────────────────────────────────────

MT5_LOGIN = 24446623
MT5_PASSWORD = "Z2Nf&3eE"
MT5_SERVER = "VantageInternational-Demo"
MT5_EXE    = r"C:\Program Files\MetaTrader 5\terminal64.exe" 