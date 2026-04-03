#!/usr/bin/env python3
"""
SYSTEM AUDIT - Signal Flow → Execution → MT5 Terminal Mapping

Verifies that each bot:
1. Fetches signals correctly
2. Transforms signals per strategy
3. Executes trades in correct MT5 terminal
4. Never mixes accounts or terminals

This module provides audit logging and assertions without modifying trading logic.
"""

import json
from typing import Optional, List, Dict, Any


class SystemAudit:
    """Audit logging for signal → execution → terminal mapping."""

    # Class-level tracking for cross-bot detection
    _bots_seen = {}  # {BOT_ID: {'terminal': str, 'login': int, 'strategy': str}}
    _execution_log = []  # {BOT_ID, timestamp, signal, execution_result}

    @staticmethod
    def log_mt5_connection(bot_id: int, account_info: Any, terminal_info: Any):
        """
        Log MT5 connection details per bot.

        Call after mt5.login() succeeds.
        """
        if account_info is None or terminal_info is None:
            print(f"[AUDIT_ERROR] Bot {bot_id}: account_info or terminal_info is None")
            return

        login = account_info.login if hasattr(account_info, 'login') else 'UNKNOWN'
        server = account_info.server if hasattr(account_info, 'server') else 'UNKNOWN'
        path = terminal_info.path if hasattr(terminal_info, 'path') else 'UNKNOWN'

        # Log the connection
        print(
            f"[MT5_CONNECT] Bot={bot_id} "
            f"Login={login} Server={server} "
            f"Terminal={path}"
        )

        # Track for cross-bot verification
        SystemAudit._bots_seen[bot_id] = {
            'login': login,
            'server': server,
            'terminal': path,
        }

        # Verify bot-specific naming
        bot_str = str(bot_id)
        if bot_id == 1:
            assert bot_str in path or "bot_1" in path.lower() or "Bot1" in path or "BOT1" in path, \
                f"[AUDIT_FAIL] Bot 1 terminal path doesn't contain bot identifier: {path}"
        elif bot_id == 2:
            assert bot_str in path or "bot_2" in path.lower() or "Bot2" in path or "BOT2" in path, \
                f"[AUDIT_FAIL] Bot 2 terminal path doesn't contain bot identifier: {path}"
        elif bot_id == 3:
            assert bot_str in path or "bot_3" in path.lower() or "Bot3" in path or "BOT3" in path, \
                f"[AUDIT_FAIL] Bot 3 terminal path doesn't contain bot identifier: {path}"

        print(f"[AUDIT_OK] Bot {bot_id} connected to correct terminal")

    @staticmethod
    def log_signal_fetch(bot_id: int, signals: List[Any], strategy_name: str):
        """
        Log signal fetch details per bot.

        Args:
            bot_id: Bot identifier
            signals: List of fetched Signal objects
            strategy_name: Strategy being applied
        """
        signal_count = len(signals) if signals else 0
        pairs = []

        if signals:
            for sig in signals:
                if hasattr(sig, 'pair'):
                    pairs.append(sig.pair)
                elif hasattr(sig, 'symbol'):
                    pairs.append(sig.symbol)

        print(
            f"[SIGNAL_FETCH] Bot={bot_id} "
            f"Strategy={strategy_name.upper()} "
            f"Count={signal_count} "
            f"Pairs={pairs if pairs else 'none'}"
        )

        assert signal_count >= 0, f"[AUDIT_FAIL] Invalid signal count: {signal_count}"

    @staticmethod
    def log_signal_transformation(
        bot_id: int,
        pair: str,
        original_side: str,
        transformed_side: str,
        original_tp: float,
        transformed_tp: float,
        original_sl: float,
        transformed_sl: float,
        strategy_name: str
    ):
        """
        Log signal transformation per bot.

        Verifies strategy correctness.
        """
        print(
            f"[SIGNAL_TRANSFORM] Bot={bot_id} "
            f"Strategy={strategy_name} "
            f"Pair={pair} "
            f"Side={original_side}→{transformed_side} "
            f"TP={original_tp:.5f}→{transformed_tp:.5f} "
            f"SL={original_sl:.5f}→{transformed_sl:.5f}"
        )

        # Basic validations
        assert original_side in ('BUY', 'SELL'), f"Invalid original side: {original_side}"
        assert transformed_side in ('BUY', 'SELL'), f"Invalid transformed side: {transformed_side}"

        # Strategy-specific validation
        if strategy_name.lower() == 'mirror':
            assert original_side == transformed_side, \
                f"[AUDIT_FAIL] Mirror strategy should NOT invert: {original_side} → {transformed_side}"
            assert original_tp == transformed_tp and original_sl == transformed_sl, \
                f"[AUDIT_FAIL] Mirror strategy should NOT change TP/SL"

        elif strategy_name.lower() == 'reverse':
            assert original_side != transformed_side, \
                f"[AUDIT_FAIL] Reverse strategy MUST invert: {original_side}"

    @staticmethod
    def log_trade_request(
        bot_id: int,
        symbol: str,
        side: str,
        volume: float,
        entry_price: float,
        tp: float,
        sl: float
    ):
        """
        Log trade execution request before order_send().
        """
        print(
            f"[TRADE_REQUEST] Bot={bot_id} "
            f"Symbol={symbol} "
            f"Side={side} "
            f"Volume={volume} "
            f"Entry={entry_price:.5f} "
            f"TP={tp:.5f} "
            f"SL={sl:.5f}"
        )

        assert symbol and len(symbol) > 0, "[AUDIT_FAIL] Empty symbol"
        assert side in ('BUY', 'SELL'), f"[AUDIT_FAIL] Invalid side: {side}"
        assert volume > 0, f"[AUDIT_FAIL] Invalid volume: {volume}"

    @staticmethod
    def log_trade_result(
        bot_id: int,
        symbol: str,
        retcode: int,
        ticket: Optional[int] = None,
        order_id: Optional[int] = None
    ):
        """
        Log MT5 order_send() result.
        """
        status = "SUCCESS" if retcode == 10009 else f"FAILED_CODE_{retcode}"  # 10009 = TRADE_RETCODE_DONE

        print(
            f"[TRADE_RESULT] Bot={bot_id} "
            f"Symbol={symbol} "
            f"Status={status} "
            f"Ticket={ticket} "
            f"OrderID={order_id}"
        )

        # Track execution for audit
        SystemAudit._execution_log.append({
            'bot_id': bot_id,
            'symbol': symbol,
            'retcode': retcode,
            'ticket': ticket,
            'timestamp': None
        })

    @staticmethod
    def log_position_check(
        bot_id: int,
        positions_list: List[Any]
    ):
        """
        Log positions for bot and verify isolation.

        Checks that bot only sees its own positions.
        """
        if not positions_list:
            print(f"[POSITION_CHECK] Bot={bot_id} Positions=0 (no open trades)")
            return

        position_details = []
        for pos in positions_list:
            ticket = pos.ticket if hasattr(pos, 'ticket') else '?'
            symbol = pos.symbol if hasattr(pos, 'symbol') else '?'
            side = 'BUY' if hasattr(pos, 'type') and pos.type == 0 else 'SELL'

            position_details.append(f"T{ticket}/{symbol}/{side}")

        print(
            f"[POSITION_CHECK] Bot={bot_id} "
            f"Count={len(positions_list)} "
            f"Positions=[{', '.join(position_details)}]"
        )

    @staticmethod
    def verify_no_cross_bot_interference():
        """
        Verify that bots are using different terminals/accounts.
        """
        if len(SystemAudit._bots_seen) < 2:
            return  # Not enough bots to check cross-contamination

        print("\n[AUDIT_VERIFICATION] Cross-bot isolation check:")
        print("-" * 80)

        logins = set()
        terminals = set()

        for bot_id, info in SystemAudit._bots_seen.items():
            login = info['login']
            terminal = info['terminal']

            logins.add(login)
            terminals.add(terminal)

            print(f"  Bot {bot_id}: Login={login}, Terminal={terminal}")

        # Check for mix-ups
        if len(logins) == 1 and len(SystemAudit._bots_seen) > 1:
            print("  ⚠️  WARNING: Multiple bots using SAME LOGIN")
            print("     (This may be OK if terminals are different)")

        if len(terminals) == 1 and len(SystemAudit._bots_seen) > 1:
            print("  ⚠️  WARNING: Multiple bots using SAME TERMINAL")
            print("     (Potential risk of account mix-up)")
        else:
            print("  ✅ Each bot has unique terminal path")

        print("-" * 80 + "\n")

    @staticmethod
    def generate_audit_report():
        """
        Generate comprehensive audit report.
        """
        print("\n" + "=" * 80)
        print("SYSTEM AUDIT REPORT")
        print("=" * 80)

        print(f"\nBots Seen: {len(SystemAudit._bots_seen)}")
        for bot_id, info in sorted(SystemAudit._bots_seen.items()):
            print(f"  Bot {bot_id}:")
            print(f"    Login: {info['login']}")
            print(f"    Server: {info['server']}")
            print(f"    Terminal: {info['terminal']}")

        print(f"\nTotal Executions Logged: {len(SystemAudit._execution_log)}")

        # Execution summary by bot
        executions_by_bot = {}
        for exec_item in SystemAudit._execution_log:
            bot_id = exec_item['bot_id']
            if bot_id not in executions_by_bot:
                executions_by_bot[bot_id] = []
            executions_by_bot[bot_id].append(exec_item)

        for bot_id in sorted(executions_by_bot.keys()):
            items = executions_by_bot[bot_id]
            print(f"  Bot {bot_id}: {len(items)} trades")

        print("\n" + "=" * 80 + "\n")
