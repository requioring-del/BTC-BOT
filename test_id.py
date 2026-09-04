import requests

TOKEN = "8811292743:AAEJBiVXN7j0hysvOpx7TjqHnN44goXX_-o"

# 1. Fetch live incoming messages
updates_url = f"https://api.telegram.org/bot{TOKEN}/getUpdates"
response = requests.get(updates_url).json()

if response.get("result") and len(response["result"]) > 0:
    # Read the latest chat ID automatically
    real_chat_id = response["result"][-1]["message"]["chat"]["id"]
    print(f"✅ FOUND YOUR REAL CHAT ID: {real_chat_id}")

    # 2. Test message
    send_url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {
        "chat_id": real_chat_id,
        "text": "hey daddy",
    }
    send_res = requests.post(send_url, json=payload).json()
    print("Delivery Status:", send_res)
else:
    print("❌ STILL NOT FOUND!")
    print(
        "Please open https://t.me/BTeeCeeBot in Telegram, send 'hello', and run this file again."
    )