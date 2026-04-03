"""
SIMPLE TRADER - Blind follower

Just opens and closes trades as website signals say.
No fancy position management.
"""

import time
import subprocess
import MetaTrader5 as mt5
from datetime import datetime, timezone

MAGIC_NUMBER = 777  # All trades use same magic (no frame distinction in blind mode)
MAX_RETRIES = 3
MAX_CLOSE_ATTEMPTS = 5

# Track close attempts per ticket to prevent infinite loops
close_attempts = {}


def init_mt5(mt5_login, mt5_password, mt5_server, mt5_exe):
    """Initialize MetaTrader5 with bot-specific credentials.

    Args:
        mt5_login: MT5 account login (bot-specific)
        mt5_password: MT5 account password (bot-specific)
        mt5_server: MT5 server name
        mt5_exe: Path to MT5 terminal executable

    Raises:
        RuntimeError: If MT5 initialization or login fails
    """
    if not mt5.initialize():
        print("MT5 not running — launching terminal...")
        subprocess.Popen(mt5_exe, creationflags=subprocess.CREATE_NO_WINDOW)
        time.sleep(10)
        if not mt5.initialize():
            raise RuntimeError("MT5 init failed after launch")

    if not mt5.login(mt5_login, mt5_password, mt5_server):
        raise RuntimeError(f"MT5 login failed for account {mt5_login}")

    account_info = mt5.account_info()
    print(f"[MT5] Connected to account {mt5_login} ({account_info.name if account_info else 'name unknown'})")


def validate_and_adjust_stops(symbol, side, price, tp, sl):
    """Validate SL/TP against broker constraints (stops + freeze levels).

    Adjusts SL and TP if they violate broker minimum distance requirements.
    Uses BOTH trade_stops_level AND trade_freeze_level.

    Args:
        symbol: Trading pair
        side: 'BUY' or 'SELL'
        price: Current price (bid/ask)
        tp: Take profit level
        sl: Stop loss level

    Returns:
        (adjusted_sl, adjusted_tp, was_adjusted)
    """
    try:
        symbol_info = mt5.symbol_info(symbol)
        if not symbol_info:
            return sl, tp, False

        # Get BOTH broker constraints
        stops_level = symbol_info.trade_stops_level
        freeze_level = symbol_info.trade_freeze_level
        point = symbol_info.point

        # Use the MAXIMUM of both (most restrictive)
        min_distance = max(stops_level, freeze_level) * point

        was_adjusted = False
        adjusted_sl = sl
        adjusted_tp = tp

        # ─── ADJUST SL ──────────────────────────────────────────────────────
        if side == 'BUY':
            # For BUY: SL must be BELOW price by at least min_distance
            if (price - adjusted_sl) < min_distance:
                adjusted_sl = price - min_distance
                was_adjusted = True
        else:  # SELL
            # For SELL: SL must be ABOVE price by at least min_distance
            if (adjusted_sl - price) < min_distance:
                adjusted_sl = price + min_distance
                was_adjusted = True

        # ─── ADJUST TP ──────────────────────────────────────────────────────
        if side == 'BUY':
            # For BUY: TP must be ABOVE price by at least min_distance
            if (adjusted_tp - price) < min_distance:
                adjusted_tp = price + min_distance
                was_adjusted = True
        else:  # SELL
            # For SELL: TP must be BELOW price by at least min_distance
            if (price - adjusted_tp) < min_distance:
                adjusted_tp = price - min_distance
                was_adjusted = True

        if was_adjusted:
            print(f"  [STOPS_FIXED] {symbol} | stops_level={stops_level} freeze_level={freeze_level} | min_distance={min_distance:.5f} | SL: {sl:.5f}->{adjusted_sl:.5f} | TP: {tp:.5f}->{adjusted_tp:.5f}")

        return adjusted_sl, adjusted_tp, was_adjusted

    except Exception as e:
        print(f"  [STOPS_ERR] Error validating stops for {symbol}: {e}")
        return sl, tp, False


def get_adaptive_deviation(symbol: str) -> int:
    """
    Calculate adaptive deviation based on symbol volatility.
    JPY pairs: max(100, 3x spread)
    Standard pairs: max(50, 2x spread)
    """
    try:
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            return 100  # Safe default

        spread_points = int((tick.ask - tick.bid) / mt5.symbol_info(symbol).point)

        if "JPY" in symbol:
            return max(100, spread_points * 3)
        else:
            return max(50, spread_points * 2)
    except Exception as e:
        print(f"  [DEVIATION] Error calculating deviation for {symbol}: {e}")
        return 100  # Safe default


