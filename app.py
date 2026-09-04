import os
import threading
import time
from flask import Flask
import requests

app = Flask(__name__)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "YOUR_TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "YOUR_TELEGRAM_CHAT_ID")
TARGET_PRICE = float(os.getenv("TARGET_PRICE", "95000.00"))


def send_telegram_alert(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message}
    try:
        requests.post(url, json=payload)
    except Exception as e:
        print(f"Error sending Telegram alert: {e}")


def btc_monitor_loop():
    print("BTC Monitoring loop started...")
    url = "https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT"

    while True:
        try:
            response = requests.get(url, timeout=10)
            data = response.json()
            current_price = float(data["price"])
            print(f"Current BTC Price: ${current_price:.2f}")

            if current_price >= TARGET_PRICE:
                send_telegram_alert(
                    f"🚨 BTC Alert! Price reached ${current_price:.2f}"
                )
                time.sleep(300)

        except Exception as e:
            print(f"Error fetching BTC price: {e}")

        time.sleep(15)


threading.Thread(target=btc_monitor_loop, daemon=True).start()


@app.route("/")
def home():
    return "BTC Monitor Bot is active and running!"


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)