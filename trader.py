import time
import subprocess
import MetaTrader5 as mt5
from collections import deque
from datetime import datetime, timedelta, timezone
from config import *
from slog import slog

MAGIC_BY_FRAME = {"short": MAGIC_SHORT, "long": MAGIC_LONG}

_peak_profit    = {}   # ticket → highest profit (USD) seen while trade was open
_profit_history = {}   # ticket → deque of (timestamp, profit) — rolling window for rapid-drop detection
_partial_closed = set()  # tickets where 50% was already booked
_tp_extended    = set()  # tickets where TP was already pushed out


def init_mt5():

    if not mt5.initialize():
        print("MT5 not running — launching terminal...")
        subprocess.Popen(MT5_EXE, creationflags=subprocess.CREATE_NO_WINDOW)
        time.sleep(10)
        if not mt5.initialize():
            raise RuntimeError("MT5 init failed after launch")

    if not mt5.login(MT5_LOGIN, MT5_PASSWORD, MT5_SERVER):
        raise RuntimeError("MT5 login failed")

    print("MT5 connected")


def open_trade(signal):

    pair  = signal["pair"]
    side  = signal["side"]
    tp    = signal["tp"]
    sl    = signal["sl"]
    magic = MAGIC_BY_FRAME[signal["frame"]]

    # counter-trend mode: flip direction; SL moves to original TP (tight stop).
    # TP is recalculated from price after the tick is fetched (see below).
    if REVERSE_SIGNALS:
        side = "SELL" if side == "BUY" else "BUY"
        sl   = tp   # original TP becomes our stop loss
        tp   = 0    # placeholder — will be set from price × REVERSE_RR below
        print(f"REVERSE: {pair} [{signal['frame']}] signal={signal['side']} -> trading {side}")

    # resolve symbol: try bare name then + suffix, retry up to 3x per name
    sym = None
    for name in (pair, pair + "+"):
        mt5.symbol_select(name, True)
        for _ in range(3):
            time.sleep(0.5)
            info = mt5.symbol_info(name)
            if info is not None and info.trade_mode != 0:
                pair = name
                sym  = info
                break
        if sym is not None:
            break

    if sym is None:
        print("SKIP TRADE: symbol unavailable —", signal["pair"])
        slog(signal["pair"], signal["frame"], "SKIP SYMBOL", "unavailable")
        return False

    # prevent duplicate trades for the same frame
    existing = mt5.positions_get(symbol=pair)
    if existing:
        for p in existing:
            if p.magic == magic:
                print(f"SKIP TRADE: already open for {pair} [{signal['frame']}]")
                return False

    # cap total concurrent bot positions
    all_bot_pos = [p for p in (mt5.positions_get() or [])
                   if p.magic in (MAGIC_SHORT, MAGIC_LONG)]
    if len(all_bot_pos) >= MAX_POSITIONS:
        print(f"SKIP TRADE: position cap ({MAX_POSITIONS}) reached — {pair} [{signal['frame']}]")
        slog(pair, signal["frame"], "SKIP CAP", f"max {MAX_POSITIONS} positions reached")
        return False

    tick = mt5.symbol_info_tick(pair)

    if tick is None:
        print("SKIP TRADE: no tick data for", pair)
        return False

    price = tick.ask if side == "BUY" else tick.bid

    # if price has already moved past the signal's entry (we're entering late),
    # tighten SL to the original entry price so we don't risk more than needed.
    # Skipped for reversed trades — SL is already set to the original TP above.
    if not REVERSE_SIGNALS:
        if side == "BUY" and price > signal["open"]:
            sl = round(signal["open"], sym.digits)
            print(f"LATE ENTRY BUY {pair}: adjusting SL {signal['sl']} -> {sl} (entry price)")
            slog(pair, signal["frame"], "SL ADJUSTED", f"late entry: SL {signal['sl']} -> {sl}")
        elif side == "SELL" and price < signal["open"]:
            sl = round(signal["open"], sym.digits)
            print(f"LATE ENTRY SELL {pair}: adjusting SL {signal['sl']} -> {sl} (entry price)")
            slog(pair, signal["frame"], "SL ADJUSTED", f"late entry: SL {signal['sl']} -> {sl}")
        else:
            sl = signal["sl"]

    # for reversed trades:
    #   SL = original TP price (meaningful market level, already stored in sl)
    #   TP = price ± 2 × (distance to original TP) → clean 2:1 R:R
    if REVERSE_SIGNALS:
        orig_sl_dist = abs(price - sl)   # sl holds original TP price
        if side == "BUY":
            tp = round(price + orig_sl_dist * 2, sym.digits)
            # sl stays as original TP (below entry for BUY ✓)
        else:
            tp = round(price - orig_sl_dist * 2, sym.digits)
            # sl stays as original TP (above entry for SELL ✓)
        sl = round(sl, sym.digits)
        print(f"REVERSE RR: {pair} entry={price}  SL={sl}  TP={tp}  (2:1)")

    # R:R check: reward (TP distance from current price) must be >= MIN_RR_RATIO × risk (SL distance)
    tp_dist_now = abs(tp - price)
    sl_dist_now = abs(price - sl)
    if sl_dist_now > 0:
        rr = tp_dist_now / sl_dist_now
        if rr < MIN_RR_RATIO:
            print(f"SKIP R:R: {pair} R:R={rr:.2f} (need {MIN_RR_RATIO}) — skipping")
            slog(pair, signal["frame"], "SKIP R:R", f"R:R={rr:.2f} < {MIN_RR_RATIO} — not worth entering")
            return True   # mark processed — geometry won't improve

    order_type = mt5.ORDER_TYPE_BUY if side == "BUY" else mt5.ORDER_TYPE_SELL

    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": pair,
        "volume": TRADE_VOLUME,
        "type": order_type,
        "price": price,
        "tp": tp,
        "sl": sl,
        "deviation": 20,
        "magic": magic,
        "comment": signal["frame"],
        "type_filling": mt5.ORDER_FILLING_IOC,
        "type_time": mt5.ORDER_TIME_GTC
    }

    result = mt5.order_send(request)

    if result.retcode == 10009:
        print("OPEN RESULT:", result)
        slog(pair, signal["frame"], "OPENED", f"{side} @ {result.price}")
        return True

    if result.retcode == 10016:
        print(f"SKIP PERMANENT: {pair} [{signal['frame']}] invalid stops — price moved too far, giving up")
        slog(pair, signal["frame"], "SKIP INVALID", "price moved past SL, giving up")
        return True   # mark processed, never retry

    print("OPEN FAILED:", result)
    slog(pair, signal["frame"], "OPEN FAILED", str(result.retcode))
    return False