def open_trade(signal, volume: float):
    """
    Open a trade exactly as signal says with retry logic.

    Args:
        signal: Signal object with attributes (pair, side, open_price, tp, sl, frame, ...)
        volume: Trade volume (lot size) to open

    Returns:
        (success: bool, ticket: int or None)
    """

    pair = signal.pair
    side = signal.side
    tp = signal.tp
    sl = signal.sl

    # ─── Get symbol ──────────────────────────────────────────────────────
    sym = None
    for name in (pair, pair + "+"):
        mt5.symbol_select(name, True)
        time.sleep(0.5)
        info = mt5.symbol_info(name)
        if info is not None and info.trade_mode != 0:
            pair = name
            sym = info
            break

    if sym is None:
        print(f"  [SKIP] Symbol {pair} not available")
        return False, None

    # ─── FIX 3: Ensure tick data available ───────────────────────────────
    tick = mt5.symbol_info_tick(pair)
    if tick is None:
        print(f"  [SKIP] No tick data for {pair}")
        return False, None

    price = tick.ask if side == "BUY" else tick.bid

    # ─── Send order with retry logic ─────────────────────────────────────
    order_type = mt5.ORDER_TYPE_BUY if side == "BUY" else mt5.ORDER_TYPE_SELL
    result = None

    for attempt in range(MAX_RETRIES):
        # FIX 7 (NEW): Validate and adjust SL/TP to broker minimum
        adjusted_sl, adjusted_tp, stops_adjusted = validate_and_adjust_stops(
            pair, side, price, tp, sl
        )

        # FIX 6: Calculate adaptive deviation based on spread
        deviation = get_adaptive_deviation(pair)

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": pair,
            "volume": volume,
            "type": order_type,
            "price": price,
            "tp": adjusted_tp,  # Use adjusted TP
            "sl": adjusted_sl,  # Use adjusted SL
            "deviation": deviation,
            "magic": MAGIC_NUMBER,
            "comment": "blind",
            "type_filling": mt5.ORDER_FILLING_IOC,
            "type_time": mt5.ORDER_TIME_GTC
        }

        result = mt5.order_send(request)

        # FIX 5: Log MT5 errors properly
        if result:
            print(f"  [MT5] Attempt {attempt+1}: retcode={result.retcode} comment={result.comment}")

        # Success - break loop
        if result and result.retcode == mt5.TRADE_RETCODE_DONE:
            print(f"  [OPENED] {side} {pair} @ {result.price} | SL: {adjusted_sl:.5f} | TP: {adjusted_tp:.5f} | Ticket: {result.order} | Deviation: {deviation}")
            return True, result.order

        # Price moved - try again with fresh price
        if result and result.retcode == 10016:  # Price moved
            if attempt < MAX_RETRIES - 1:
                print(f"  [RETRY] Price moved (attempt {attempt+1}/{MAX_RETRIES}), refreshing...")
                tick = mt5.symbol_info_tick(pair)
                if tick:
                    price = tick.ask if side == "BUY" else tick.bid
                time.sleep(0.2)
            else:
                print(f"  [FAIL] Price moved after {MAX_RETRIES} retries - skipping")
                return True, None  # Mark as processed
        else:
            # Other errors - don't retry
            if result:
                print(f"  [FAILED] Order rejected: retcode={result.retcode} comment={result.comment}")
            else:
                print(f"  [FAILED] Order send returned None")
            return False, None

    return False, None



def close_trade(pair):
    """Close all positions for this pair with tick data check and retry logic."""

    closed_count = 0
    for name in (pair, pair + "+"):
        # FIX 3: Ensure tick data available before closing
        tick = mt5.symbol_info_tick(name)
        if tick is None:
            print(f"  [SKIP] No tick data for {name} - cannot close")
            continue

        positions = mt5.positions_get(symbol=name)
        if not positions:
            continue

        for pos in positions:
            if pos.magic != MAGIC_NUMBER:
                continue

            ticket = pos.ticket
            entry_price = pos.price_open

            # FIX 4: Track close attempts
            if ticket not in close_attempts:
                close_attempts[ticket] = 0
            close_attempts[ticket] += 1

            # If exceeded max attempts, give up and remove from tracking
            if close_attempts[ticket] > MAX_CLOSE_ATTEMPTS:
                print(f"  [FORCE CLOSE] T{ticket} exceeded max close attempts ({MAX_CLOSE_ATTEMPTS}) - removing from tracking")
                if ticket in close_attempts:
                    del close_attempts[ticket]
                continue

            # FIX 6: Use adaptive deviation
            deviation = get_adaptive_deviation(name)

            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": name,
                "volume": pos.volume,
                "type": mt5.ORDER_TYPE_SELL if pos.type == 0 else mt5.ORDER_TYPE_BUY,
                "position": pos.ticket,
                "deviation": deviation,
                "magic": MAGIC_NUMBER,
                "comment": "close",
                "type_filling": mt5.ORDER_FILLING_IOC,
                "type_time": mt5.ORDER_TIME_GTC
            }

            result = mt5.order_send(request)

            # FIX 5: Log MT5 errors properly
            if result:
                print(f"  [MT5] Close attempt {close_attempts[ticket]}: retcode={result.retcode} comment={result.comment}")

            if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                # Fetch real close price from deal history
                close_deal = None
                try:
                    deals = mt5.history_deals_get(position=ticket, group="*")
                    if deals:
                        for deal in reversed(deals):
                            if deal.entry == 1:  # Closing deal
                                close_deal = deal
                                break
                except Exception:
                    pass

                if close_deal:
                    close_price = close_deal.price
                    close_profit = close_deal.profit
                    price_diff = close_price - entry_price
                    print(f"  [CLOSED] {name} T{ticket} Entry: {entry_price} -> Close: {close_price} | Diff: {price_diff:.6f} | Profit: ${close_profit:.2f}")
                else:
                    print(f"  [CLOSED] {name} | Profit: ${pos.profit:.2f}")

                closed_count += 1
                # Clear close attempt counter on success
                if ticket in close_attempts:
                    del close_attempts[ticket]
            elif result and result.retcode == 10016:
                # Price moved - will retry next cycle
                print(f"  [RETRY] Close price moved for T{ticket}")

    return closed_count > 0



