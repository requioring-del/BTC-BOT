import os
import threading
import time
from flask import Flask
import requests

app = Flask(__name__)

TARGET_PRICE = float(os.getenv("TARGET_PRICE", "95000.00"))
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

latest_btc_price = "Initializing..."


def btc_monitor_loop():
  global latest_btc_price
  # Wait 5 seconds after startup before the first API request to let Gunicorn bind fully
  time.sleep(5)
  print("BTC Monitoring loop started...", flush=True)
  url = "https://api.coinbase.com/v2/prices/BTC-USD/spot"

  while True:
    try:
      response = requests.get(url, timeout=5)
      data = response.json()

      if "data" in data and "amount" in data["data"]:
        current_price = float(data["data"]["amount"])
        latest_btc_price = f"${current_price:,.2f}"
        print(f"Current BTC Price: {latest_btc_price}", flush=True)
      else:
        print(f"API Error: {data}", flush=True)

    except Exception as e:
      print(f"Error fetching price: {e}", flush=True)

    time.sleep(15)


# Start daemon thread so it doesn't block worker startup
threading.Thread(target=btc_monitor_loop, daemon=True).start()


@app.route("/")
def home():
  return f"BTC Monitor Bot is Active! Live Price: {latest_btc_price}"


if __name__ == "__main__":
  port = int(os.environ.get("PORT", 10000))
  app.run(host="0.0.0.0", port=port)