def close_trade(pair):

    for name in (pair, pair + "+"):
        positions = mt5.positions_get(symbol=name)
        if not positions:
            continue
        for p in positions:
            if p.magic not in (MAGIC_SHORT, MAGIC_LONG):
                continue
            tick = mt5.symbol_info_tick(p.symbol)
            if p.type == mt5.POSITION_TYPE_BUY:
                order_type = mt5.ORDER_TYPE_SELL
                price = tick.bid
            else:
                order_type = mt5.ORDER_TYPE_BUY
                price = tick.ask
            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "position": p.ticket,
                "symbol": p.symbol,
                "volume": p.volume,
                "type": order_type,
                "price": price,
                "deviation": 20,
                "magic": p.magic,
                "type_filling": mt5.ORDER_FILLING_IOC,
                "type_time": mt5.ORDER_TIME_GTC
            }
            result = mt5.order_send(request)
            print("CLOSE RESULT:", result)
            if result.retcode == 10009:
                frame = "short" if p.magic == MAGIC_SHORT else "long"
                slog(p.symbol, frame, "CLOSED", f"@ {result.price}")


def get_position(pair):
    """Return the open bot position for pair (bare or + suffix), or None."""
    for name in (pair, pair + "+"):
        positions = mt5.positions_get(symbol=name)
        if positions:
            for p in positions:
                if p.magic in (MAGIC_SHORT, MAGIC_LONG):
                    return p
    return None