def close_position_by_ticket(ticket, pair=None):
    """Close a specific position by ticket number with retry logic and tick checks."""

    # ──── EXECUTION TRACE ────
    import traceback
    import inspect

    stack = traceback.extract_stack()
    caller_frame = None
    caller_function = "UNKNOWN"

    # Find caller (skip this function and decorator frames)
    for frame in reversed(stack[:-1]):
        if "close_position_by_ticket" not in frame.name:
            caller_frame = frame
            caller_function = frame.name if frame.name else "UNKNOWN"
            break

    print(f"[TRACE_CLOSE] Ticket {ticket} close initiated")
    print(f"[TRACE_CLOSE] Caller: {caller_function}() at {caller_frame.filename.split(chr(92))[-1] if caller_frame else 'unknown'}:{caller_frame.lineno if caller_frame else '?'}")

    # FIX 4: Track close attempts per ticket
    if ticket not in close_attempts:
        close_attempts[ticket] = 0
    close_attempts[ticket] += 1

    # If exceeded max attempts, give up
    if close_attempts[ticket] > MAX_CLOSE_ATTEMPTS:
        print(f"[FORCE CLOSE] Ticket {ticket} exceeded max close attempts ({MAX_CLOSE_ATTEMPTS}) - removing from tracking")
        if ticket in close_attempts:
            del close_attempts[ticket]
        return False

    if ticket in [1029131995, 1028771560, 1028924631]:  # Known problem tickets
        print(f"[TRACE_CLOSE] **PROBLEM TICKET DETECTED** (attempt {close_attempts[ticket]}/{MAX_CLOSE_ATTEMPTS})")

    names = [(pair, pair + "+")] if pair else [(None, None)]

    for name1, name2 in names:
        for name in (name1, name2):
            if name is None:
                continue

            # FIX 3: Ensure tick data available before closing
            tick = mt5.symbol_info_tick(name)
            if tick is None:
                print(f"  [SKIP] No tick data for {name} - cannot close T{ticket}")
                continue

            positions = mt5.positions_get(symbol=name)
            if not positions:
                continue

            for pos in positions:
                if pos.ticket != ticket or pos.magic != MAGIC_NUMBER:
                    continue

                # Store entry details BEFORE close
                entry_price = pos.price_open
                entry_time = datetime.now(timezone.utc)

                # Get tick info before close
                bid_before = tick.bid if tick else 0
                ask_before = tick.ask if tick else 0

                # FIX 6: Use adaptive deviation
                deviation = get_adaptive_deviation(name)

                request = {
                    "action": mt5.TRADE_ACTION_DEAL,
                    "symbol": name,
                    "volume": pos.volume,
                    "type": mt5.ORDER_TYPE_SELL if pos.type == 0 else mt5.ORDER_TYPE_BUY,
                    "position": ticket,
                    "deviation": deviation,
                    "magic": MAGIC_NUMBER,
                    "comment": "close",
                    "type_filling": mt5.ORDER_FILLING_IOC,
                    "type_time": mt5.ORDER_TIME_GTC
                }

                result = mt5.order_send(request)

                # FIX 5: Log MT5 errors properly
                if result:
                    print(f"  [MT5] Close attempt {close_attempts[ticket]}: retcode={result.retcode} comment={result.comment}")

                if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                    # Close succeeded - fetch real close price from deal history
                    close_deal = None
                    try:
                        # Get deals for this position (most recent deals)
                        deals = mt5.history_deals_get(position=ticket, group="*")
                        if deals:
                            # Find the CLOSING deal (should be most recent)
                            for deal in reversed(deals):
                                # Deal type: DEAL_TYPE_BUY=0, DEAL_TYPE_SELL=1
                                # Deal entry: DEAL_ENTRY_IN=0, DEAL_ENTRY_OUT=1
                                if deal.entry == 1:  # CLOSING deal
                                    close_deal = deal
                                    break
                    except Exception as e:
                        print(f"    [DEBUG] Deal history error: {e}")

                    if close_deal:
                        close_price = close_deal.price
                        close_profit = close_deal.profit
                        price_diff = close_price - entry_price

                        # Detect if close at entry or real movement
                        if abs(price_diff) < 0.00001 and close_profit != 0:
                            warning = " [WARNING: Close at entry but non-zero profit - likely friction only]"
                        else:
                            warning = ""

                        print(f"  [CLOSED] T{ticket} Entry: {entry_price} -> Close: {close_price} | Movement: {price_diff:.6f} pips | Profit: ${close_profit:.2f}{warning}")

                        # ─── CLOSE CORRELATION TRACE ─────────────────────────────────────
                        # Log close details for correlation with trailing stop moves
                        close_reason = caller_function if caller_function != "UNKNOWN" else "UNKNOWN"
                        print(f"[CLOSE_TRACE] T{ticket} | reason={close_reason} | close={close_price:.5f} | sl={pos.sl:.5f} | tp={pos.tp:.5f} | entry={entry_price:.5f} | profit=${close_profit:.2f}")
                    else:
                        # Fallback if deal history unavailable
                        print(f"  [CLOSED] T{ticket} (deal history unavailable) | Entry: {entry_price} | Profit: ${pos.profit:.2f}")

                        # ─── CLOSE CORRELATION TRACE (FALLBACK) ─────────────────────────────────
                        close_reason = caller_function if caller_function != "UNKNOWN" else "UNKNOWN"
                        print(f"[CLOSE_TRACE] T{ticket} | reason={close_reason} | close=UNKNOWN | sl={pos.sl:.5f} | tp={pos.tp:.5f} | entry={entry_price:.5f} | profit=${pos.profit:.2f}")

                    # Verify position actually closed in MT5
                    time.sleep(0.5)  # Wait for MT5 to update
                    remaining = mt5.positions_get(ticket=ticket)
                    if remaining:
                        print(f"    [ERROR] Position T{ticket} still exists in MT5 after close!")
                    else:
                        print(f"    [OK] Position T{ticket} fully closed in MT5")

                    # Clear close attempt counter on success
                    if ticket in close_attempts:
                        del close_attempts[ticket]

                    return True
                elif result and result.retcode == 10016:
                    # Price moved - will retry next cycle
                    print(f"  [RETRY] Close price moved for T{ticket}, will retry")
                    return False

    print(f"  [WARN] Position ticket {ticket} not found")
    return False



