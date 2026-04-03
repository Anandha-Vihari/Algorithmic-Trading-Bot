"""
Multi Algo Trading System - Analytics Dashboard (Streamlit)

Read-only dashboard displaying trading performance metrics from trades_history.jsonl.
No modifications to underlying data or trading systems.
"""

import streamlit as st
import pandas as pd
import json
from datetime import datetime, timedelta
from pathlib import Path

# ─────────────────────────────────────────────────────────────────────────────
# SECTION 1: Load Data with Caching
# ─────────────────────────────────────────────────────────────────────────────

@st.cache_data
def load_data():
    """
    Load trades from trades_history.jsonl.

    Format: One JSON object per line (JSONL)
    Expected fields: symbol/pair, side, entry_price, exit_price, pnl, strategy, close_time, max_profit, max_loss

    Returns:
        DataFrame or empty DataFrame if file doesn't exist/is empty
    """
    trades_file = Path("trades_history.jsonl")

    if not trades_file.exists():
        return pd.DataFrame()

    trades = []
    try:
        with open(trades_file, 'r') as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        trade = json.loads(line)
                        trades.append(trade)
                    except json.JSONDecodeError:
                        continue
    except Exception as e:
        st.error(f"Error reading trades_history.jsonl: {e}")
        return pd.DataFrame()

    if not trades:
        return pd.DataFrame()

    df = pd.DataFrame(trades)
    return df


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 2: Preprocess Data
# ─────────────────────────────────────────────────────────────────────────────

def preprocess(df):
    """
    Preprocess trades dataframe.

    Converts:
    - close_time string to datetime object
    - Calculates cumulative PnL
    - Calculates trade efficiency based on MFE

    Returns:
        Preprocessed DataFrame
    """
    if df.empty:
        return df

    df = df.copy()

    # Convert close_time string to datetime if present
    if 'close_time' in df.columns:
        df['close_time'] = pd.to_datetime(df['close_time'], errors='coerce')
    else:
        # Fallback: use current time if close_time not present
        df['close_time'] = datetime.now()

    # Sort by close_time
    df = df.sort_values('close_time', ascending=True).reset_index(drop=True)

    # Calculate cumulative PnL
    if 'pnl' in df.columns:
        df['cum_pnl'] = df['pnl'].cumsum()
    else:
        df['cum_pnl'] = 0

    # Calculate trade efficiency based on MFE
    # Efficiency = PnL / Max Profit
    if 'pnl' in df.columns and 'max_profit' in df.columns:
        df['efficiency'] = df['pnl'] / df['max_profit']
        df.loc[df['max_profit'].isna() | (df['max_profit'] <= 0), 'efficiency'] = None
    else:
        df['efficiency'] = None

    return df


# ─────────────────────────────────────────────────────────────────────────────
# MAIN DASHBOARD
# ─────────────────────────────────────────────────────────────────────────────