def manage_positions():

    positions = mt5.positions_get()

    if not positions:
        return

    now = datetime.now(timezone.utc)

    for p in positions:

        if p.magic not in (MAGIC_SHORT, MAGIC_LONG):
            continue

        frame = "short" if p.magic == MAGIC_SHORT else "long"

        # track highest profit seen while this position is open
        _peak_profit[p.ticket] = max(_peak_profit.get(p.ticket, p.profit), p.profit)

        if p.tp == 0:
            continue   # no TP set — can't calculate distances

        sym  = mt5.symbol_info(p.symbol)
        tick = mt5.symbol_info_tick(p.symbol)
        if sym is None or tick is None:
            continue

        open_time = datetime.fromtimestamp(p.time, tz=timezone.utc)
        bars = mt5.copy_rates_range(p.symbol, mt5.TIMEFRAME_M1, open_time, now)

        # time-based exit: cut a losing position that has overstayed its signal window
        age_hours = (now - open_time).total_seconds() / 3600
        max_hours = SHORT_MAX_HOURS if frame == "short" else LONG_MAX_HOURS
        if age_hours > max_hours and p.profit < 0:
            print(f"TIME EXIT: {p.symbol} [{frame}] {age_hours:.1f}h, P&L={p.profit:.2f}")
            slog(p.symbol, frame, "TIME EXIT", f"{age_hours:.1f}h old, still losing — closing")
            close_type  = mt5.ORDER_TYPE_SELL if p.type == mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY
            close_price = tick.bid             if p.type == mt5.POSITION_TYPE_BUY else tick.ask
            mt5.order_send({
                "action": mt5.TRADE_ACTION_DEAL,
                "position": p.ticket, "symbol": p.symbol,
                "volume": p.volume, "type": close_type,
                "price": close_price, "deviation": 20,
                "magic": p.magic,
                "type_filling": mt5.ORDER_FILLING_IOC,
                "type_time": mt5.ORDER_TIME_GTC
            })
            continue

        if p.type == mt5.POSITION_TYPE_BUY:

            tp_dist = p.tp - p.price_open
            if tp_dist <= 0:
                continue

            current_price = tick.bid
            profit        = current_price - p.price_open
            peak_price    = float(bars['high'].max()) if bars is not None and len(bars) > 0 else current_price
            peak_move     = peak_price - p.price_open   # how far peak got above open
            cur_sl        = round(p.sl, sym.digits)
            pct           = profit / tp_dist * 100

            # trail: activate once peak has EVER reached TRAIL_START_PCT — keeps SL
            # locked against that peak even if price retreats below the threshold
            if peak_move >= TRAIL_START_PCT * tp_dist:
                # tighten trail when very close to TP to protect near-full profit
                trail_dist = TRAIL_TIGHT_DIST if profit >= TRAIL_TIGHT_PCT * tp_dist else TRAIL_DISTANCE_PCT
                new_sl = round(peak_price - trail_dist * tp_dist, sym.digits)
                if new_sl > cur_sl:
                    result = mt5.order_send({
                        "action": mt5.TRADE_ACTION_SLTP,
                        "position": p.ticket, "symbol": p.symbol,
                        "sl": new_sl, "tp": p.tp
                    })
                    if result.retcode in (10009, 10025):
                        print(f"TRAIL SL:  {p.symbol} -> {new_sl}  (peak={peak_price:.5f}  {pct:.0f}% of TP)")
                        slog(p.symbol, frame, "TRAIL SL", f"SL -> {new_sl} peak={peak_price:.5f} ({pct:.0f}% of TP)")
                    else:
                        print(f"TRAIL SL FAILED: {p.symbol} retcode={result.retcode}")

            elif profit >= BREAKEVEN_PCT * tp_dist:
                new_sl = round(p.price_open, sym.digits)
                if new_sl > cur_sl:
                    result = mt5.order_send({
                        "action": mt5.TRADE_ACTION_SLTP,
                        "position": p.ticket, "symbol": p.symbol,
                        "sl": new_sl, "tp": p.tp
                    })
                    if result.retcode in (10009, 10025):
                        print(f"BREAKEVEN: {p.symbol} SL -> {new_sl}  ({pct:.0f}% of TP)")
                        slog(p.symbol, frame, "BREAKEVEN", f"SL -> {new_sl} ({pct:.0f}% of TP)")
                    else:
                        print(f"BREAKEVEN FAILED: {p.symbol} retcode={result.retcode}")

        else:

            tp_dist = p.price_open - p.tp
            if tp_dist <= 0:
                continue

            current_price = tick.ask
            profit        = p.price_open - current_price
            peak_price    = float(bars['low'].min()) if bars is not None and len(bars) > 0 else current_price
            peak_move     = p.price_open - peak_price   # how far peak dropped below open
            cur_sl        = round(p.sl, sym.digits)
            pct           = profit / tp_dist * 100

            # trail: activate once peak has EVER reached TRAIL_START_PCT
            if peak_move >= TRAIL_START_PCT * tp_dist:
                trail_dist = TRAIL_TIGHT_DIST if profit >= TRAIL_TIGHT_PCT * tp_dist else TRAIL_DISTANCE_PCT
                new_sl = round(peak_price + trail_dist * tp_dist, sym.digits)
                if p.sl == 0 or new_sl < cur_sl:
                    result = mt5.order_send({
                        "action": mt5.TRADE_ACTION_SLTP,
                        "position": p.ticket, "symbol": p.symbol,
                        "sl": new_sl, "tp": p.tp
                    })
                    if result.retcode in (10009, 10025):
                        print(f"TRAIL SL:  {p.symbol} -> {new_sl}  (peak={peak_price:.5f}  {pct:.0f}% of TP)")
                        slog(p.symbol, frame, "TRAIL SL", f"SL -> {new_sl} peak={peak_price:.5f} ({pct:.0f}% of TP)")
                    else:
                        print(f"TRAIL SL FAILED: {p.symbol} retcode={result.retcode}")

            elif profit >= BREAKEVEN_PCT * tp_dist:
                new_sl = round(p.price_open, sym.digits)
                if p.sl == 0 or new_sl < cur_sl:
                    result = mt5.order_send({
                        "action": mt5.TRADE_ACTION_SLTP,
                        "position": p.ticket, "symbol": p.symbol,
                        "sl": new_sl, "tp": p.tp
                    })
                    if result.retcode in (10009, 10025):
                        print(f"BREAKEVEN: {p.symbol} SL -> {new_sl}  ({pct:.0f}% of TP)")
                        slog(p.symbol, frame, "BREAKEVEN", f"SL -> {new_sl} ({pct:.0f}% of TP)")
                    else:
                        print(f"BREAKEVEN FAILED: {p.symbol} retcode={result.retcode}")