def get_position(pair):
    """Get any open position for this pair."""

    for name in (pair, pair + "+"):
        positions = mt5.positions_get(symbol=name)
        if positions:
            for p in positions:
                if p.magic == MAGIC_NUMBER:
                    return p

    return None


def show_open_positions():
    """Display all open positions (fault-tolerant)."""
    try:
        positions = mt5.positions_get()
        if not positions:
            print("  No open positions")
            return

        print(f"  Open positions: {len(positions)}")
        for p in positions[:5]:  # Show first 5
            try:
                pos_type = "BUY" if p.type == 0 else "SELL"
                symbol = getattr(p, 'symbol', 'UNKNOWN')
                price_open = getattr(p, 'price_open', 0.0)
                profit = getattr(p, 'profit', 0.0)
                print(f"    [{symbol}] {pos_type} @ {price_open:.5f} | Profit: ${profit:.2f}")
            except Exception as e:
                print(f"  [ERROR_POS] Failed to display position: {e}")
                continue
    except Exception as e:
        print(f"  [ERROR_MT5] show_open_positions failed: {e}")


def account_summary():
    """Show account stats (fault-tolerant)."""
    try:
        info = mt5.account_info()
        if not info:
            print("  [WARN] Account info unavailable")
            return

        try:
            balance = getattr(info, 'balance', 0.0)
            equity = getattr(info, 'equity', 0.0)
            print(f"  Account: Balance ${balance:.2f} | Equity ${equity:.2f}")
        except Exception as e:
            print(f"  [ERROR_ACCT] Failed to display account info: {e}")
    except Exception as e:
        print(f"  [ERROR_MT5] account_summary failed: {e}")
