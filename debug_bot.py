import os
import requests

TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN", "8811292743:AAEJBiVXN7j0hysvOpx7TjqHnN44goXX_-o"
)
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "8595599623")

url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
payload = {"chat_id": CHAT_ID, "text": "🎉 Success! Token and Chat ID fixed."}

res = requests.post(url, json=payload).json()
print("Telegram API Response:", res)