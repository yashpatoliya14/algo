import os, sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
from delta_trader import DeltaClient

load_dotenv()
api_key = os.getenv("DELTA_API_KEY")
api_secret = os.getenv("DELTA_API_SECRET")
base_url = os.getenv("DELTA_BASE_URL", "https://api.india.delta.exchange")

client = DeltaClient(api_key, api_secret, base_url)

product_id = 14830 # AVAXUSD

try:
    res = client._request("POST", f"/v2/products/{product_id}/orders/leverage", payload={"leverage": "2"}, auth=True)
    print("Set Leverage Response:", res)
except Exception as e:
    print("Error:", e)
    if hasattr(e, 'response') and e.response:
        print("Response:", e.response.text)