def main():
    st.set_page_config(page_title="Multi Algo Trading Dashboard", layout="wide")
    st.title("📊 Multi Algo Trading Dashboard")

    # Load and preprocess data
    df = load_data()

    if df.empty:
        st.warning("⚠️ No trade data available. Waiting for trades_history.jsonl...")
        return

    df = preprocess(df)

    # ─────────────────────────────────────────────────────────────────────────
    # SECTION 3: Sidebar Filters
    # ─────────────────────────────────────────────────────────────────────────

    st.sidebar.header("🔧 Filters")

    # Refresh button
    if st.sidebar.button("🔄 Refresh Data", help="Clear cache and reload trades_history.jsonl"):
        st.cache_data.clear()
        st.rerun()

    # Strategy filter
    available_strategies = df['strategy'].unique() if 'strategy' in df.columns else []
    selected_strategies = st.sidebar.multiselect(
        "Strategy",
        options=sorted(available_strategies),
        default=list(sorted(available_strategies))
    )

    # Date range filter
    if 'close_time' in df.columns:
        min_date = df['close_time'].min()
        max_date = df['close_time'].max()
        date_range = st.sidebar.date_input(
            "Date Range",
            value=(min_date.date(), max_date.date()),
            min_value=min_date.date(),
            max_value=max_date.date()
        )
        if len(date_range) == 2:
            start_date, end_date = date_range
            df = df[(df['close_time'].dt.date >= start_date) & (df['close_time'].dt.date <= end_date)]

    # Apply strategy filter
    df = df[df['strategy'].isin(selected_strategies)]

    if df.empty:
        st.warning("No trades match the selected filters.")
        return

    # ─────────────────────────────────────────────────────────────────────────
    # SECTION 4: Overall Metrics
    # ─────────────────────────────────────────────────────────────────────────

    st.header("📈 Overall Metrics")

    col1, col2, col3 = st.columns(3)

    total_trades = len(df)
    total_pnl = df['pnl'].sum() if 'pnl' in df.columns else 0
    winning_trades = len(df[df['pnl'] > 0]) if 'pnl' in df.columns else 0
    win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0

    with col1:
        st.metric("Total Trades", f"{total_trades:,}")

    with col2:
        st.metric("Total PnL", f"${total_pnl:.2f}")

    with col3:
        st.metric("Win Rate", f"{win_rate:.1f}%")

    # ─────────────────────────────────────────────────────────────────────────
    # SECTION 5: Equity Curve
    # ─────────────────────────────────────────────────────────────────────────

    st.header("📉 Equity Curve")

    if 'cum_pnl' in df.columns and 'close_time' in df.columns:
        equity_df = df[['close_time', 'cum_pnl']].copy()
        equity_df = equity_df.set_index('close_time')
        st.line_chart(equity_df)
    else:
        st.info("Insufficient data for equity curve.")

    # ─────────────────────────────────────────────────────────────────────────
    # SECTION 6: Strategy Performance
    # ─────────────────────────────────────────────────────────────────────────

    st.header("🎯 Strategy Performance")

    if 'strategy' in df.columns:
        strategy_stats = []
        for strategy in df['strategy'].unique():
            strat_df = df[df['strategy'] == strategy]
            strat_total_pnl = strat_df['pnl'].sum() if 'pnl' in df.columns else 0
            strat_trades = len(strat_df)
            strat_wins = len(strat_df[strat_df['pnl'] > 0]) if 'pnl' in df.columns else 0
            strat_win_rate = (strat_wins / strat_trades * 100) if strat_trades > 0 else 0
            strat_avg_pnl = strat_df['pnl'].mean() if 'pnl' in df.columns else 0

            strategy_stats.append({
                'Strategy': strategy,
                'Trades': strat_trades,
                'Total PnL': f"${strat_total_pnl:.2f}",
                'Win Rate': f"{strat_win_rate:.1f}%",
                'Avg PnL': f"${strat_avg_pnl:.2f}"
            })

        st.dataframe(pd.DataFrame(strategy_stats), use_container_width=True)
    else:
        st.info("Strategy data not available.")

    # ─────────────────────────────────────────────────────────────────────────
    # SECTION 7: Per-Pair Performance
    # ─────────────────────────────────────────────────────────────────────────

    st.header("💱 Per-Pair Performance")

    symbol_col = 'symbol' if 'symbol' in df.columns else ('pair' if 'pair' in df.columns else None)
    if symbol_col:
        pair_stats = []
        for symbol in sorted(df[symbol_col].unique()):
            pair_df = df[df[symbol_col] == symbol]
            pair_total_pnl = pair_df['pnl'].sum() if 'pnl' in df.columns else 0
            pair_trades = len(pair_df)
            pair_wins = len(pair_df[pair_df['pnl'] > 0]) if 'pnl' in df.columns else 0
            pair_win_rate = (pair_wins / pair_trades * 100) if pair_trades > 0 else 0
            pair_avg_pnl = pair_df['pnl'].mean() if 'pnl' in df.columns else 0

            pair_stats.append({
                'Pair': symbol,
                'Trades': pair_trades,
                'Total PnL': f"${pair_total_pnl:.2f}",
                'Win Rate': f"{pair_win_rate:.1f}%",
                'Avg PnL': f"${pair_avg_pnl:.2f}"
            })

        st.dataframe(pd.DataFrame(pair_stats), use_container_width=True)
    else:
        st.info("Pair data not available.")

    # ─────────────────────────────────────────────────────────────────────────
    # SECTION 8: MFE/MAE Analysis
    # ─────────────────────────────────────────────────────────────────────────

    st.header("📊 MFE/MAE Analysis")

    mfe_mae_available = all(col in df.columns for col in ['max_profit', 'max_loss', 'strategy'])

    if mfe_mae_available:
        mfe_mae_stats = []
        for strategy in df['strategy'].unique():
            strat_df = df[df['strategy'] == strategy]
            avg_mfe = strat_df['max_profit'].mean() if 'max_profit' in df.columns else 0
            avg_mae = strat_df['max_loss'].mean() if 'max_loss' in df.columns else 0

            mfe_mae_stats.append({
                'Strategy': strategy,
                'Avg Max Profit (MFE)': f"${avg_mfe:.2f}",
                'Avg Max Loss (MAE)': f"${abs(avg_mae):.2f}"
            })

        st.dataframe(pd.DataFrame(mfe_mae_stats), use_container_width=True)
    else:
        st.info("MFE/MAE data not available (ensure max_profit and max_loss columns exist).")

    # ─────────────────────────────────────────────────────────────────────────
    # SECTION 9: Trade Efficiency
    # ─────────────────────────────────────────────────────────────────────────

    st.header("⚡ Trade Efficiency")

    if 'efficiency' in df.columns and 'strategy' in df.columns:
        efficiency_stats = []
        for strategy in df['strategy'].unique():
            strat_df = df[df['strategy'] == strategy]
            valid_efficiency = strat_df['efficiency'].dropna()
            avg_efficiency = valid_efficiency.mean() if len(valid_efficiency) > 0 else 0

            efficiency_stats.append({
                'Strategy': strategy,
                'Avg Efficiency': f"{avg_efficiency:.2f}"
            })

        st.dataframe(pd.DataFrame(efficiency_stats), use_container_width=True)
    else:
        st.info("Efficiency data not available.")

    # ─────────────────────────────────────────────────────────────────────────
    # SECTION 10: Recent Trades
    # ─────────────────────────────────────────────────────────────────────────

    st.header("🔍 Recent Trades")

    # Display last 50 trades
    recent_trades = df.tail(50).copy()

    # Format dataframe for display
    display_cols = []
    if 'close_time' in recent_trades.columns:
        display_cols.append('close_time')
    symbol_col = 'symbol' if 'symbol' in recent_trades.columns else ('pair' if 'pair' in recent_trades.columns else None)
    if symbol_col:
        display_cols.append(symbol_col)
    if 'side' in recent_trades.columns:
        display_cols.append('side')
    if 'entry_price' in recent_trades.columns:
        display_cols.append('entry_price')
    if 'exit_price' in recent_trades.columns:
        display_cols.append('exit_price')
    if 'pnl' in recent_trades.columns:
        display_cols.append('pnl')
    if 'strategy' in recent_trades.columns:
        display_cols.append('strategy')
    if 'efficiency' in recent_trades.columns:
        display_cols.append('efficiency')

    if display_cols:
        display_df = recent_trades[display_cols].copy()

        # Format numeric columns
        if 'entry_price' in display_df.columns:
            display_df['entry_price'] = display_df['entry_price'].apply(lambda x: f"{x:.5f}")
        if 'exit_price' in display_df.columns:
            display_df['exit_price'] = display_df['exit_price'].apply(lambda x: f"{x:.5f}")
        if 'pnl' in display_df.columns:
            display_df['pnl'] = display_df['pnl'].apply(lambda x: f"${x:.2f}")
        if 'efficiency' in display_df.columns:
            display_df['efficiency'] = display_df['efficiency'].apply(lambda x: f"{x:.2f}" if pd.notna(x) else "—")
        if 'close_time' in display_df.columns:
            display_df['close_time'] = display_df['close_time'].apply(lambda x: x.strftime('%Y-%m-%d %H:%M:%S') if pd.notna(x) else "")

        st.dataframe(display_df, use_container_width=True)
    else:
        st.info("No trade data available.")


if __name__ == "__main__":
    main()
