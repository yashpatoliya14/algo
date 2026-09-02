import os
import sys
import time
from delta_trader import DeltaTrader

# Colors for terminal
GREEN = "\033[92m"
RED = "\033[91m"
CYAN = "\033[96m"
WHITE = "\033[97m"
RESET = "\033[0m"

def main():
    print(f"\n{CYAN}======================================================{RESET}")
    print(f"{CYAN}       END-TO-END DEMO: ENTRY -> EXIT -> SL CLEANUP   {RESET}")
    print(f"{CYAN}======================================================{RESET}\n")

    os.environ["DRY_RUN"] = "false"
    
    try:
        trader = DeltaTrader()
    except Exception as e:
        print(f"{RED}[FAIL] Could not initialize DeltaTrader: {e}{RESET}")
        sys.exit(1)

    symbol = trader.symbol
    canon_sym = trader.symbol_canonical
    client = trader.client

    ticker = client.get_ticker(symbol)
    mark_price = float(ticker.get("mark_price", 0))
    print(f"  {GREEN}[OK] Live Price: ${mark_price:,.2f}{RESET}\n")

    # 1. Place Market Order (Entry)
    print(f"  {CYAN}[1/5] Placing Market Entry Order (Buy 1 contract)...{RESET}")
    entry_res = client.place_order(symbol, 1, "buy", "market_order")
    entry_id = entry_res.get('result', {}).get('id') or entry_res.get('id')
    print(f"  {GREEN}[OK] Entry Placed! ID: {entry_id}{RESET}\n")

    # 2. Place Stop Loss Order
    sl_price = mark_price * 0.90  # Far away so it doesn't trigger
    print(f"  {CYAN}[2/5] Placing Stop-Loss Order (Sell 1 contract @ ${sl_price:,.2f})...{RESET}")
    sl_res = client.place_order(symbol, 1, "sell", "stop_market_order", stop_price=sl_price, reduce_only=True)
    sl_id = sl_res.get('result', {}).get('id') or sl_res.get('id')
    print(f"  {GREEN}[OK] SL Placed! ID: {sl_id}{RESET}\n")

    # 3. Inject into bot state (this is what _execute_entry normally does)
    print(f"  {CYAN}[3/5] Registering position into bot memory...{RESET}")
    trader.positions[canon_sym] = {
        "direction": "long",
        "entry_price": mark_price,
        "size": 1,
        "stop_order_id": sl_id
    }
    print(f"  {GREEN}[OK] Bot is now tracking SL Order #{sl_id}{RESET}\n")
    
    time.sleep(2)  # Wait for exchange to register position

    # 4. Manually close the position (Simulating a Take-Profit limit order hitting on exchange)
    print(f"  {CYAN}[4/5] Simulating Manual/TP Exit (Market Sell 1 contract)...{RESET}")
    exit_res = client.place_order(symbol, 1, "sell", "market_order", reduce_only=True)
    exit_id = exit_res.get('result', {}).get('id') or exit_res.get('id')
    print(f"  {GREEN}[OK] Position Closed! Exit ID: {exit_id}{RESET}\n")

    time.sleep(2)  # Wait for exchange to clear the position balance

    # 5. Run reconciliation (The bot should detect position is gone, and cancel the SL)
    print(f"  {CYAN}[5/5] Triggering reconcile_positions()... Watch for SL cancellation!{RESET}")
    trader.reconcile_positions()
    
    if canon_sym not in trader.positions:
        print(f"\n  {GREEN}[SUCCESS] Bot successfully cleared position and cancelled SL Order #{sl_id}!{RESET}")
    else:
        print(f"\n  {RED}[FAIL] Position is still in memory!{RESET}")

if __name__ == "__main__":
    main()
