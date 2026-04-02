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
MAX_SIGNAL_AGE = 1800  # Only OPEN fresh signals < 30 min old. Already-open trades stay open until website closes them

# ─── TRADING ────────────────────────────────────────────────────────────────
TRADE_VOLUME = 0.01    # Lot size (REDUCE if "No money" errors occur)

# ─── SIGNAL INVERSION MODE ──────────────────────────────────────────────────
REVERSE_MODE = True   # If True: BUY→SELL, SELL→BUY, TP↔SL swap

MT5_LOGIN = 24647005
MT5_PASSWORD = "v8O^%6sJ"
MT5_SERVER = "VantageInternational-Demo"
MT5_EXE    = r"C:\Users\h\Desktop\MetaTrader 5\terminal64.exe" 