def profit_guard():
    """
    Fast profit monitor — runs every second.

    Activates once a position has reached PROFIT_GUARD_MIN ($0.20).
    Three layered checks, any one triggers an immediate close:

      1. RAPID DROP   — profit fell PROFIT_GUARD_DROP_USD or more within
                        PROFIT_GUARD_DROP_SECS seconds.  Catches fast reversals
                        before they wipe out the gain entirely.

      2. FLOOR        — profit fell below PROFIT_GUARD_FLOOR ($0.04 absolute).
                        Prevents a good trade from being held all the way to zero.

      3. RETAIN       — profit is below PROFIT_GUARD_RETAIN (40%) of all-time peak.
                        Catches slow bleeds where velocity alone wouldn't fire.

    Only closes when one of these fires; normal retracements that stay above the
    floor and retain level are left alone so profits keep running.
    """
    positions = mt5.positions_get()
    if not positions or not PROFIT_GUARD_ENABLED:
        return

    now_ts = time.time()

    for p in positions:
        if p.magic not in (MAGIC_SHORT, MAGIC_LONG):
            continue

        frame = "short" if p.magic == MAGIC_SHORT else "long"

        # update peak profit (shared with manage_positions)
        prev_peak = _peak_profit.get(p.ticket, 0)
        peak      = max(prev_peak, p.profit)
        _peak_profit[p.ticket] = peak

        # maintain rolling profit history for this ticket
        hist = _profit_history.setdefault(p.ticket, deque(maxlen=60))
        hist.append((now_ts, p.profit))

        # guard only activates once we've been meaningfully in profit
        if peak < PROFIT_GUARD_MIN:
            continue

        # ── check 1: rapid drop within DROP_SECS window ──────────────────────
        window = [pnl for ts, pnl in hist if now_ts - ts <= PROFIT_GUARD_DROP_SECS]
        rapid_drop = False
        reason     = ""
        if len(window) >= 3:
            drop = max(window) - p.profit
            if drop >= PROFIT_GUARD_DROP_USD:
                rapid_drop = True
                reason = (f"rapid drop ${drop:.2f} in {PROFIT_GUARD_DROP_SECS}s "
                          f"(peak=${peak:.2f} now=${p.profit:.2f})")

        # ── check 2: absolute floor ───────────────────────────────────────────
        at_floor = p.profit < PROFIT_GUARD_FLOOR
        if at_floor and not reason:
            reason = f"below floor ({p.profit:.2f} < {PROFIT_GUARD_FLOOR}) after peak ${peak:.2f}"

        # ── check 3: retain fraction of peak (slow-bleed backstop) ───────────
        retain_target = peak * PROFIT_GUARD_RETAIN
        retain_fail   = p.profit < retain_target
        if retain_fail and not reason:
            reason = (f"retain fail: ${p.profit:.2f} < "
                      f"{PROFIT_GUARD_RETAIN*100:.0f}% of peak ${peak:.2f}")

        if not (rapid_drop or at_floor or retain_fail):
            continue

        # one of the checks fired — close immediately
        print(f"PROFIT GUARD: {p.symbol} [{frame}] {reason} — closing")
        slog(p.symbol, frame, "PROFIT GUARD", reason)

        tick = mt5.symbol_info_tick(p.symbol)
        if tick is None:
            continue

        close_type  = mt5.ORDER_TYPE_SELL if p.type == mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY
        close_price = tick.bid             if p.type == mt5.POSITION_TYPE_BUY else tick.ask

        result = mt5.order_send({
            "action":       mt5.TRADE_ACTION_DEAL,
            "position":     p.ticket,
            "symbol":       p.symbol,
            "volume":       p.volume,
            "type":         close_type,
            "price":        close_price,
            "deviation":    20,
            "magic":        p.magic,
            "type_filling": mt5.ORDER_FILLING_IOC,
            "type_time":    mt5.ORDER_TIME_GTC
        })

        if result.retcode == 10009:
            slog(p.symbol, frame, "CLOSED",
                 f"profit guard @ {result.price}  locked ${p.profit:.2f}")
        else:
            print(f"PROFIT GUARD CLOSE FAILED: {p.symbol} retcode={result.retcode}")


