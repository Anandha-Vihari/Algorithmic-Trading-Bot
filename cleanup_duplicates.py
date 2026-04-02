"""Close all open positions to clean up duplicates."""
import MetaTrader5 as mt5
from config import MT5_LOGIN, MT5_PASSWORD, MT5_SERVER, MT5_EXE
import subprocess
import time

# Initialize MT5
if not mt5.initialize():
    print("MT5 not running - launching...")
    subprocess.Popen(MT5_EXE, creationflags=subprocess.CREATE_NO_WINDOW)
    time.sleep(10)

mt5.login(MT5_LOGIN, MT5_PASSWORD, MT5_SERVER)

# Get all positions
positions = mt5.positions_get()
if positions:
    print(f"Found {len(positions)} open positions")
    closed_count = 0
    for pos in positions:
        print(f"  T{pos.ticket}: {pos.symbol} {('BUY' if pos.type == 0 else 'SELL')} @ {pos.price_open:.5f}")
        
        # Close each position
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": pos.symbol,
            "volume": pos.volume,
            "type": mt5.ORDER_TYPE_SELL if pos.type == 0 else mt5.ORDER_TYPE_BUY,
            "position": pos.ticket,
            "deviation": 50,
            "magic": 777,
            "comment": "cleanup",
            "type_filling": mt5.ORDER_FILLING_IOC,
            "type_time": mt5.ORDER_TIME_GTC
        }
        
        result = mt5.order_send(request)
        if result and result.retcode == mt5.TRADE_RETCODE_DONE:
            print(f"    [OK] Closed T{pos.ticket}")
            closed_count += 1
        else:
            print(f"    [FAIL] retcode={result.retcode if result else 'None'}")
    
    print(f"\nClosed {closed_count}/{len(positions)} positions")
else:
    print("No open positions")

mt5.shutdown()
