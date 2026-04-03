#!/usr/bin/env python3
"""
SYSTEM AUDIT INTEGRATION - Signal Flow Verification

This module provides integration points for auditing the signal → execution → MT5 mapping.
Add these calls to main.py and trader.py to enable comprehensive audit logging.
"""

print("""
════════════════════════════════════════════════════════════════════════════════
SYSTEM AUDIT INTEGRATION GUIDE
════════════════════════════════════════════════════════════════════════════════

This document describes where to add audit logging calls to verify correct
signal flow, strategy transformation, and MT5 terminal isolation.

NO TRADING LOGIC IS MODIFIED - only logging is added.

════════════════════════════════════════════════════════════════════════════════
STEP 1: trader.py - Log MT5 Connection
════════════════════════════════════════════════════════════════════════════════

Location: After mt5.login() succeeds in init_mt5()
File: trader.py, after line 31-32 (after login)

Add:

    from system_audit import SystemAudit

    # After successful login
    account_info = mt5.account_info()
    terminal_info = mt5.terminal_info()
    SystemAudit.log_mt5_connection(BOT_ID, account_info, terminal_info)

────────────────────────────────────────────────────────────────────────────────

STEP 2: main.py - Log Signal Fetch
════════════════════════════════════════════════════════════════════════════════

Location: After signals are fetched from website
File: main.py, in run_signal_cycle() function (~line 327+)

After:
    signals = [convert raw signals to Signal objects]

Add:

    from system_audit import SystemAudit

    SystemAudit.log_signal_fetch(BOT_ID, signals, strategy.name if hasattr(strategy, 'name') else 'unknown')

────────────────────────────────────────────────────────────────────────────────

STEP 3: main.py - Log Signal Transformation
════════════════════════════════════════════════════════════════════════════════

Location: After strategy.transform_signal() is called
File: main.py, wherever signals are transformed

Before execution:
    transformed_sig = strategy.transform_signal(raw_signal)

Add:

    SystemAudit.log_signal_transformation(
        bot_id=BOT_ID,
        pair=raw_signal.pair,
        original_side=raw_signal.side,
        transformed_side=transformed_sig.side,
        original_tp=raw_signal.tp,
        transformed_tp=transformed_sig.tp,
        original_sl=raw_signal.sl,
        transformed_sl=transformed_sig.sl,
        strategy_name=strategy.name if hasattr(strategy, 'name') else 'unknown'
    )

────────────────────────────────────────────────────────────────────────────────

STEP 4: main.py / trader.py - Log Trade Request
════════════════════════════════════════════════════════════════════════════════

Location: Before open_trade() is called
File: main.py, before calling open_trade()

Add:

    SystemAudit.log_trade_request(
        bot_id=BOT_ID,
        symbol=signal.pair,
        side=signal.side,
        volume=TRADE_VOLUME,
        entry_price=signal.open_price if hasattr(signal, 'open_price') else signal.entry,
        tp=signal.tp,
        sl=signal.sl
    )

────────────────────────────────────────────────────────────────────────────────

STEP 5: trader.py - Log Trade Result
════════════════════════════════════════════════════════════════════════════════

Location: After mt5.order_send()
File: trader.py, in open_trade() function after result = mt5.order_send()

Add:

    SystemAudit.log_trade_result(
        bot_id=BOT_ID,
        symbol=symbol,
        retcode=result.retcode if hasattr(result, 'retcode') else None,
        ticket=result.order if hasattr(result, 'order') else None
    )

────────────────────────────────────────────────────────────────────────────────

STEP 6: main.py - Log Position Check
════════════════════════════════════════════════════════════════════════════════

Location: When positions are verified in run_signal_cycle()
File: main.py, after mt5.positions_get()

Add:

    mt5_positions = mt5.positions_get() or []
    SystemAudit.log_position_check(BOT_ID, mt5_positions)

════════════════════════════════════════════════════════════════════════════════
VERIFICATION OUTPUT
════════════════════════════════════════════════════════════════════════════════

After adding the audit logging calls above, you will see output like:

    [MT5_CONNECT] Bot=1 Login=24446623 Server=VantageInternational-Demo Terminal=/path/to/bot_1
    [SIGNAL_FETCH] Bot=1 Strategy=MIRROR Count=3 Pairs=['EURUSD', 'GBPUSD', 'USDJPY']
    [SIGNAL_TRANSFORM] Bot=1 Strategy=mirror Pair=EURUSD Side=BUY→BUY TP=1.08500→1.08500 SL=1.07500→1.07500
    [TRADE_REQUEST] Bot=1 Symbol=EURUSD Side=BUY Volume=0.01 Entry=1.08000 TP=1.08500 SL=1.07500
    [TRADE_RESULT] Bot=1 Symbol=EURUSD Status=SUCCESS Ticket=123456 OrderID=None
    [POSITION_CHECK] Bot=1 Count=1 Positions=[T123456/EURUSD/BUY]

════════════════════════════════════════════════════════════════════════════════
ASSERTIONS & VERIFICATION
════════════════════════════════════════════════════════════════════════════════

The audit module includes automatic assertions for:

✔ Bot-specific terminal paths
✔ Strategy transformation correctness (Mirror, Reverse)
✔ Trade execution result codes
✔ Position ownership verification
✔ Cross-bot isolation checks

If any assertion fails, you will see:
    [AUDIT_FAIL] ... detailed error message

════════════════════════════════════════════════════════════════════════════════
""")
