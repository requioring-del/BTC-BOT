import asyncio
import json
import requests
import websockets

# --- CONFIGURATION ---
TELEGRAM_BOT_TOKEN = "8811292743:AAEJBiVXN7j0hysvOpx7TjqHnN44goXX_-o"
TELEGRAM_CHAT_ID = "8595599623"
TARGET_PRICE = 70000.00  # Set your desired alert price here


def send_telegram_alert(message):
    """Sends a notification directly to your Telegram."""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message}
    try:
        response = requests.post(url, json=payload)
        if response.status_code == 200:
            print("\n[SUCCESS] Alert sent to Telegram!")
        else:
            print(f"\n[ERROR] Telegram API response: {response.text}")
    except Exception as e:
        print(f"\n[ERROR] Network error: {e}")


async def monitor_btc():
    url = "wss://stream.binance.com:9443/ws/btcusdt@trade"

    print("Connecting to live BTC/USDT market stream...")
    async with websockets.connect(url) as websocket:
        print("Connected! Listening to real-time market data...")

        # Test message sent immediately when you start the script
        send_telegram_alert(
            f"🚀 BTC Monitor Bot is live!\nTarget set at: ${TARGET_PRICE:,.2f}"
        )

        while True:
            response = await websocket.recv()
            data = json.loads(response)
            current_price = float(data["p"])

            # Live terminal price display
            print(f"Current BTC Price: ${current_price:,.2f}", end="\r")

            if current_price >= TARGET_PRICE:
                alert_text = (
                    f"🚨 PRICE ALERT!\nBTC has reached: ${current_price:,.2f}"
                )
                send_telegram_alert(alert_text)
                break  # Stops script after firing alert


if __name__ == "__main__":
    asyncio.run(monitor_btc())