URL = "https://massyart.com/ringsignal/"

SIGNAL_INTERVAL   = 66  # seconds between website signal checks
POSITION_INTERVAL = 5   # seconds between full trail/breakeven checks
GUARD_INTERVAL    = 1   # seconds between profit-guard checks (watches every second)

TRADE_VOLUME     = 0.01
MAX_POSITIONS    = 10     # max concurrent bot positions
TRADE_FRAME      = "both"  # "short" = 15/30 min chart only, "long" = 1/4 hour only, "both" = all
REVERSE_SIGNALS       = True    # True → trade opposite to signal (BUY->SELL, SELL->BUY)
REVERSE_RR            = 2.0     # take-profit ratio for reversed trades (2 = 2:1 R:R)
REVERSE_BROKER_SL_USD = 1.20    # broker-side emergency SL in dollars (fires if bot goes offline)
MAGIC_SHORT = 777   # magic number for short-frame (15/30 min) positions
MAGIC_LONG  = 778   # magic number for long-frame  (1/4 hour)  positions

# pairs to never trade — signal source is accurate on these so reversal loses
PAIR_BLACKLIST = {"EURUSD", "EURGBP", "EURCAD", "EURJPY", "EURCHF", "EURNZD", "EURAUD"}

DOLLAR_STOP_LOSS = 0.60   # close immediately if floating loss exceeds this amount ($)
# stepped profit lock: $0.30→entry, $0.60→lock$0.30, $0.90→lock$0.60 (hardcoded in active_brain)

MIN_RR_RATIO    = 1.0   # skip entry if TP distance < this × SL distance from current price
MAX_SPREAD_PIPS = 5.0   # skip entry if spread exceeds this many pips
DAILY_MAX_LOSS  = 5.00  # circuit breaker: stop opening new trades if daily closed loss hits this ($)
SHORT_MAX_HOURS = 4     # close short-frame losing positions after 4 hours
LONG_MAX_HOURS  = 24    # close long-frame  losing positions after 24 hours

# ── Active Trade Brain ────────────────────────────────────────────────────────
BRAIN_ENABLED         = True
BRAIN_DEAD_MINS       = 90     # close if profit never reached BRAIN_DEAD_MIN after this many minutes
BRAIN_DEAD_MIN_PROFIT = 0.05   # minimum peak profit ($) to consider a trade "alive"
BRAIN_EMERGENCY_TRAIL = 0.15   # SL distance as fraction of TP when momentum crashes (-2 score)
BRAIN_TP_EXTEND_PCT   = 0.80   # extend TP when price reaches 80% of original TP distance
BRAIN_TP_EXTEND_MULT  = 1.5    # new TP = original TP + 50% extra distance

PROFIT_GUARD_ENABLED   = True   # rapid-drop / floor / retain protection
PROFIT_GUARD_MIN      = 0.20  # $ profit must first reach this before guard watches
PROFIT_GUARD_RETAIN   = 0.40  # fallback: close if profit drops below 40% of peak
PROFIT_GUARD_FLOOR    = 0.04  # absolute floor: close if profit falls to $0.04 once $0.20 was hit
PROFIT_GUARD_DROP_USD = 0.08  # rapid-reversal: profit dropped this much in DROP_SECS → massive loss
PROFIT_GUARD_DROP_SECS = 8    # time window (seconds) for rapid-drop measurement

MT5_LOGIN = 24343206
MT5_PASSWORD = "oiAZ!5s6"
MT5_SERVER = "VantageInternational-Demo"
MT5_EXE    = r"C:\Users\h\AppData\Roaming\MetaTrader 5\terminal64.exe"