# ── Active Trade Brain ─────────────────────────────────────────────────────────

def _momentum_score(ticket):
    """Returns -2..+2: profit trend over last 30s and 60s. Negative = falling."""
    hist = _profit_history.get(ticket)
    if not hist or len(hist) < 3:
        return 0
    now_ts  = time.time()
    current = hist[-1][1]
    score   = 0
    for window in (30, 60):
        past = next((pnl for ts, pnl in reversed(list(hist)) if now_ts - ts >= window), None)
        if past is not None:
            score += 1 if current > past else (-1 if current < past else 0)
    return score


def _brain_close(p, tick, frame, reason):
    close_type  = mt5.ORDER_TYPE_SELL if p.type == mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY
    close_price = tick.bid             if p.type == mt5.POSITION_TYPE_BUY else tick.ask
    result = mt5.order_send({
        "action":       mt5.TRADE_ACTION_DEAL,
        "position":     p.ticket,
        "symbol":       p.symbol,
        "volume":       p.volume,
        "type":         close_type,
        "price":        close_price,
        "deviation":    20,
        "magic":        p.magic,
        "type_filling": mt5.ORDER_FILLING_IOC,
        "type_time":    mt5.ORDER_TIME_GTC
    })
    if result.retcode == 10009:
        slog(p.symbol, frame, "CLOSED", f"brain {reason} @ {result.price}  pnl=${p.profit:.2f}")
    else:
        print(f"BRAIN CLOSE FAILED: {p.symbol} retcode={result.retcode}")
    return result.retcode == 10009


def _brain_sltp(p, new_sl, new_tp, sym, frame, reason):
    result = mt5.order_send({
        "action":   mt5.TRADE_ACTION_SLTP,
        "position": p.ticket,
        "symbol":   p.symbol,
        "sl":       round(new_sl, sym.digits),
        "tp":       round(new_tp, sym.digits)
    })
    if result.retcode in (10009, 10025):
        print(f"BRAIN: {p.symbol} [{frame}] {reason}")
        slog(p.symbol, frame, "BRAIN", reason)
    else:
        print(f"BRAIN SLTP FAILED: {p.symbol} retcode={result.retcode}")


