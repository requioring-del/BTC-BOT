import os
import threading
import time
from flask import Flask
import requests

app = Flask(__name__)

# --- CONFIGURATION ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "YOUR_TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "YOUR_TELEGRAM_CHAT_ID")
TARGET_PRICE = float(os.getenv("TARGET_PRICE", "95000.00"))
MY_RENDER_URL = os.getenv(
    "MY_RENDER_URL", "https://btc-bot-kq6n.onrender.com"
)

latest_btc_price = "Fetching..."


def send_telegram_alert(message):
  url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
  payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message}
  try:
    requests.post(url, json=payload, timeout=5)
  except Exception as e:
    print(f"Error sending Telegram alert: {e}", flush=True)


def btc_monitor_loop():
  """Background thread to monitor BTC price."""
  global latest_btc_price
  print("BTC Monitoring loop started...", flush=True)
  url = "https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT"

  while True:
    try:
      response = requests.get(url, timeout=10)
      data = response.json()
      current_price = float(data["price"])
      latest_btc_price = f"${current_price:,.2f}"

      print(f"Current BTC Price: {latest_btc_price}", flush=True)

      if current_price >= TARGET_PRICE:
        send_telegram_alert(f"🚨 BTC Alert! Price reached ${current_price:,.2f}")
        time.sleep(300)

    except Exception as e:
      print(f"Error fetching BTC price: {e}", flush=True)

    time.sleep(15)


def self_ping_loop():
  """Background thread to ping itself every 10 minutes to prevent sleep."""
  time.sleep(30)  # Wait for server startup
  while True:
    try:
      print("Sending self-ping request...", flush=True)
      requests.get(MY_RENDER_URL, timeout=10)
    except Exception as e:
      print(f"Self-ping failed: {e}", flush=True)
    time.sleep(600)  # Ping every 10 minutes


# Start background processes
threading.Thread(target=btc_monitor_loop, daemon=True).start()
threading.Thread(target=self_ping_loop, daemon=True).start()


@app.route("/")
def home():
  return f"""
    <html>
        <head><title>BTC Bot Status</title></head>
        <body style="font-family: Arial; text-align: center; padding-top: 50px;">
            <h2>🟢 BTC Monitor Bot is Active</h2>
            <h1>Current BTC Price: <span style="color: green;">{latest_btc_price}</span></h1>
            <p>Checking price every 15 seconds. Self-pinging active.</p>
        </body>
    </html>
    """


if __name__ == "__main__":
  port = int(os.environ.get("PORT", 5000))
  app.run(host="0.0.0.0", port=port)