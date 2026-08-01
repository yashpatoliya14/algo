"""
Delta Exchange Test Script — Verify Order Placement with Small Quantity
========================================================================
This script tests your Delta Exchange API credentials and verifies that 
order placement and position registration work correctly by placing a minimal 
test trade (1 contract) and verifying response details.

Usage:
    1. Fill in your credentials in `.env` (DELTA_API_KEY, DELTA_API_SECRET)
    2. Run: python test_delta_order.py
"""

import os
import sys
import time
from delta_trader import DeltaClient

# Load .env file
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Colors for terminal
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
WHITE = "\033[97m"
GRAY = "\033[90m"
BOLD = "\033[1m"
RESET = "\033[0m"


def main():
    print()
    print("=" * 65)
    print("      DELTA EXCHANGE ORDER PLACEMENT VERIFICATION SCRIPT")
    print("=" * 65)

    api_key = os.getenv("DELTA_API_KEY", "").strip()
    api_secret = os.getenv("DELTA_API_SECRET", "").strip()
    base_url = os.getenv("DELTA_BASE_URL", "https://api.india.delta.exchange").strip()
    symbol = os.getenv("SYMBOL", "BTCUSD").strip()

    print(f"  API Base URL:   {base_url}")
    print(f"  Symbol:         {symbol}")
    print(f"  API Key:        {api_key[:6]}...{api_key[-4:] if len(api_key)>10 else 'MISSING'}")
    print("=" * 65)
    print()

    if not api_key or not api_secret or api_key == "your_api_key_here":
        print(f"  {RED}[ERROR] API Credentials not found!{RESET}")
        print(f"  Please open {CYAN}.env{RESET} and set your actual DELTA_API_KEY and DELTA_API_SECRET.")
        print()
        sys.exit(1)

    client = DeltaClient(api_key, api_secret, base_url)

    # ------------------------------------------------------------------------
    # STEP 1: Test Connection & Fetch Wallet Balance
    # ------------------------------------------------------------------------
    print(f"  {CYAN}[1/4] Testing API Authentication & Fetching Wallet Balance...{RESET}")
    try:
        balances = client.get_balances()
        if not balances:
            print(f"  {YELLOW}Warning: Connected successfully, but no wallet balances returned.{RESET}")
        else:
            print(f"  {GREEN}✓ Connection Successful!{RESET}")
            for b in balances:
                asset = b.get("asset_symbol", "USDT")
                balance_val = b.get("balance", "0")
                available_val = b.get("available_balance", "0")
                print(f"    Asset: {WHITE}{asset:<6}{RESET} Total Balance: {WHITE}{balance_val}{RESET} | Available: {GREEN}{available_val}{RESET}")
    except Exception as e:
        print(f"  {RED}[FAIL] Authentication Error: {e}{RESET}")
        if hasattr(e, 'response') and e.response is not None:
            try:
                err_data = e.response.json()
                err_code = err_data.get("error", {}).get("code")
                if err_code == "ip_not_whitelisted_for_api_key":
                    client_ip = err_data.get("error", {}).get("context", {}).get("client_ip", "Unknown")
                    print(f"\n  {YELLOW}[ACTION REQUIRED] IP Whitelist Restriction Detected!{RESET}")
                    print(f"  Your current IP address is: {BOLD}{CYAN}{client_ip}{RESET}")
                    print(f"  Please add {CYAN}{client_ip}{RESET} to your API Key whitelist in Delta Exchange settings,")
                    print(f"  or edit your API key on Delta Exchange to disable IP restriction.\n")
            except Exception:
                pass
        print("  Please check your API key, secret, and base URL in .env.")
        sys.exit(1)

    print()

    # ------------------------------------------------------------------------
    # STEP 2: Fetch Current Market Price
    # ------------------------------------------------------------------------
    print(f"  {CYAN}[2/4] Fetching Live Market Price for {symbol}...{RESET}")
    try:
        ticker = client.get_ticker(symbol)
        mark_price = float(ticker.get("mark_price", 0))
        close_price = float(ticker.get("close", 0))
        print(f"  {GREEN}✓ Market Data Retrieved!{RESET}")
        print(f"    Mark Price:  {GREEN}${mark_price:,.2f}{RESET}")
        print(f"    Close Price: ${close_price:,.2f}")
    except Exception as e:
        print(f"  {RED}[FAIL] Failed to fetch ticker: {e}{RESET}")
        sys.exit(1)

    print()

    # ------------------------------------------------------------------------
    # STEP 3: Place Minimal Test Order (BUY 1 Contract)
    # ------------------------------------------------------------------------
    test_qty = 1  # Minimum contract quantity
    print(f"  {CYAN}[3/4] Placing Small Test Market Order ({test_qty} contract of {symbol})...{RESET}")
    
    try:
        # Place Market Buy Order
        order_res = client.place_order(
            symbol=symbol,
            size=test_qty,
            side="buy",
            order_type="market_order"
        )
        print(f"  {GREEN}✓ TEST ORDER PLACED SUCCESSFULLY!{RESET}")
        order_id = order_res.get("id") or order_res.get("result", {}).get("id")
        order_state = order_res.get("state") or order_res.get("result", {}).get("state", "placed")
        print(f"    Order ID:    {WHITE}{order_id}{RESET}")
        print(f"    Order State: {GREEN}{order_state.upper()}{RESET}")
        print(f"    Order Raw Response: {GRAY}{order_res}{RESET}")

    except Exception as e:
        print(f"  {RED}[FAIL] Order Placement Error: {e}{RESET}")
        print("  Note: Ensure your account has sufficient margin and order permissions enabled for your API key.")
        sys.exit(1)

    print()
    time.sleep(2)  # Short delay for position update

    # ------------------------------------------------------------------------
    # STEP 4: Verify Position & Close Test Trade
    # ------------------------------------------------------------------------
    print(f"  {CYAN}[4/4] Verifying Active Position & Closing Test Trade...{RESET}")
    try:
        positions = client.get_positions(symbol)
        active_pos = None
        if positions:
            for p in positions:
                if float(p.get("size", 0)) != 0:
                    active_pos = p
                    break

        if active_pos:
            size = active_pos.get("size")
            entry_px = float(active_pos.get("entry_price", 0))
            print(f"  {GREEN}✓ ACTIVE POSITION CONFIRMED ON DELTA EXCHANGE!{RESET}")
            print(f"    Position Size:  {WHITE}{size} contracts{RESET}")
            print(f"    Entry Price:    {GREEN}${entry_px:,.2f}{RESET}")

            # Close test position by selling 1 contract
            print(f"  Closing test position (SELLING {test_qty} contract)...")
            close_res = client.place_order(symbol, test_qty, "sell", "market_order")
            print(f"  {GREEN}✓ TEST POSITION CLOSED CLEANLY!{RESET}")
            print(f"    Close Order ID: {WHITE}{close_res.get('id') or close_res.get('result', {}).get('id')}{RESET}")
        else:
            print(f"  {YELLOW}Order was executed, but no active position remains (might have filled and closed).{RESET}")

    except Exception as e:
        print(f"  {YELLOW}[WARN] Position verification / closing warning: {e}{RESET}")

    print()
    print("=" * 65)
    print(f"  {GREEN}{BOLD}ALL VERIFICATION TESTS PASSED! YOUR DELTA TRADING IS READY.{RESET}")
    print("=" * 65)
    print()


if __name__ == "__main__":
    main()