def active_brain():
    """
    Runs every second. Six behaviours:

    1. DEAD TRADE KILLER  — close if peak never reached $0.05 after 30 min
    2. DOLLAR STOP        — close immediately if floating loss exceeds $0.60
    3. PROFIT LOCK        — move SL to breakeven when floating profit reaches $0.30
    4. PROFIT TRAIL       — trail SL behind price once trade is 30%+ into TP
    5. TP EXTENSION       — push TP 50% further when price is at 80% and still moving
    6. PARTIAL CLOSE      — lock 50% at 60% of TP (only when lot >= 2x broker minimum)
    """
    if not BRAIN_ENABLED:
        return

    positions = mt5.positions_get()
    if not positions:
        return

    now    = datetime.now(timezone.utc)
    now_ts = time.time()

    for p in positions:
        if p.magic not in (MAGIC_SHORT, MAGIC_LONG):
            continue
        if p.tp == 0:
            continue

        frame = "short" if p.magic == MAGIC_SHORT else "long"
        sym   = mt5.symbol_info(p.symbol)
        tick  = mt5.symbol_info_tick(p.symbol)
        if sym is None or tick is None:
            continue

        # update shared state
        hist = _profit_history.setdefault(p.ticket, deque(maxlen=120))
        hist.append((now_ts, p.profit))
        peak = max(_peak_profit.get(p.ticket, p.profit), p.profit)
        _peak_profit[p.ticket] = peak

        age_mins = (now - datetime.fromtimestamp(p.time, tz=timezone.utc)).total_seconds() / 60

        if p.type == mt5.POSITION_TYPE_BUY:
            tp_dist  = p.tp - p.price_open
            cur_move = tick.bid - p.price_open
        else:
            tp_dist  = p.price_open - p.tp
            cur_move = p.price_open - tick.ask

        if tp_dist <= 0:
            continue

        pct = cur_move / tp_dist * 100

        # ── 1. DEAD TRADE KILLER ──────────────────────────────────────────────
        if age_mins >= BRAIN_DEAD_MINS and peak < BRAIN_DEAD_MIN_PROFIT:
            print(f"BRAIN DEAD TRADE: {p.symbol} [{frame}] {age_mins:.0f}min  peak=${peak:.2f}")
            slog(p.symbol, frame, "DEAD TRADE", f"{age_mins:.0f}min open, never profitable — closing")
            _brain_close(p, tick, frame, "dead trade")
            continue

        # ── 2. DOLLAR STOP LOSS ───────────────────────────────────────────────
        # close immediately if floating loss exceeds $0.60 — hard cap per trade
        if p.profit <= -DOLLAR_STOP_LOSS:
            print(f"DOLLAR STOP: {p.symbol} [{frame}] loss=${p.profit:.2f} — closing")
            slog(p.symbol, frame, "DOLLAR STOP", f"loss=${p.profit:.2f} hit -${DOLLAR_STOP_LOSS} cap")
            _brain_close(p, tick, frame, f"dollar stop ${p.profit:.2f}")
            continue

        # ── 3. PROFIT LOCK (SL → breakeven at $0.30 profit) ─────────────────
        # once trade hits +$0.30, slide SL to entry so it can't turn into a loss
        if p.profit >= PROFIT_LOCK_USD:
            be = round(p.price_open, sym.digits)
            if p.type == mt5.POSITION_TYPE_BUY:
                if round(p.sl, sym.digits) < be:
                    _brain_sltp(p, be, p.tp, sym, frame,
                                f"profit lock SL->BE (profit=+${p.profit:.2f})")
            else:
                if p.sl == 0 or round(p.sl, sym.digits) > be:
                    _brain_sltp(p, be, p.tp, sym, frame,
                                f"profit lock SL->BE (profit=+${p.profit:.2f})")

        score = _momentum_score(p.ticket)

        # ── 4. PROFIT PROTECTION TRAIL ────────────────────────────────────────
        # once trade is ≥30% into TP, keep SL trailing behind current price
        if pct >= 30 and p.profit > 0:
            if p.type == mt5.POSITION_TYPE_BUY:
                new_sl    = round(tick.bid - BRAIN_EMERGENCY_TRAIL * tp_dist, sym.digits)
                min_move  = 10 ** (-sym.digits + 1)
                if new_sl > round(p.sl, sym.digits) + min_move:
                    _brain_sltp(p, new_sl, p.tp, sym, frame,
                                f"profit trail SL->{new_sl} ({pct:.0f}% of TP)")
            else:
                new_sl   = round(tick.ask + BRAIN_EMERGENCY_TRAIL * tp_dist, sym.digits)
                min_move = 10 ** (-sym.digits + 1)
                if p.sl == 0 or new_sl < round(p.sl, sym.digits) - min_move:
                    _brain_sltp(p, new_sl, p.tp, sym, frame,
                                f"profit trail SL->{new_sl} ({pct:.0f}% of TP)")

        # ── 5. TP EXTENSION ───────────────────────────────────────────────────
        if p.ticket not in _tp_extended and pct >= BRAIN_TP_EXTEND_PCT * 100 and score >= 1:
            extra = tp_dist * (BRAIN_TP_EXTEND_MULT - 1)
            if p.type == mt5.POSITION_TYPE_BUY:
                new_tp = round(p.tp + extra, sym.digits)
            else:
                new_tp = round(p.tp - extra, sym.digits)
            _brain_sltp(p, p.sl, new_tp, sym, frame,
                        f"TP extended {p.tp}->{new_tp} ({pct:.0f}% of orig, score={score})")
            _tp_extended.add(p.ticket)

        # ── 6. PARTIAL CLOSE ──────────────────────────────────────────────────
        if p.ticket not in _partial_closed and pct >= BRAIN_PARTIAL_PCT * 100 and p.profit > 0:
            half = round(p.volume / 2, 2)
            if half >= sym.volume_min:
                close_type  = mt5.ORDER_TYPE_SELL if p.type == mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY
                close_price = tick.bid             if p.type == mt5.POSITION_TYPE_BUY else tick.ask
                result = mt5.order_send({
                    "action":       mt5.TRADE_ACTION_DEAL,
                    "position":     p.ticket,
                    "symbol":       p.symbol,
                    "volume":       half,
                    "type":         close_type,
                    "price":        close_price,
                    "deviation":    20,
                    "magic":        p.magic,
                    "type_filling": mt5.ORDER_FILLING_IOC,
                    "type_time":    mt5.ORDER_TIME_GTC
                })
                if result.retcode == 10009:
                    _partial_closed.add(p.ticket)
                    slog(p.symbol, frame, "PARTIAL CLOSE",
                         f"50% @ {close_price}  locked ~${p.profit/2:.2f}")
                    # move SL to breakeven on remaining half
                    _brain_sltp(p, p.price_open, p.tp, sym, frame,
                                "SL->breakeven after partial close")


