import os
import sys
import time
import json
from datetime import datetime, timezone
from delta_trader import DeltaClient, DeltaTrader

# Colors for terminal
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
WHITE = "\033[97m"
RESET = "\033[0m"

def main():
    print(f"\n{CYAN}======================================================{RESET}")
    print(f"{CYAN}       LIMIT ORDER DEMO & CANCELLATION TEST           {RESET}")
    print(f"{CYAN}======================================================{RESET}\n")

    # 1. Initialize Trader (which initializes DeltaClient)
    # Ensure DRY_RUN is False for the test if you want actual API interaction
    os.environ["DRY_RUN"] = "false"
    
    try:
        trader = DeltaTrader()
    except Exception as e:
        print(f"{RED}[FAIL] Could not initialize DeltaTrader: {e}{RESET}")
        print("Please check your .env file for API credentials.")
        sys.exit(1)

    symbol = trader.symbol
    client = trader.client

    print(f"  {CYAN}[1/4] Fetching Live Market Price for {symbol}...{RESET}")
    try:
        ticker = client.get_ticker(symbol)
        mark_price = float(ticker.get("mark_price", 0))
        print(f"  {GREEN}[OK] Market Data Retrieved! Mark Price: ${mark_price:,.2f}{RESET}\n")
    except Exception as e:
        print(f"  {RED}[FAIL] Failed to fetch ticker: {e}{RESET}")
        sys.exit(1)

    # 2. Place a Limit Order far away from market price so it doesn't fill
    limit_price = mark_price * 0.90  # 10% below market price
    test_qty = 1

    print(f"  {CYAN}[2/4] Placing Limit Order (Buy {test_qty} contract @ ${limit_price:,.2f})...{RESET}")
    try:
        order_res = client.place_order(
            symbol=symbol,
            size=test_qty,
            side="buy",
            order_type="limit_order",
            limit_price=limit_price
        )
        order_id = order_res.get("id") or order_res.get("result", {}).get("id")
        print(f"  {GREEN}[OK] LIMIT ORDER PLACED SUCCESSFULLY!{RESET}")
        print(f"    Order ID: {WHITE}{order_id}{RESET}")

        # 3. Record the order using the newly added record_order implementation
        print(f"\n  {CYAN}[3/4] Testing record_order logic...{RESET}")
        trader.record_order("limit_order", symbol, str(order_id), {
            "direction": "long",
            "side": "buy",
            "size": test_qty,
            "limit_price": limit_price,
            "demo": True
        })
        print(f"  {GREEN}[OK] Order recorded to cache/orders.log{RESET}")

    except Exception as e:
        print(f"  {RED}[FAIL] Order Placement Error: {e}{RESET}")
        sys.exit(1)

    # Give the exchange a second to process the order
    time.sleep(2)

    # 4. Cancel the Limit Order by ID (testing specific cancellation)
    print(f"\n  {CYAN}[4/4] Testing Targeted Cancellation (cancel_order_by_id)...{RESET}")
    try:
        cancel_res = client.cancel_order_by_id(order_id)
        print(f"  {GREEN}[OK] LIMIT ORDER #{order_id} CANCELLED CLEANLY!{RESET}")
        print(f"    Cancellation response state: {cancel_res.get('state', cancel_res.get('result', {}).get('state', 'cancelled'))}")
    except Exception as e:
        print(f"  {RED}[FAIL] Failed to cancel order #{order_id}: {e}{RESET}")
        # Cleanup fallback just in case
        client.cancel_all_orders(symbol)
        sys.exit(1)

    print(f"\n{GREEN}======================================================{RESET}")
    print(f"{GREEN}  DEMO COMPLETE: Limits & targeted cancellations work!{RESET}")
    print(f"{GREEN}======================================================{RESET}\n")

if __name__ == "__main__":
    main()