def show_open_positions():

    positions = mt5.positions_get()

    if not positions:
        print("ACTIVE TRADES: none")
        return

    print("\nACTIVE TRADES")

    for p in positions:

        side = "BUY" if p.type == mt5.POSITION_TYPE_BUY else "SELL"

        print(
            p.symbol,
            side,
            "vol:", p.volume,
            "profit:", round(p.profit, 2)
        )


def show_recent_history(minutes=10):

    now = datetime.now()
    past = now - timedelta(minutes=minutes)

    deals = mt5.history_deals_get(past, now)

    if not deals:
        return

    print("\nRECENT CLOSED TRADES")

    for d in deals:

        if d.entry != mt5.DEAL_ENTRY_OUT:
            continue

        print(
            d.symbol,
            "profit:", round(d.profit, 2),
            "time:", datetime.fromtimestamp(d.time).strftime("%H:%M:%S")
        )


def account_summary(save=True):

    info = mt5.account_info()
    if info is None:
        return

    # all our closed deals, from the beginning of time
    epoch     = datetime(2000, 1, 1, tzinfo=timezone.utc)
    now       = datetime.now(timezone.utc)
    all_deals = mt5.history_deals_get(epoch, now) or []

    our_deals  = [d for d in all_deals
                  if d.magic in (MAGIC_SHORT, MAGIC_LONG)
                  and d.entry == mt5.DEAL_ENTRY_OUT]

    wins      = [d for d in our_deals if d.profit > 0]
    losses    = [d for d in our_deals if d.profit < 0]
    breakeven = [d for d in our_deals if d.profit == 0]
    total_pnl = sum(d.profit for d in our_deals)
    win_rate  = len(wins) / len(our_deals) * 100 if our_deals else 0
    avg_win   = sum(d.profit for d in wins)   / len(wins)   if wins   else 0
    avg_loss  = sum(d.profit for d in losses) / len(losses) if losses else 0
    best      = max(our_deals, key=lambda d: d.profit, default=None)
    worst     = min(our_deals, key=lambda d: d.profit, default=None)

    # open positions
    positions = mt5.positions_get() or []
    our_pos   = [p for p in positions if p.magic in (MAGIC_SHORT, MAGIC_LONG)]
    open_pnl  = sum(p.profit for p in our_pos)

    W  = 54
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    lines = [
        f"\n{'═'*W}",
        f"  BALANCE SHEET   {ts}",
        f"{'═'*W}",
        f"  Balance      ${info.balance:>10.2f}",
        f"  Equity       ${info.equity:>10.2f}",
        f"  Open P&L     ${open_pnl:>+10.2f}   ({len(our_pos)} open)",
        f"{'─'*W}",
    ]

    if our_pos:
        lines.append("  OPEN POSITIONS")
        for p in our_pos:
            side   = "BUY" if p.type == mt5.POSITION_TYPE_BUY else "SELL"
            frame  = "short" if p.magic == MAGIC_SHORT else "long"
            tp_dist = abs(p.tp - p.price_open) if p.tp else 0
            tick   = mt5.symbol_info_tick(p.symbol)
            if tick and tp_dist:
                cur    = tick.bid if p.type == mt5.POSITION_TYPE_BUY else tick.ask
                pdiff  = cur - p.price_open if p.type == mt5.POSITION_TYPE_BUY else p.price_open - cur
                pct    = pdiff / tp_dist * 100
            else:
                pct = 0
            peak = _peak_profit.get(p.ticket, p.profit)
            lines.append(
                f"  {p.symbol:<12} {side:<4} [{frame}]"
                f"  pnl:${p.profit:>+6.2f}"
                f"  {pct:>+5.0f}% of TP"
                f"  peak:${peak:>+6.2f}"
            )
        lines.append(f"{'─'*W}")

    lines += [
        f"  CLOSED TRADES (bot only)",
        f"  Total        {len(our_deals):>4}   |  Win rate:  {win_rate:>5.1f}%",
        f"  Wins         {len(wins):>4}   |  Losses:    {len(losses):>4}   |  BE: {len(breakeven)}",
        f"  Total P&L    ${total_pnl:>+9.2f}",
        f"  Avg win      ${avg_win:>+9.2f}   |  Avg loss:  ${avg_loss:>+.2f}",
    ]

    if best:
        t = datetime.fromtimestamp(best.time).strftime("%m-%d %H:%M")
        lines.append(f"  Best trade   ${best.profit:>+9.2f}   {best.symbol:<12} {t}")
    if worst:
        t = datetime.fromtimestamp(worst.time).strftime("%m-%d %H:%M")
        lines.append(f"  Worst trade  ${worst.profit:>+9.2f}   {worst.symbol:<12} {t}")

    # last 5 closed trades
    if our_deals:
        last5 = sorted(our_deals, key=lambda d: d.time)[-5:]
        lines.append(f"{'─'*W}")
        lines.append(f"  LAST {len(last5)} CLOSED")
        for d in reversed(last5):
            t    = datetime.fromtimestamp(d.time).strftime("%m-%d %H:%M")
            flag = "WIN " if d.profit > 0 else ("LOSS" if d.profit < 0 else "BE  ")
            lines.append(f"  {flag}  {d.symbol:<12}  ${d.profit:>+7.2f}   {t}")

    lines.append(f"{'═'*W}")

    text = "\n".join(lines)
    print(text)

    if save:
        with open("balance.log", "a", buffering=1, encoding="utf-8") as f:
            f.write(text + "\n")